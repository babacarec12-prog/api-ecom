"""Endpoint unique utilisé par l'agent IA et le workflow n8n."""

import hmac
import json
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .exceptions import CommerceError
from .database_client import DatabaseCatalogClient
from .kimi_client import KimiClient
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


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Sonde légère utilisée par Render, sans dépendance à WooCommerce."""
    return Response({"status": "ok", "service": "ai-commerce-api"}, status=200)

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
    "execute_intent",
    "conversation_turn",
    "message_turn",
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
    aliases = {
        "woo": "woocommerce",
        "woocommerce": "woocommerce",
        "db": "database",
        "database": "database",
    }
    if normalized not in aliases:
        raise CommerceError(
            "Cette API accepte uniquement les plateformes 'database' ou 'woocommerce'.",
            400,
        )
    return aliases[normalized]


def _catalog_platform():
    provider = str(
        getattr(settings, "COMMERCE_CATALOG_PROVIDER", "database") or "database"
    ).strip().casefold()
    return _platform(provider)


def _client(platform):
    platform = _platform(platform)
    return DatabaseCatalogClient() if platform == "database" else WooCommerceClient()


def _woo_only(data):
    if data.get("platform"):
        _platform(data["platform"])
    return WooCommerceClient()


def _validate_cart(cart, default_platform=None):
    if not isinstance(cart, list) or not cart:
        raise CommerceError("Le panier doit être une liste non vide.", 400)
    cleaned = []
    selected_platform = None
    for index, item in enumerate(cart):
        if not isinstance(item, dict) or not item.get("product_id"):
            raise CommerceError(f"L'article {index + 1} doit contenir product_id.", 400)
        platform = _platform(item.get("platform") or default_platform)
        if selected_platform and platform != selected_platform:
            raise CommerceError("Un panier ne peut pas mélanger plusieurs plateformes.", 400)
        selected_platform = platform
        try:
            quantity = int(item.get("quantity", 1))
        except (TypeError, ValueError) as exc:
            raise CommerceError(f"Quantité invalide pour l'article {index + 1}.", 400) from exc
        if quantity <= 0:
            raise CommerceError(f"La quantité de l'article {index + 1} doit être positive.", 400)
        cleaned.append({**item, "quantity": quantity, "platform": platform})
    return selected_platform, cleaned


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
        "pending_action": state.pending_action,
        "has_pending_action": bool(state.pending_action),
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
    products = _client(data.get("platform") or _catalog_platform()).search_products(
        str(data["query"]).strip()
    )

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
    platform = _platform(data.get("platform") or _catalog_platform())
    row, created = Cart.objects.get_or_create(
        user_id=str(data["user_id"]),
        product_id=str(data["product_id"]),
        defaults={
            "product_name": str(data["product_name"]),
            "quantity": quantity,
            "price": price,
            "platform": platform,
            "idempotency_key": data.get("idempotency_key"),
        },
    )
    if not created:
        row.quantity += quantity
        row.product_name = str(data["product_name"])
        row.price = price
        row.platform = platform
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
        "platform": _catalog_platform(),
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
        platform = _platform(data.get("platform") or _catalog_platform())
        source_cart = data.get("cart")
        if source_cart is None:
            source_cart = [
                {"product_id": row.product_id, "quantity": row.quantity, "platform": row.platform}
                for row in Cart.objects.filter(user_id=str(data["user_id"]))
            ]
        _, cart = _validate_cart(source_cart, platform)
        result = _client(platform).create_order(data["user_id"], cart)
        UserOrder.objects.update_or_create(
            order_id=result["order_id"],
            defaults={
                "user_id": str(data["user_id"]),
                "platform": platform,
                "amount_total": _decimal(result["montant_total"], "montant_total"),
                "currency": result.get("devise", "XOF"),
                "status": result.get("statut", "pending"),
                "items": result.get("items", []),
            },
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
    row = UserOrder.objects.filter(
        order_id=str(data.get("order_id")), user_id=str(data.get("user_id"))
    ).first()
    if row and row.platform == "database":
        return {
            "order_id": row.order_id,
            "statut": row.status,
            "montant_total": str(row.amount_total or 0),
            "devise": row.currency,
            "items": row.items,
            "plateforme": "database",
        }
    woo = _owned_order(data)
    return woo.get_order_status(data["order_id"])


def _cancel_order_unprotected(data):
    _required(data, "order_id", "user_id")
    reason = str(data.get("reason", "")).strip()
    if len(reason) > 500:
        raise CommerceError("Le motif d'annulation ne doit pas dépasser 500 caractères.", 400)
    woo = _owned_order(data)
    return woo.cancel_order(data["order_id"], reason, data["user_id"])


def _request_refund_unprotected(data):
    _required(data, "order_id", "user_id", "amount")
    amount = _decimal(data["amount"], "amount", positive=True)
    reason = str(data.get("reason", "")).strip()
    if len(reason) > 500:
        raise CommerceError("Le motif du remboursement ne doit pas dépasser 500 caractères.", 400)
    woo = _owned_order(data)
    return woo.request_refund(data["order_id"], amount, reason)


def _update_order_unprotected(data):
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


def _optional_idempotent(action, data, callback):
    if data.get("idempotency_key"):
        return _idempotent(action, data, callback)
    return callback()


def _cancel_order(data):
    return _optional_idempotent(
        "cancel_order", data, lambda: _cancel_order_unprotected(data)
    )


def _request_refund(data):
    return _optional_idempotent(
        "request_refund", data, lambda: _request_refund_unprotected(data)
    )


def _update_order(data):
    return _optional_idempotent(
        "update_order", data, lambda: _update_order_unprotected(data)
    )


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
        product = _client(_catalog_platform()).get_product(state.pending_product_id)
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
                "platform": _catalog_platform(),
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


KIMI_INTENTIONS = {
    "search_products", "get_product", "cart_add", "cart_view", "cart_remove",
    "cart_clear", "cart_update_quantity", "create_order", "generate_payment",
    "get_order_status", "cancel_order", "request_refund", "update_order",
    "get_tracking", "validate_coupon", "check_variant_stock", "get_policy",
    "transfer_to_human", "other",
}


def _intent_clarification(intention, message):
    return {
        "executed": False,
        "intention": intention,
        "requires_clarification": True,
        "clarification": message,
    }


def _dispatch_intent(data):
    """Execute une intention classee par Kimi, sans analyser le message client."""
    _required(data, "user_id", "intention")
    user_id = str(data["user_id"])
    intention = str(data["intention"]).strip()
    params = data.get("params") or {}
    if intention not in KIMI_INTENTIONS:
        raise CommerceError("Intention Kimi non autorisee.", 400)
    if not isinstance(params, dict):
        raise CommerceError("Les parametres Kimi doivent etre un objet JSON.", 400)

    state = _state(user_id)
    if state.state == "human_takeover" and intention != "transfer_to_human":
        return {
            "executed": False,
            "intention": intention,
            "human_takeover": True,
            "message": "Un conseiller humain prend deja en charge ce client.",
        }
    if intention == "other":
        return {
            "executed": False,
            "intention": intention,
            "reformulation": data.get("reformulation", ""),
        }

    payload = {key: value for key, value in params.items() if value not in (None, "")}
    payload.update({"user_id": user_id, "platform": _catalog_platform()})

    if intention == "search_products":
        payload["query"] = str(payload.get("query") or "*").strip()
        payload["session_key"] = str(data.get("session_key") or "current")
        result = _search(payload)
    elif intention == "get_product":
        if payload.get("position") is not None:
            result = {"selected_product": _get_product_by_position(payload)}
        elif payload.get("product_id"):
            result = _get_product(payload)
        else:
            return _intent_clarification(intention, "Quel produit souhaitez-vous consulter ?")
    elif intention == "cart_add":
        product_id = payload.get("product_id") or state.pending_product_id
        if not product_id and payload.get("position") is not None:
            product_id = _get_product_by_position(payload)["product_id"]
        if not product_id:
            return _intent_clarification(intention, "Quel produit souhaitez-vous ajouter au panier ?")
        product = _client(_catalog_platform()).get_product(product_id)
        if product.get("prix") in (None, ""):
            raise CommerceError("Le prix de ce produit est indisponible.", 409)
        result = _cart_add({
            "user_id": user_id,
            "product_id": product["id"],
            "product_name": product.get("nom") or "Produit",
            "quantity": payload.get("quantity", 1),
            "price": product["prix"],
            "platform": _catalog_platform(),
        })
    elif intention in {"cart_remove", "cart_update_quantity"}:
        product_id = payload.get("product_id") or state.pending_product_id
        if not product_id and payload.get("position") is not None:
            product_id = _get_product_by_position(payload)["product_id"]
        if not product_id:
            return _intent_clarification(intention, "Quel produit du panier souhaitez-vous modifier ?")
        payload["product_id"] = product_id
        if intention == "cart_update_quantity" and payload.get("quantity") is None:
            return _intent_clarification(intention, "Quelle quantite souhaitez-vous ?")
        result = _cart_remove(payload) if intention == "cart_remove" else _cart_update_quantity(payload)
    elif intention == "cart_view":
        result = _cart_view(payload)
    elif intention == "cart_clear":
        result = _cart_clear(payload)
    elif intention == "create_order":
        cart = _cart_payload(user_id)
        if not cart["items"]:
            return _intent_clarification(intention, "Votre panier est vide. Ajoutez d'abord un produit.")
        if state.state != "confirming":
            state.previous_state, state.state = state.state, "confirming"
            state.save()
            return {
                "executed": False,
                "intention": intention,
                "requires_confirmation": True,
                "cart": cart,
                "message": "Demander une confirmation explicite avant de creer la commande.",
            }
        payload["idempotency_key"] = str(data.get("idempotency_key") or f"{user_id}:{data.get('timestamp', 'intent')}:create_order")
        result = _create_order(payload)
    elif intention == "generate_payment":
        payload["order_id"] = payload.get("order_id") or state.pending_order_id
        payload["amount"] = payload.get("amount") or state.pending_amount
        if not payload.get("order_id") or payload.get("amount") in (None, ""):
            return _intent_clarification(intention, "Quelle commande souhaitez-vous payer ?")
        payload["idempotency_key"] = str(data.get("idempotency_key") or f"{user_id}:{data.get('timestamp', 'intent')}:generate_payment")
        result = _generate_payment(payload)
    elif intention in {"get_order_status", "cancel_order", "get_tracking"}:
        payload["order_id"] = payload.get("order_id") or state.pending_order_id
        if not payload.get("order_id"):
            return _intent_clarification(intention, "Quel est le numero de la commande concernee ?")
        if intention == "cancel_order":
            payload["idempotency_key"] = _intent_key(data, intention)
        handler = {
            "get_order_status": _get_order_status,
            "cancel_order": _cancel_order,
            "get_tracking": _get_tracking,
        }[intention]
        result = handler(payload)
    elif intention == "request_refund":
        payload["order_id"] = payload.get("order_id") or state.pending_order_id
        payload["amount"] = payload.get("amount") or state.pending_amount
        if not payload.get("order_id") or payload.get("amount") in (None, ""):
            return _intent_clarification(intention, "Precisez la commande et le montant du remboursement.")
        payload["idempotency_key"] = _intent_key(data, intention)
        result = _request_refund(payload)
    elif intention == "update_order":
        if not payload.get("order_id") or not payload.get("line_items"):
            return _intent_clarification(intention, "Precisez la commande et les articles a modifier.")
        payload["idempotency_key"] = _intent_key(data, intention)
        result = _update_order(payload)
    elif intention == "validate_coupon":
        if not payload.get("code"):
            return _intent_clarification(intention, "Quel code promotionnel souhaitez-vous verifier ?")
        result = _validate_coupon(payload)
    elif intention == "check_variant_stock":
        if not payload.get("product_id") or not payload.get("variant_id"):
            return _intent_clarification(intention, "Quelle variante souhaitez-vous verifier ?")
        result = _check_variant_stock(payload)
    elif intention == "get_policy":
        if not payload.get("policy_type"):
            return _intent_clarification(intention, "Parlez-vous de livraison, de retour ou de remboursement ?")
        result = _get_policy(payload)
    elif intention == "transfer_to_human":
        result = _transfer_to_human(payload)
    else:
        raise CommerceError("Cette intention n'est pas executable.", 400)

    return {"executed": True, "intention": intention, "result": result}


CONFIRMABLE_INTENTIONS = {
    "cart_clear",
    "create_order",
    "cancel_order",
    "request_refund",
    "update_order",
}

INTENTION_ALIASES = {
    "confirm": "confirm_action",
    "confirmation": "confirm_action",
    "yes": "confirm_action",
    "deny": "cancel_pending_action",
    "no": "cancel_pending_action",
    "cancel_pending": "cancel_pending_action",
}

POLICY_ALIASES = {
    "delivery": "delivery",
    "livraison": "delivery",
    "returns": "returns",
    "return": "returns",
    "retour": "returns",
    "refund": "refund",
    "remboursement": "refund",
}


def _intent_key(data, intention):
    supplied = str(data.get("idempotency_key") or "").strip()
    if supplied:
        return supplied
    timestamp = str(data.get("timestamp") or "intent")
    return f"{data['user_id']}:{timestamp}:{intention}"


def _latest_order_id(user_id, state):
    if state.pending_order_id:
        return str(state.pending_order_id)
    row = UserOrder.objects.filter(user_id=str(user_id)).order_by("-created_at").first()
    return row.order_id if row else None


def _normalise_intent_params(intention, params, user_id, state):
    payload = {
        str(key): value
        for key, value in params.items()
        if value not in (None, "")
    }
    if "position" in payload:
        try:
            payload["position"] = int(payload["position"])
        except (TypeError, ValueError) as exc:
            raise CommerceError("La position doit etre un entier.", 400) from exc
    if "quantity" in payload:
        try:
            payload["quantity"] = int(payload["quantity"])
        except (TypeError, ValueError) as exc:
            raise CommerceError("La quantite doit etre un entier.", 400) from exc
    if payload.get("policy_type"):
        policy = POLICY_ALIASES.get(str(payload["policy_type"]).strip().casefold())
        if not policy:
            raise CommerceError("policy_type doit valoir delivery, returns ou refund.", 400)
        payload["policy_type"] = policy
    if intention in {
        "generate_payment", "get_order_status", "cancel_order", "request_refund",
        "update_order", "get_tracking",
    } and not payload.get("order_id"):
        payload["order_id"] = _latest_order_id(user_id, state)
    return payload


def _pending_summary(intention, payload, user_id):
    if intention == "create_order":
        return {"cart": _cart_payload(user_id)}
    if intention == "cart_clear":
        return {"cart": _cart_payload(user_id)}
    if intention == "cancel_order":
        return {"order_id": payload.get("order_id"), "reason": payload.get("reason", "")}
    if intention == "request_refund":
        return {
            "order_id": payload.get("order_id"),
            "amount": str(payload.get("amount")),
            "currency": "XOF",
            "reason": payload.get("reason", ""),
        }
    return {"order_id": payload.get("order_id"), "line_items": payload.get("line_items", [])}


def _stage_intent(data, intention, payload, state):
    if intention == "create_order" and not _cart_payload(data["user_id"])["items"]:
        return _intent_clarification(intention, "Votre panier est vide. Ajoutez d'abord un produit.")
    if intention in {"cancel_order", "request_refund", "update_order"} and not payload.get("order_id"):
        return _intent_clarification(intention, "Quel est le numero de la commande concernee ?")
    if intention == "request_refund" and payload.get("amount") in (None, ""):
        return _intent_clarification(intention, "Quel montant souhaitez-vous rembourser ?")
    if intention == "update_order" and not payload.get("line_items"):
        return _intent_clarification(intention, "Quels articles de la commande souhaitez-vous modifier ?")
    if intention in {"cancel_order", "request_refund"} and len(str(payload.get("reason", "")).strip()) > 500:
        raise CommerceError("Le motif ne doit pas depasser 500 caracteres.", 400)
    if intention == "request_refund":
        payload["amount"] = str(_decimal(payload["amount"], "amount", positive=True))
    if intention == "update_order":
        if not isinstance(payload["line_items"], list):
            raise CommerceError("line_items doit etre une liste non vide.", 400)
        for index, item in enumerate(payload["line_items"]):
            if not isinstance(item, dict) or not item.get("line_item_id"):
                raise CommerceError(f"La ligne {index + 1} doit contenir line_item_id.", 400)
            try:
                quantity = int(item.get("quantity"))
                int(item["line_item_id"])
            except (TypeError, ValueError) as exc:
                raise CommerceError(f"Ligne ou quantite invalide a la position {index + 1}.", 400) from exc
            if quantity < 0:
                raise CommerceError("Une quantite ne peut pas etre negative.", 400)

    stored = {
        "params": payload,
        "idempotency_key": _intent_key(data, intention),
        "timestamp": data.get("timestamp"),
        "state_before_confirmation": state.state,
    }
    if intention == "create_order" and state.state != "confirming":
        state.previous_state, state.state = state.state, "confirming"
    state.pending_action = intention
    state.pending_payload = json.loads(json.dumps(stored, default=str))
    state.save()
    return {
        "executed": False,
        "intention": intention,
        "requires_confirmation": True,
        "confirmation": _pending_summary(intention, payload, data["user_id"]),
        "message": "Une confirmation explicite est requise avant cette action.",
        "state": _state_payload(state),
    }


def _cancel_pending_intent(user_id, state):
    cancelled = state.pending_action
    before = (state.pending_payload or {}).get("state_before_confirmation")
    if cancelled == "create_order" and before in ALLOWED_STATES:
        state.state = before
    state.pending_action = None
    state.pending_payload = {}
    state.save()
    return {
        "executed": False,
        "intention": "cancel_pending_action",
        "cancelled_action": cancelled,
        "state": _state_payload(state),
    }


def _confirm_pending_intent(data, state):
    if not state.pending_action:
        return _intent_clarification("confirm_action", "Aucune action n'attend de confirmation.")
    pending_action = state.pending_action
    stored = dict(state.pending_payload or {})
    confirmed_data = {
        **data,
        "intention": pending_action,
        "params": stored.get("params") or {},
        "idempotency_key": stored.get("idempotency_key") or _intent_key(data, pending_action),
        "timestamp": stored.get("timestamp") or data.get("timestamp"),
        "confidence": 1,
    }
    result = _dispatch_intent(confirmed_data)
    state.refresh_from_db()
    state.pending_action = None
    state.pending_payload = {}
    state.save()
    result["confirmed_action"] = pending_action
    result["state"] = _state_payload(state)
    return result


def _execute_intent(data):
    """Contrat transactionnel entre Kimi et l'API metier."""
    _required(data, "user_id", "intention")
    if not isinstance(data.get("params") or {}, dict):
        raise CommerceError("Les parametres Kimi doivent etre un objet JSON.", 400)

    intention = INTENTION_ALIASES.get(
        str(data["intention"]).strip().casefold(),
        str(data["intention"]).strip().casefold(),
    )
    allowed = KIMI_INTENTIONS | {"confirm_action", "cancel_pending_action"}
    if intention not in allowed:
        raise CommerceError("Intention Kimi non autorisee.", 400)

    if data.get("confidence") not in (None, ""):
        try:
            confidence = float(data["confidence"])
        except (TypeError, ValueError) as exc:
            raise CommerceError("confidence doit etre un nombre entre 0 et 1.", 400) from exc
        if not 0 <= confidence <= 1:
            raise CommerceError("confidence doit etre un nombre entre 0 et 1.", 400)
        if confidence < 0.6:
            result = _intent_clarification(intention, "Pouvez-vous preciser votre demande ?")
            result["state"] = _state_payload(_state(data["user_id"]))
            return result

    user_id = str(data["user_id"])
    state = _state(user_id)
    if state.state == "human_takeover" and intention != "transfer_to_human":
        return {
            "executed": False,
            "intention": intention,
            "human_takeover": True,
            "message": "Un conseiller humain prend deja en charge ce client.",
            "state": _state_payload(state),
        }
    if intention == "cancel_pending_action":
        return _cancel_pending_intent(user_id, state)
    if intention == "confirm_action":
        return _confirm_pending_intent({**data, "user_id": user_id}, state)

    params = _normalise_intent_params(intention, data.get("params") or {}, user_id, state)
    normalised = {**data, "user_id": user_id, "intention": intention, "params": params}
    if intention in CONFIRMABLE_INTENTIONS:
        return _stage_intent(normalised, intention, params, state)

    result = _dispatch_intent(normalised)
    result.setdefault("requires_confirmation", False)
    result.setdefault("requires_clarification", False)
    result["state"] = _state_payload(_state(user_id))
    return result


