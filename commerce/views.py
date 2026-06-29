"""Endpoint unique utilisé par l'agent IA et le workflow n8n."""
import json
import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .exceptions import CommerceError
from .shopify_client import ShopifyClient
from .stripe_client import StripeClient
from .woo_client import WooCommerceClient

logger = logging.getLogger(__name__)
ALLOWED_ACTIONS = {
    "search_products",
    "get_product",
    "create_order",
    "generate_payment",
    "get_order_status",
}


def _required(data, *fields):
    missing = [field for field in fields if data.get(field) in (None, "", [])]
    if missing:
        raise CommerceError(f"Champ(s) requis manquant(s) : {', '.join(missing)}.", 400)


def _platform(value):
    normalized = str(value or "").strip().casefold()
    aliases = {"shopify": "shopify", "woo": "woocommerce", "woocommerce": "woocommerce"}
    if normalized not in aliases:
        raise CommerceError("La plateforme doit être 'shopify' ou 'woocommerce'.", 400)
    return aliases[normalized]


def _client(platform):
    return ShopifyClient() if platform == "shopify" else WooCommerceClient()


def _validate_cart(cart, default_platform=None):
    if not isinstance(cart, list) or not cart:
        raise CommerceError("Le panier doit être une liste non vide.", 400)

    platforms = set()
    cleaned = []
    for index, item in enumerate(cart):
        if not isinstance(item, dict) or not item.get("product_id"):
            raise CommerceError(f"L'article {index + 1} doit contenir product_id.", 400)
        platform = _platform(item.get("platform") or default_platform)
        platforms.add(platform)
        try:
            quantity = int(item.get("quantity", 1))
        except (TypeError, ValueError) as exc:
            raise CommerceError(f"Quantité invalide pour l'article {index + 1}.", 400) from exc
        if quantity <= 0:
            raise CommerceError(f"La quantité de l'article {index + 1} doit être positive.", 400)
        cleaned.append({**item, "quantity": quantity, "platform": platform})

    if len(platforms) != 1:
        raise CommerceError("Une commande ne peut pas mélanger Shopify et WooCommerce.", 400)
    return platforms.pop(), cleaned


def _search(data):
    _required(data, "query")
    # Une erreur sur une boutique n'empêche pas de retourner les résultats de l'autre.
    products, warnings = [], []
    for name, client_class in (("Shopify", ShopifyClient), ("WooCommerce", WooCommerceClient)):
        try:
            products.extend(client_class().search_products(str(data["query"]).strip()))
        except CommerceError as exc:
            warnings.append(f"{name} : {exc.message}")
    if len(warnings) == 2:
        raise CommerceError("; ".join(warnings), 502)
    result = {"products": products}
    if warnings:
        result["warnings"] = warnings
    return result


def _get_product(data):
    _required(data, "product_id", "platform")
    return _client(_platform(data["platform"])).get_product(data["product_id"])


def _create_order(data):
    _required(data, "user_id", "cart")
    platform, cart = _validate_cart(data["cart"], data.get("platform"))
    return _client(platform).create_order(data["user_id"], cart)


def _generate_payment(data):
    _required(data, "order_id", "amount")
    return StripeClient().generate_payment(data["order_id"], data["amount"])


def _get_order_status(data):
    _required(data, "order_id")
    if data.get("platform"):
        return _client(_platform(data["platform"])).get_order_status(data["order_id"])

    # Sans plateforme, on cherche d'abord sur Shopify puis sur WooCommerce.
    try:
        return ShopifyClient().get_order_status(data["order_id"])
    except CommerceError as shopify_error:
        try:
            return WooCommerceClient().get_order_status(data["order_id"])
        except CommerceError as woo_error:
            raise CommerceError(
                f"Commande introuvable. Shopify : {shopify_error.message}; "
                f"WooCommerce : {woo_error.message}",
                404 if shopify_error.status_code == woo_error.status_code == 404 else 502,
            ) from woo_error


HANDLERS = {
    "search_products": _search,
    "get_product": _get_product,
    "create_order": _create_order,
    "generate_payment": _generate_payment,
    "get_order_status": _get_order_status,
}


@api_view(["POST"])
@permission_classes([AllowAny])
def commerce(request):
    """Route toutes les opérations e-commerce via le champ ``action``."""
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

        # Certains modèles renvoient ``data`` sous forme de texte JSON. Pour la
        # recherche, ils peuvent même envoyer directement le terme recherché.
        if isinstance(data, str):
            raw_data = data.strip()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                if action == "search_products" and raw_data:
                    data = {"query": raw_data}
                else:
                    raise CommerceError(
                        "Le champ 'data' doit être un objet JSON valide.", 400
                    )
        if not isinstance(data, dict):
            raise CommerceError("Le champ 'data' doit être un objet JSON.", 400)
        return Response({"success": True, "data": HANDLERS[action](data)}, status=200)
    except CommerceError as exc:
        return Response({"success": False, "error": exc.message}, status=exc.status_code)
    except APIException:
        # Laisser le gestionnaire DRF uniformiser notamment les JSON malformés.
        raise
    except Exception:
        # La trace détaillée reste dans les logs et n'expose aucun secret au client.
        logger.exception("Erreur inattendue dans l'endpoint commerce")
        return Response(
            {"success": False, "error": "Une erreur interne inattendue est survenue."},
            status=500,
        )
