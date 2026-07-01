"""Endpoint unique utilisé par l'agent IA et le workflow n8n."""

import hmac
import json
import logging
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .exceptions import CommerceError
from .models import (
    Cart,
    ConversationState,
    HumanTransfer,
    ProcessedRequest,
    ProductSelection,
    ShopPolicy,
    UserOrder,
)
from .paytech_client import PayTechClient
from .woo_client import WooCommerceClient

logger = logging.getLogger(__name__)

STATE_SEQUENCE = [
    "browsing",
    "selecting",
    "cart_review",
    "confirming",
    "ordering",
    "payment_pending",
    "completed",
]
ALLOWED_STATES = set(STATE_SEQUENCE) | {"human_takeover"}

ALLOWED_ACTIONS = {
    "search_products",
    "get_product",
    "create_order",
    "generate_payment",
    "get_order_status",
    "cancel_order",
    "request_refund",
    "update_order",
    "modify_order",
    "get_tracking",
    "validate_coupon",
    "check_variant_stock",
    "cart_add",
    "cart_remove",
    "cart_update_quantity",
    "cart_view",
    "cart_clear",
    "save_selection_list",
    "get_product_by_position",
    "get_state",
    "set_state",
    "revert_state",
    "transfer_to_human",
    "check_human_status",
    "get_policy",
    "conversation_turn",
}


def _required(data, *fields):
    missing = [field for field in fields if data.get(field) in (None, "", [])]
    if missing:
        raise CommerceError(f"Champ(s) requis manquant(s) : {', '.join(missing)}.", 400)


def _decimal(value, field, *, positive=False):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CommerceError(f"Le champ {field} doit être un nombre.", 400) from exc
    if positive and parsed <= 0:
        raise CommerceError(f"Le champ {field} doit être positif.", 400)
    if parsed < 0:
        raise CommerceError(f"Le champ {field} ne peut pas être négatif.", 400)
    return parsed


def _platform(value):
    normalized = str(value or "").strip().casefold()
    aliases = {"woo": "woocommerce", "woocommerce": "woocommerce"}
    if normalized not in aliases:
        raise CommerceError(
            "Cette API MVP accepte uniquement la plateforme 'woocommerce'.", 400
        )
    return aliases[normalized]


def _client(platform):
    _platform(platform)
    return WooCommerceClient()


def _woo_only(data):
    if data.get("platform"):
        _platform(data["platform"])
    return WooCommerceClient()


def _validate_cart(cart, default_platform=None):
    if not isinstance(cart, list) or not cart:
        raise CommerceError("Le panier doit être une liste non vide.", 400)
    cleaned = []
    for index, item in enumerate(cart):
        if not isinstance(item, dict) or not item.get("product_id"):
            raise CommerceError(f"L'article {index + 1} doit contenir product_id.", 400)
        platform = _platform(item.get("platform") or default_platform)
        try:
            quantity = int(item.get("quantity", 1))
        except (TypeError, ValueError) as exc:
            raise CommerceError(f"Quantité invalide pour l'article {index + 1}.", 400) from exc
        if quantity <= 0:
            raise CommerceError(f"La quantité de l'article {index + 1} doit être positive.", 400)
        cleaned.append({**item, "quantity": quantity, "platform": platform})
    return "woocommerce", cleaned


def _state(user_id):
    state, _ = ConversationState.objects.get_or_create(user_id=str(user_id))
    return state


def _state_payload(state):
    return {
        "user_id": state.user_id,
        "state": state.state,
        "previous_state": state.previous_state,
        "pending_product_id": state.pending_product_id,
        "pending_order_id": state.pending_order_id,
        "pending_amount": str(state.pending_amount) if state.pending_amount is not None else None,
    }


def _move_state(state, new_state, **pending):
    if new_state not in ALLOWED_STATES:
        raise CommerceError(f"État invalide : {new_state}.", 400)
    if new_state != "human_takeover":
        current_index = STATE_SEQUENCE.index(state.state) if state.state in STATE_SEQUENCE else 0
        new_index = STATE_SEQUENCE.index(new_state)
        if new_index > current_index + 1:
            raise CommerceError(
                f"Transition interdite de '{state.state}' vers '{new_state}'.", 409
            )
    state.previous_state = state.state
    state.state = new_state
    for field in ("pending_product_id", "pending_order_id", "pending_amount"):
        if field in pending:
            setattr(state, field, pending[field])
    state.save()
    return state