def _normalise_message(value):
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9']+", text))


AFFIRMATIVE_MESSAGES = {
    "oui", "waw", "waaw", "yes", "ok", "d'accord", "d accord", "confirme",
    "je confirme", "valide", "vas y",
}
NEGATIVE_MESSAGES = {
    "non", "no", "deedeet", "annule", "laisse tomber", "du tout",
}
BASIC_FRENCH_RESPONSES = {
    "bonjour": "Bonjour ! Comment puis-je vous aider ? 😊",
    "bonsoir": "Bonsoir ! Comment puis-je vous aider ? 😊",
    "salut": "Bonjour ! Comment puis-je vous aider ? 😊",
    "hello": "Bonjour ! Comment puis-je vous aider ? 😊",
    "hi": "Bonjour ! Comment puis-je vous aider ? 😊",
    "coucou": "Bonjour ! Comment puis-je vous aider ? 😊",
    "cc": "Bonjour ! Comment puis-je vous aider ? 😊",
    "salam": "Bonjour ! Comment puis-je vous aider ? 😊",
    "asalaam maalekum": "Bonjour ! Comment puis-je vous aider ? 😊",
    "nanga def": "Bonjour ! Je vais bien, merci. Comment puis-je vous aider ?",
    "na nga def": "Bonjour ! Je vais bien, merci. Comment puis-je vous aider ?",
    "merci": "Avec plaisir ! 😊",
    "jerejef": "Avec plaisir ! 😊",
}


