"""Client minimal pour l'API Admin REST de Shopify."""
import os

import requests

from .exceptions import CommerceError


class ShopifyClient:
    def __init__(self):
        domain = os.getenv("SHOPIFY_STORE_DOMAIN", "").strip().rstrip("/")
        token = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip()
        version = os.getenv("SHOPIFY_API_VERSION", "2026-04")
        if not domain or not token:
            raise CommerceError("La configuration Shopify est incomplète.", 500)
        domain = domain.removeprefix("https://").removeprefix("http://")
        self.base_url = f"https://{domain}/admin/api/{version}"
        self.headers = {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        }

    def _request(self, method, path, **kwargs):
        try:
            response = requests.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                headers=self.headers,
                timeout=20,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise CommerceError(f"Shopify est inaccessible : {exc}") from exc

        if response.status_code == 404:
            raise CommerceError("Ressource Shopify introuvable.", 404)
        if not response.ok:
            raise CommerceError(
                f"Erreur Shopify ({response.status_code}) : {self._error(response)}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise CommerceError("Shopify a renvoyé une réponse JSON invalide.") from exc

    @staticmethod
    def _error(response):
        try:
            payload = response.json()
            return str(payload.get("errors", payload))
        except ValueError:
            return response.text[:300] or "réponse vide"

    @staticmethod
    def _stock(product):
        stocks = [v.get("inventory_quantity", 0) or 0 for v in product.get("variants", [])]
        return sum(stocks)

    @staticmethod
    def _price(product):
        variants = product.get("variants", [])
        return variants[0].get("price") if variants else None

    def search_products(self, query):
        # Shopify REST ne propose pas une recherche plein texte dédiée : title est
        # utilisé côté serveur, puis un filtrage souple est appliqué localement.
        payload = self._request("GET", "products.json", params={"title": query, "limit": 50})
        products = payload.get("products", [])
        words = query.casefold().split()
        filtered = [
            product
            for product in products
            if all(word in product.get("title", "").casefold() for word in words)
        ]
        return [
            {
                "id": str(product["id"]),
                "nom": product.get("title"),
                "prix": self._price(product),
                "stock": self._stock(product),
                "plateforme": "shopify",
                "default_variant_id": (
                    str(product["variants"][0]["id"]) if product.get("variants") else None
                ),
            }
            for product in filtered
        ]

    def get_product(self, product_id):
        product = self._request("GET", f"products/{product_id}.json").get("product", {})
        return {
            "id": str(product.get("id", product_id)),
            "nom": product.get("title"),
            "description": product.get("body_html", ""),
            "images": [image.get("src") for image in product.get("images", [])],
            "variantes": [
                {
                    "id": str(variant.get("id")),
                    "nom": variant.get("title"),
                    "prix": variant.get("price"),
                    "stock": variant.get("inventory_quantity", 0),
                    "sku": variant.get("sku"),
                }
                for variant in product.get("variants", [])
            ],
            "stock": self._stock(product),
            "plateforme": "shopify",
        }

    def create_order(self, user_id, cart):
        line_items = []
        for item in cart:
            variant_id = item.get("variant_id")
            if not variant_id:
                product = self.get_product(item["product_id"])
                variants = product.get("variantes", [])
                if not variants:
                    raise CommerceError(
                        f"Le produit Shopify {item['product_id']} n'a aucune variante.", 400
                    )
                variant_id = variants[0]["id"]
            line_items.append(
                {"variant_id": int(variant_id), "quantity": int(item.get("quantity", 1))}
            )

        body = {
            "order": {
                "line_items": line_items,
                "note": f"Commande WhatsApp - utilisateur {user_id}",
                "tags": "AI Commerce Assistant,WhatsApp",
                "financial_status": "pending",
            }
        }
        order = self._request("POST", "orders.json", json=body).get("order", {})
        return {
            "order_id": str(order.get("id")),
            "montant_total": order.get("total_price"),
            "devise": order.get("currency"),
            "plateforme": "shopify",
        }

    def get_order_status(self, order_id):
        order = self._request("GET", f"orders/{order_id}.json").get("order", {})
        tags = {tag.strip().casefold() for tag in order.get("tags", "").split(",")}
        if "livrée" in tags or "delivered" in tags:
            status = "livrée"
        elif order.get("fulfillment_status") == "fulfilled":
            status = "expédiée"
        elif order.get("financial_status") in {"paid", "partially_paid"}:
            status = "confirmée"
        else:
            status = "en_attente"
        return {"order_id": str(order_id), "statut": status, "plateforme": "shopify"}