def _cart_payload(user_id):
    rows = Cart.objects.filter(user_id=str(user_id)).order_by("id")
    items = [
        {
            "product_id": row.product_id,
            "product_name": row.product_name,
            "quantity": row.quantity,
            "price": str(row.price),
            "line_total": str(row.price * row.quantity),
            "platform": row.platform,
        }
        for row in rows
    ]
    total = sum((Decimal(item["line_total"]) for item in items), Decimal("0"))
    return {"user_id": str(user_id), "items": items, "total": str(total), "currency": "XOF"}


def _owned_order(data, client=None):
    _required(data, "order_id", "user_id")
    order_id, user_id = str(data["order_id"]), str(data["user_id"])
    if UserOrder.objects.filter(order_id=order_id, user_id=user_id).exists():
        return client or _woo_only(data)

    # Compatibilité avec les commandes créées avant la table user_orders.
    woo = client or _woo_only(data)
    if not woo.order_belongs_to_user(order_id, user_id):
        raise CommerceError("Commande introuvable pour ce compte.", 404)
    UserOrder.objects.get_or_create(
        order_id=order_id,
        defaults={"user_id": user_id, "platform": "woocommerce"},
    )
    return woo


def _idempotent(action, data, callback):
    _required(data, "idempotency_key")
    key = str(data["idempotency_key"]).strip()
    existing = ProcessedRequest.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.action != action:
            raise CommerceError("Cette clé d'idempotence appartient à une autre action.", 409)
        if existing.result.get("_processing"):
            raise CommerceError("Cette opération est déjà en cours.", 409)
        return existing.result
    try:
        reservation = ProcessedRequest.objects.create(
            idempotency_key=key, action=action, result={"_processing": True}
        )
    except IntegrityError:
        # Une autre exécution a réservé la même clé entre la lecture et l'écriture.
        existing = ProcessedRequest.objects.get(idempotency_key=key)
        if existing.action != action:
            raise CommerceError("Cette clé d'idempotence appartient à une autre action.", 409)
        if existing.result.get("_processing"):
            raise CommerceError("Cette opération est déjà en cours.", 409)
        return existing.result
    try:
        result = callback()
    except Exception:
        # Un échec ne doit pas bloquer définitivement une nouvelle tentative sûre.
        reservation.delete()
        raise
    reservation.result = result
    reservation.save(update_fields=["result"])
    return result


def _search(data):
    _required(data, "query")
    products = WooCommerceClient().search_products(str(data["query"]).strip())

    # n8n affiche au maximum dix résultats. Lorsque l'identifiant WhatsApp est
    # fourni, enregistrer ici exactement cette liste évite de demander au LLM
    # de recopier des identifiants et rend un choix comme « 1 » déterministe.
    if data.get("user_id") and products:
        products = products[:10]
        _save_selection_list(
            {
                "user_id": data["user_id"],
                "session_key": data.get("session_key") or "current",
                "products": [
                    {
                        "position": index,
                        "product_id": product.get("id"),
                        "product_name": product.get("nom") or "Produit",
                        "price": product.get("prix"),
                    }
                    for index, product in enumerate(products, start=1)
                ],
            }
        )
    return {"products": products}


def _get_product(data):
    _required(data, "product_id", "platform")
    return _client(data["platform"]).get_product(data["product_id"])


def _cart_add(data):
    _required(data, "user_id", "product_id", "product_name", "quantity", "price")
    try:
        quantity = int(data["quantity"])
    except (TypeError, ValueError) as exc:
        raise CommerceError("La quantité doit être un entier positif.", 400) from exc
    if quantity <= 0:
        raise CommerceError("La quantité doit être un entier positif.", 400)
    price = _decimal(data["price"], "price")
    _platform(data.get("platform", "woocommerce"))
    row, created = Cart.objects.get_or_create(
        user_id=str(data["user_id"]),
        product_id=str(data["product_id"]),
        defaults={
            "product_name": str(data["product_name"]),
            "quantity": quantity,
            "price": price,
            "platform": "woocommerce",
            "idempotency_key": data.get("idempotency_key"),
        },
    )
    if not created:
        row.quantity += quantity
        row.product_name = str(data["product_name"])
        row.price = price
        row.save()
    state = _state(data["user_id"])
    if state.state == "browsing":
        _move_state(state, "selecting")
    if state.state == "selecting":
        _move_state(state, "cart_review")
    return _cart_payload(data["user_id"])


def _cart_remove(data):
    _required(data, "user_id", "product_id")
    Cart.objects.filter(user_id=str(data["user_id"]), product_id=str(data["product_id"])).delete()
    return _cart_payload(data["user_id"])