def _fallback_analysis(message, state):
    """Secours local rapide quand Kimi est indisponible."""
    normalized = _normalise_message(message)
    params = {}
    intention = "other"
    commerce_words = re.search(
        r"\b(catalogue|catalog|produit|produits|article|articles|montre|affiche|"
        r"bissap|power bank|batterie|telephone|téléphone|chargeur|ordinateur|"
        r"robe|chaussure|sac)\b",
        normalized,
    )
    product_question = re.match(
        r"^(?:amo|am nga|y a t il|avez vous|vous avez|dama beug|dama beg|je cherche|je veux|je voudrais)\b",
        normalized,
    )
    if normalized.isdigit() and state.state == "selecting":
        intention, params = "get_product", {"position": int(normalized)}
    elif re.search(r"\b(voir|affiche|montre|consulte)\b.{0,20}\b(panier|cart)\b", normalized) or normalized in {"panier", "mon panier"}:
        intention = "cart_view"
    elif commerce_words or product_question:
        intention = "search_products"
        stop_words = {
            "a", "affiche", "ai", "am", "amo", "avez", "beug", "beg", "catalog",
            "catalogue", "dama", "de", "des", "du", "en", "est", "il", "je", "la",
            "le", "les", "mes", "moi", "mon", "montre", "nga", "nos", "produit", "produits", "que",
            "quoi", "t", "tes", "tous", "toutes", "un", "une", "voir", "votre", "vos", "voudrais",
            "vous", "veux", "y", "yi", "disponible", "disponibles",
        }
        query_words = [word for word in normalized.split() if word not in stop_words]
        params = {"query": " ".join(query_words) or "*"}
    elif re.search(r"\b(conseiller|humain|agent|service client)\b", normalized):
        intention, params = "transfer_to_human", {"reason": "Demande du client"}
    return {
        "intention": intention,
        "params": params,
        "confidence": 1 if intention != "other" else 0.8,
        "langue_detectee": (
            "wolof_mix"
            if re.search(r"\b(dama|beug|beg|amo|nanga|nga|waw|waaw|jerejef|deedeet)\b", normalized)
            else "français"
        ),
        "reformulation": str(message),
        "reponse_generale": None,
    }