def _cart_update_quantity(data):
    _required(data, "user_id", "product_id", "quantity")
    try:
        quantity = int(data["quantity"])
    except (TypeError, ValueError) as exc:
        raise CommerceError("La quantité doit être un entier.", 400) from exc
    query = Cart.objects.filter(user_id=str(data["user_id"]), product_id=str(data["product_id"]))
    if not query.exists():
        raise CommerceError("Ce produit n'est pas dans le panier.", 404)
    if quantity <= 0:
        query.delete()
    else:
        query.update(quantity=quantity)
    return _cart_payload(data["user_id"])


def _cart_view(data):
    _required(data, "user_id")
    return _cart_payload(data["user_id"])


def _cart_clear(data):
    _required(data, "user_id")
    Cart.objects.filter(user_id=str(data["user_id"])).delete()
    state = _state(data["user_id"])
    state.previous_state, state.state = state.state, "browsing"
    state.pending_product_id = None
    state.save()
    return _cart_payload(data["user_id"])


def _save_selection_list(data):
    _required(data, "user_id", "products")
    if not isinstance(data["products"], list) or not data["products"]:
        raise CommerceError("products doit être une liste non vide.", 400)
    user_id = str(data["user_id"])
    session_key = str(data.get("session_key") or "current")
    with transaction.atomic():
        ProductSelection.objects.filter(user_id=user_id).delete()
        rows = []
        for item in data["products"]:
            if not isinstance(item, dict):
                raise CommerceError("Chaque produit sélectionné doit être un objet.", 400)
            _required(item, "position", "product_id", "product_name")
            rows.append(
                ProductSelection(
                    user_id=user_id,
                    session_key=session_key,
                    position=int(item["position"]),
                    product_id=str(item["product_id"]),
                    product_name=str(item["product_name"]),
                    price=_decimal(item["price"], "price") if item.get("price") not in (None, "") else None,
                )
            )
        ProductSelection.objects.bulk_create(rows)
    state = _state(user_id)
    if state.state == "browsing":
        _move_state(state, "selecting")
    return {"saved": len(rows), "session_key": session_key}


def _get_product_by_position(data):
    _required(data, "user_id", "position")
    try:
        position = int(data["position"])
    except (TypeError, ValueError) as exc:
        raise CommerceError("La position doit être un entier.", 400) from exc
    row = ProductSelection.objects.filter(user_id=str(data["user_id"]), position=position).order_by("-created_at").first()
    if not row:
        raise CommerceError("Aucun produit ne correspond à cette position.", 404)
    state = _state(data["user_id"])
    state.pending_product_id = row.product_id
    state.save()
    return {
        "position": row.position,
        "product_id": row.product_id,
        "product_name": row.product_name,
        "price": str(row.price) if row.price is not None else None,
        "platform": "woocommerce",
    }


def _get_state(data):
    _required(data, "user_id")
    return _state_payload(_state(data["user_id"]))


def _set_state(data):
    _required(data, "user_id", "state")
    pending = {
        field: data[field]
        for field in ("pending_product_id", "pending_order_id", "pending_amount")
        if field in data
    }
    if "pending_amount" in pending and pending["pending_amount"] not in (None, ""):
        pending["pending_amount"] = _decimal(pending["pending_amount"], "pending_amount")
    return _state_payload(_move_state(_state(data["user_id"]), str(data["state"]), **pending))


def _revert_state(data):
    _required(data, "user_id")
    state = _state(data["user_id"])
    previous = state.previous_state if state.previous_state in ALLOWED_STATES else "browsing"
    state.state, state.previous_state = previous, "browsing"
    state.save()
    return _state_payload(state)


def _create_order(data):
    _required(data, "user_id")

    def execute():
        state = _state(data["user_id"])
        if state.state != "confirming":
            raise CommerceError("La commande exige une confirmation explicite préalable.", 409)
        platform = _platform(data.get("platform", "woocommerce"))
        source_cart = data.get("cart")
        if source_cart is None:
            source_cart = [
                {"product_id": row.product_id, "quantity": row.quantity, "platform": row.platform}
                for row in Cart.objects.filter(user_id=str(data["user_id"]))
            ]
        _, cart = _validate_cart(source_cart, platform)
        result = WooCommerceClient().create_order(data["user_id"], cart)
        UserOrder.objects.update_or_create(
            order_id=result["order_id"],
            defaults={"user_id": str(data["user_id"]), "platform": "woocommerce"},
        )
        _move_state(
            state,
            "ordering",
            pending_order_id=result["order_id"],
            pending_amount=_decimal(result["montant_total"], "montant_total"),
        )
        return result

    return _idempotent("create_order", data, execute)