def _validated_message_analysis(raw, message, state):
    raw = raw if isinstance(raw, dict) else {}
    fallback = _fallback_analysis(message, state)
    intention = str(raw.get("intention") or "").strip().casefold()
    if intention not in KIMI_INTENTIONS:
        return fallback
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "intention": intention,
        "params": params,
        "confidence": confidence,
        "langue_detectee": str(raw.get("langue_detectee") or "français"),
        "reformulation": str(raw.get("reformulation") or message),
        "reponse_generale": (
            str(raw.get("reponse_generale") or "").strip() or None
        ),
    }


def _apply_conversation_rules(analysis, message, state):
    normalized = _normalise_message(message)
    if state.pending_action and normalized in AFFIRMATIVE_MESSAGES:
        return {**analysis, "intention": "confirm_action", "params": {}, "confidence": 1}
    if state.pending_action and normalized in NEGATIVE_MESSAGES:
        return {**analysis, "intention": "cancel_pending_action", "params": {}, "confidence": 1}
    if not state.pending_action and state.pending_product_id and normalized in AFFIRMATIVE_MESSAGES:
        return {**analysis, "intention": "cart_add", "params": {}, "confidence": 1}
    if normalized.isdigit() and state.state == "selecting":
        return {
            **analysis,
            "intention": "get_product",
            "params": {"position": int(normalized)},
            "confidence": 1,
        }
    return analysis


def _display_price(value):
    if value in (None, ""):
        return ""
    try:
        return f" - {_money(value)} FCFA"
    except CommerceError:
        return ""


def _format_french_message(analysis, commerce_result):
    result = commerce_result.get("result") or {}
    intention = commerce_result.get("intention") or analysis.get("intention")
    if commerce_result.get("human_takeover"):
        return None
    if commerce_result.get("requires_clarification"):
        return str(
            commerce_result.get("clarification")
            or "Pouvez-vous préciser votre demande ?"
        )
    if commerce_result.get("requires_confirmation"):
        labels = {
            "create_order": "créer la commande",
            "cancel_order": "annuler la commande",
            "request_refund": "enregistrer la demande de remboursement",
            "update_order": "modifier la commande",
            "cart_clear": "vider le panier",
        }
        summary = commerce_result.get("confirmation") or {}
        prefix = ""
        if isinstance(summary.get("cart"), dict) and summary["cart"].get("items"):
            prefix = _format_cart(summary["cart"]) + "\n"
        return (
            prefix
            + "Voulez-vous "
            + labels.get(intention, "effectuer cette action")
            + " ? Répondez oui pour confirmer ou non pour annuler."
        )
    if intention == "cancel_pending_action":
        return "L'action en attente a été annulée."
    if isinstance(result.get("products"), list):
        products = result["products"][:10]
        if not products:
            return "Aucun produit correspondant n'a été trouvé."
        lines = [
            f"{index}. {item.get('nom') or item.get('product_name') or 'Produit'}"
            f"{_display_price(item.get('prix', item.get('price')))}"
            for index, item in enumerate(products, start=1)
        ]
        return "Voici les produits disponibles :\n" + "\n".join(lines) + "\nRépondez avec le numéro du produit choisi."
    selected = result.get("selected_product")
    if isinstance(selected, dict):
        return (
            f"{selected.get('product_name') or selected.get('nom') or 'Produit'}"
            f"{_display_price(selected.get('price', selected.get('prix')))}\n"
            "Souhaitez-vous l'ajouter au panier ?"
        )
    if isinstance(result.get("items"), list):
        if not result["items"]:
            return "Votre panier est vide."
        return _format_cart(result)
    if isinstance(result, dict) and result.get("nom"):
        return f"{result['nom']}{_display_price(result.get('prix'))}"
    if result.get("payment_url"):
        return "Voici votre lien de paiement : " + str(result["payment_url"])
    if result.get("statut"):
        order = f" {result.get('order_id')}" if result.get("order_id") else ""
        return f"Statut de la commande{order} : {str(result['statut']).replace('_', ' ')}."
    if result.get("suivi_disponible") is True:
        details = [result.get("transporteur"), result.get("numero_suivi"), result.get("url_suivi")]
        return "Suivi de votre commande : " + " - ".join(str(value) for value in details if value)
    if result.get("suivi_disponible") is False:
        return "Aucune information de suivi n'est encore disponible pour cette commande."
    if isinstance(result.get("valide"), bool):
        return "Ce code promotionnel est valide." if result["valide"] else "Ce code promotionnel n'est pas valide."
    if isinstance(result.get("en_stock"), bool):
        return "Cette variante est disponible." if result["en_stock"] else "Cette variante est actuellement indisponible."
    if result.get("content"):
        return str(result["content"])
    if result.get("human_takeover"):
        return "Votre demande a été transmise à un conseiller."
    if commerce_result.get("executed") and result.get("order_id"):
        return f"La demande concernant la commande {result['order_id']} a bien été traitée."
    if commerce_result.get("executed"):
        return "Votre demande a bien été traitée."
    if intention == "other":
        return analysis.get("reponse_generale") or (
            "Je peux vous renseigner sur nos produits, votre panier, une commande, "
            "la livraison ou un remboursement."
        )
    return "Je n'ai pas bien compris votre demande. Pouvez-vous la préciser en quelques mots ?"