def _generate_payment(data):
    _required(data, "user_id", "order_id", "amount")

    def execute():
        state = _state(data["user_id"])
        if state.state != "ordering" or str(state.pending_order_id) != str(data["order_id"]):
            raise CommerceError("Le paiement exige une commande WooCommerce créée et vérifiée.", 409)
        _owned_order(data)
        result = PayTechClient().generate_payment(data["order_id"], data["amount"])
        _move_state(state, "payment_pending")
        return result

    return _idempotent("generate_payment", data, execute)


def _get_order_status(data):
    woo = _owned_order(data)
    return woo.get_order_status(data["order_id"])


def _cancel_order(data):
    _required(data, "order_id", "user_id")
    reason = str(data.get("reason", "")).strip()
    if len(reason) > 500:
        raise CommerceError("Le motif d'annulation ne doit pas dépasser 500 caractères.", 400)
    woo = _owned_order(data)
    return woo.cancel_order(data["order_id"], reason, data["user_id"])


def _request_refund(data):
    _required(data, "order_id", "user_id", "amount")
    amount = _decimal(data["amount"], "amount", positive=True)
    reason = str(data.get("reason", "")).strip()
    if len(reason) > 500:
        raise CommerceError("Le motif du remboursement ne doit pas dépasser 500 caractères.", 400)
    woo = _owned_order(data)
    return woo.request_refund(data["order_id"], amount, reason)


def _update_order(data):
    _required(data, "order_id", "user_id", "line_items")
    if not isinstance(data["line_items"], list) or not data["line_items"]:
        raise CommerceError("line_items doit être une liste non vide.", 400)
    cleaned = []
    for index, item in enumerate(data["line_items"]):
        if not isinstance(item, dict) or not item.get("line_item_id"):
            raise CommerceError(f"La ligne {index + 1} doit contenir line_item_id.", 400)
        try:
            quantity, line_id = int(item.get("quantity")), int(item["line_item_id"])
        except (TypeError, ValueError) as exc:
            raise CommerceError(f"Ligne ou quantité invalide à la position {index + 1}.", 400) from exc
        if quantity < 0:
            raise CommerceError("Une quantité ne peut pas être négative.", 400)
        cleaned.append({"id": line_id, "quantity": quantity})
    woo = _owned_order(data)
    return woo.update_order(data["order_id"], cleaned)


def _get_tracking(data):
    woo = _owned_order(data)
    return woo.get_tracking(data["order_id"])


def _validate_coupon(data):
    _required(data, "code")
    code = str(data["code"]).strip()
    if len(code) > 100:
        raise CommerceError("Le code promo est trop long.", 400)
    return _woo_only(data).validate_coupon(code)


def _check_variant_stock(data):
    _required(data, "product_id", "variant_id")
    return _woo_only(data).check_variant_stock(data["product_id"], data["variant_id"])


def _transfer_to_human(data):
    _required(data, "user_id")
    reason = str(data.get("reason", "")).strip()
    transfer = HumanTransfer.objects.create(user_id=str(data["user_id"]), reason=reason)
    state = _state(data["user_id"])
    _move_state(state, "human_takeover")
    return {"transfer_id": str(transfer.id), "status": transfer.status, "human_takeover": True}


def _check_human_status(data):
    _required(data, "user_id")
    state = _state(data["user_id"])
    transfer = HumanTransfer.objects.filter(user_id=str(data["user_id"]), status="pending").order_by("-created_at").first()
    return {
        "human_takeover": state.state == "human_takeover",
        "status": transfer.status if transfer else None,
    }


def _get_policy(data):
    _required(data, "policy_type")
    policy_type = str(data["policy_type"]).strip().casefold()
    if policy_type not in {"delivery", "returns", "refund"}:
        raise CommerceError("policy_type doit valoir delivery, returns ou refund.", 400)
    policy = ShopPolicy.objects.filter(policy_type=policy_type).first()
    if not policy:
        raise CommerceError("Cette politique n'est pas encore configurée.", 404)
    return {"policy_type": policy.policy_type, "content": policy.content}


def _money(value):
    """Formate un montant XOF sans décimales inutiles."""
    amount = _decimal(value or 0, "price")
    return f"{int(amount):,}".replace(",", " ")


def _format_cart(cart):
    if not cart["items"]:
        return "Votre panier est vide."
    lines = [
        f"- {item['quantity']} × {item['product_name']} : {_money(item['line_total'])} FCFA"
        for item in cart["items"]
    ]
    return "Votre panier :\n" + "\n".join(lines) + f"\nTotal : {_money(cart['total'])} FCFA"


def _select_product_for_conversation(user_id, product):
    state = _state(user_id)
    state.pending_product_id = str(product.get("id") or product.get("product_id"))
    if state.state == "browsing":
        state.previous_state, state.state = state.state, "selecting"
    state.save()


def _conversation_turn(data):
    """Résout les étapes critiques sans laisser le LLM modifier l'état métier."""
    _required(data, "user_id", "message")
    user_id = str(data["user_id"])
    message = " ".join(str(data["message"]).strip().split())
    lowered = message.casefold()
    state = _state(user_id)

    if state.state == "human_takeover":
        return {
            "handled": True,
            "direct_response": "Vous êtes en contact avec notre équipe. Un agent va vous répondre très bientôt.",
            "state": _state_payload(state),
        }
    if message in {"[MESSAGE_VIDE]", ""}:
        return {"handled": True, "direct_response": "Pouvez-vous préciser votre demande ?"}
    if message == "[MEDIA_SANS_TEXTE]":
        return {
            "handled": True,
            "direct_response": "Ce service traite uniquement le texte pour le moment. Décrivez-moi votre demande par écrit.",
        }

    checkout = bool(re.search(r"\b(pass(?:e|er)?|valid(?:e|er)?|finalis(?:e|er)?|command(?:e|er))\b.{0,20}\bcommande\b", lowered))
    affirmative = bool(re.fullmatch(r"(?:oui|ok|d'accord|je confirme|confirme|vas-y|allez)", lowered))
    numeric = re.fullmatch(r"(?:je\s+(?:prends?|choisis)\s+(?:le\s+)?)?(\d+)", lowered)

    if checkout:
        cart = _cart_payload(user_id)
        if not cart["items"]:
            return {
                "handled": True,
                "direct_response": "Votre panier est vide. Choisissez d'abord un produit à ajouter.",
                "cart": cart,
            }
        state.previous_state, state.state = state.state, "confirming"
        state.save()
        return {
            "handled": True,
            "direct_response": _format_cart(cart) + "\nConfirmez-vous la création de cette commande ? Répondez oui ou non.",
            "cart": cart,
            "state": _state_payload(state),
        }

    if affirmative and state.state == "confirming":
        key = str(data.get("idempotency_key") or f"{user_id}:{data.get('timestamp', 'turn')}:create_order")
        order = _create_order(
            {"user_id": user_id, "platform": "woocommerce", "idempotency_key": key}
        )
        return {
            "handled": True,
            "direct_response": (
                f"Commande confirmée. Référence : {order['order_id']}. "
                f"Total : {_money(order['montant_total'])} {order.get('devise', 'XOF')}."
            ),
            "order": order,
        }

    if affirmative and state.state == "selecting" and state.pending_product_id:
        product = WooCommerceClient().get_product(state.pending_product_id)
        price = product.get("prix")
        if price in (None, ""):
            raise CommerceError("Le prix de ce produit est indisponible.", 409)
        cart = _cart_add(
            {
                "user_id": user_id,
                "product_id": product["id"],
                "product_name": product.get("nom") or "Produit",
                "quantity": 1,
                "price": price,
                "platform": "woocommerce",
            }
        )
        return {
            "handled": True,
            "direct_response": f"{product.get('nom')} a été ajouté au panier.\n" + _format_cart(cart) + "\nSouhaitez-vous passer la commande ?",
            "selected_product": product,
            "cart": cart,
        }

    if numeric:
        selected = _get_product_by_position({"user_id": user_id, "position": int(numeric.group(1))})
        return {
            "handled": True,
            "direct_response": (
                f"Vous avez sélectionné {selected['product_name']} à {_money(selected['price'])} FCFA. "
                "Souhaitez-vous l'ajouter au panier ?"
            ),
            "selected_product": selected,
            "state": _state_payload(_state(user_id)),
        }

    generic_catalogue = bool(
        re.search(r"catalogue|produits? disponibles?|montre(?:z)?[- ]?moi.{0,20}produits?|vous avez quoi", lowered)
    )
    greeting = bool(re.fullmatch(r"(?:bonjour|bonsoir|salut|hello|coucou)(?:\s+(?:monsieur|madame))?[!. ]*", lowered))
    if greeting:
        return {
            "handled": True,
            "direct_response": "Bonjour ! Que recherchez-vous aujourd'hui ? Vous pouvez aussi demander à voir le catalogue.",
        }

    query = "*" if generic_catalogue else message
    search = _search(
        {
            "query": query,
            "user_id": user_id,
            "session_key": data.get("session_key") or "current",
        }
    )
    products = search["products"]
    if not products:
        if generic_catalogue:
            return {"handled": True, "direct_response": "Aucun produit n'est disponible actuellement.", "products": []}
        return {"handled": False, "direct_response": None, "products": []}
    if len(products) == 1:
        product = products[0]
        _select_product_for_conversation(user_id, product)
        return {
            "handled": True,
            "direct_response": (
                f"{product.get('nom')} est disponible à {_money(product.get('prix'))} FCFA"
                + (f" ({product.get('stock')} en stock)." if product.get("stock") is not None else ".")
                + " Souhaitez-vous l'ajouter au panier ?"
            ),
            "selected_product": product,
            "products": products,
        }
    lines = [
        f"{index}. {product.get('nom')} - {_money(product.get('prix'))} FCFA"
        for index, product in enumerate(products, start=1)
    ]
    return {
        "handled": True,
        "direct_response": "Voici les produits disponibles :\n" + "\n".join(lines) + "\nRépondez avec le numéro du produit choisi.",
        "products": products,
    }