def _message_turn(data):
    """Traite un message complet et renvoie directement la réponse WhatsApp."""
    _required(data, "user_id", "message")
    user_id = str(data["user_id"])
    message = " ".join(str(data["message"]).strip().split())
    trace_id = str(data.get("message_id") or uuid4().hex)
    state = _state(user_id)
    if state.state == "human_takeover":
        return {"message": None, "silent": True, "trace_id": trace_id}
    if message in {"", "[MESSAGE_VIDE]"}:
        return {
            "message": "Pouvez-vous préciser votre demande ?",
            "silent": False,
            "trace_id": trace_id,
        }
    if message == "[MEDIA_SANS_TEXTE]":
        return {
            "message": "Décrivez-moi votre demande par écrit afin que je puisse vous aider.",
            "silent": False,
            "trace_id": trace_id,
        }
    basic = BASIC_FRENCH_RESPONSES.get(_normalise_message(message))
    if basic:
        return {"message": basic, "silent": False, "trace_id": trace_id}

    degraded = False
    local_analysis = _fallback_analysis(message, state)
    if local_analysis["intention"] != "other":
        # Les demandes fréquentes restent instantanées et continuent à marcher
        # même lorsque Moonshot est ralenti ou indisponible.
        analysis = local_analysis
    else:
        try:
            raw_analysis = KimiClient().classify(message, _state_payload(state))
            analysis = _validated_message_analysis(raw_analysis, message, state)
        except CommerceError as exc:
            degraded = True
            logger.warning("Kimi indisponible pour message_turn trace=%s: %s", trace_id, exc.message)
            analysis = local_analysis
    analysis = _apply_conversation_rules(analysis, message, state)

    intent_data = {
        "user_id": user_id,
        "session_key": str(data.get("session_key") or "current"),
        "timestamp": data.get("timestamp"),
        "idempotency_key": f"{user_id}:{trace_id}:{analysis['intention']}",
        **analysis,
    }
    try:
        commerce_result = _execute_intent(intent_data)
    except CommerceError as exc:
        logger.warning(
            "Commerce indisponible pour message_turn trace=%s intention=%s statut=%s: %s",
            trace_id,
            analysis["intention"],
            exc.status_code,
            exc.message,
        )
        return {
            "message": "Le service boutique est momentanément indisponible. Réessayez dans quelques instants.",
            "silent": False,
            "trace_id": trace_id,
            "degraded": True,
            "error_type": "commerce_unavailable",
        }
    answer = _format_french_message(analysis, commerce_result)
    silent = answer is None
    logger.info(
        "message_turn terminé trace=%s intention=%s degraded=%s silent=%s",
        trace_id,
        analysis["intention"],
        degraded,
        silent,
    )
    return {
        "message": answer,
        "silent": silent,
        "trace_id": trace_id,
        "degraded": degraded,
        "analysis": analysis,
        "commerce": commerce_result,
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
    "execute_intent": _execute_intent,
    "conversation_turn": _conversation_turn,
    "message_turn": _message_turn,
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