HANDLERS = {
    "search_products": _search,
    "get_product": _get_product,
    "create_order": _create_order,
    "generate_payment": _generate_payment,
    "get_order_status": _get_order_status,
    "cancel_order": _cancel_order,
    "request_refund": _request_refund,
    "update_order": _update_order,
    "modify_order": _update_order,
    "get_tracking": _get_tracking,
    "validate_coupon": _validate_coupon,
    "check_variant_stock": _check_variant_stock,
    "cart_add": _cart_add,
    "cart_remove": _cart_remove,
    "cart_update_quantity": _cart_update_quantity,
    "cart_view": _cart_view,
    "cart_clear": _cart_clear,
    "save_selection_list": _save_selection_list,
    "get_product_by_position": _get_product_by_position,
    "get_state": _get_state,
    "set_state": _set_state,
    "revert_state": _revert_state,
    "transfer_to_human": _transfer_to_human,
    "check_human_status": _check_human_status,
    "get_policy": _get_policy,
    "conversation_turn": _conversation_turn,
}


def _security_error(request):
    expected = str(getattr(settings, "N8N_API_TOKEN", "") or "")
    if expected and not hmac.compare_digest(request.headers.get("X-API-Token", ""), expected):
        return Response({"success": False, "error": "Unauthorized"}, status=401)

    limit = int(getattr(settings, "COMMERCE_RATE_LIMIT", 60))
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    ip = forwarded or request.META.get("REMOTE_ADDR", "unknown")
    key = f"commerce-rate:{ip}"
    if cache.add(key, 1, timeout=60):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=60)
            count = 1
    if count > limit:
        return Response({"success": False, "error": "Too Many Requests"}, status=429)
    return None


@api_view(["POST"])
@permission_classes([AllowAny])
def commerce(request):
    """Route toutes les opérations e-commerce via le champ ``action``."""
    security_error = _security_error(request)
    if security_error:
        return security_error
    try:
        if not isinstance(request.data, dict):
            raise CommerceError("Le corps de la requête doit être un objet JSON.", 400)
        action = request.data.get("action")
        data = request.data.get("data", {})
        if action not in ALLOWED_ACTIONS:
            raise CommerceError(
                f"Action invalide. Actions acceptées : {', '.join(sorted(ALLOWED_ACTIONS))}.",
                400,
            )
        if isinstance(data, str):
            raw_data = data.strip()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                if action == "search_products" and raw_data:
                    data = {"query": raw_data}
                else:
                    raise CommerceError("Le champ 'data' doit être un objet JSON valide.", 400)
        if not isinstance(data, dict):
            raise CommerceError("Le champ 'data' doit être un objet JSON.", 400)
        return Response({"success": True, "data": HANDLERS[action](data)}, status=200)
    except CommerceError as exc:
        return Response({"success": False, "error": exc.message}, status=exc.status_code)
    except APIException:
        raise
    except Exception:
        logger.exception("Erreur inattendue dans l'endpoint commerce")
        return Response(
            {"success": False, "error": "Une erreur interne inattendue est survenue."},
            status=500,
        )
