"""Client minimal pour l'API REST WooCommerce."""
import os

import requests

from .exceptions import CommerceError


class WooCommerceClient:
    def __init__(self):
        store_url = os.getenv("WOO_STORE_URL", "").strip().rstrip("/")
        key = os.getenv("WOO_CONSUMER_KEY", "").strip()
        secret = os.getenv("WOO_CONSUMER_SECRET", "").strip()
        if not store_url or not key or not secret:
            raise CommerceError("La configuration WooCommerce est incomplète.", 500)
        self.base_url = f"{store_url}/wp-json/wc/v3"
        self.auth = (key, secret)
        # Local utilise un certificat auto-signé. En production, conserver True.
        self.verify_ssl = os.getenv("WOO_VERIFY_SSL", "True").lower() in {
            "1",
            "true",
            "yes",
        }

    def _request(self, method, path, **kwargs):
        try:
            response = requests.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                auth=self.auth,
                verify=self.verify_ssl,
                timeout=20,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise CommerceError(f"WooCommerce est inaccessible : {exc}") from exc

        if response.status_code == 404:
            raise CommerceError("Ressource WooCommerce introuvable.", 404)
        if not response.ok:
            try:
                message = response.json().get("message", response.text[:300])
            except ValueError:
                message = response.text[:300]
            raise CommerceError(f"Erreur WooCommerce ({response.status_code}) : {message}")
        try:
            return response.json()
        except ValueError as exc:
            raise CommerceError("WooCommerce a renvoyé une réponse JSON invalide.") from exc

    @staticmethod
    def _stock(product):
        return product.get("stock_quantity") or (0 if product.get("stock_status") == "outofstock" else None)

    def search_products(self, query):
        products = self._request("GET", "products", params={"search": query, "per_page": 50})
        return [
            {
                "id": str(product["id"]),
                "nom": product.get("name"),
                "prix": product.get("price"),
                "stock": self._stock(product),
                "plateforme": "woocommerce",
            }
            for product in products
        ]

    def get_product(self, product_id):
        product = self._request("GET", f"products/{product_id}")
        variations = []
        if product.get("variations"):
            raw_variations = self._request("GET", f"products/{product_id}/variations", params={"per_page": 100})
            variations = [
                {
                    "id": str(variant.get("id")),
                    "nom": " / ".join(
                        attr.get("option", "") for attr in variant.get("attributes", [])
                    ),
                    "prix": variant.get("price"),
                    "stock": self._stock(variant),
                    "sku": variant.get("sku"),
                }
                for variant in raw_variations
            ]
        return {
            "id": str(product.get("id", product_id)),
            "nom": product.get("name"),
            "description": product.get("description", ""),
            "images": [image.get("src") for image in product.get("images", [])],
            "variantes": variations,
            "prix": product.get("price"),
            "stock": self._stock(product),
            "plateforme": "woocommerce",
        }

    def create_order(self, user_id, cart):
        line_items = []
        for item in cart:
            line = {
                "product_id": int(item["product_id"]),
                "quantity": int(item.get("quantity", 1)),
            }
            if item.get("variant_id"):
                line["variation_id"] = int(item["variant_id"])
            line_items.append(line)

        order = self._request(
            "POST",
            "orders",
            json={
                "status": "pending",
                "line_items": line_items,
                "customer_note": f"Commande WhatsApp - utilisateur {user_id}",
                "meta_data": [{"key": "whatsapp_user_id", "value": str(user_id)}],
            },
        )
        return {
            "order_id": str(order.get("id")),
            "montant_total": order.get("total"),
            "devise": order.get("currency"),
            "plateforme": "woocommerce",
        }

    def get_order_status(self, order_id):
        order = self._request("GET", f"orders/{order_id}")
        mapping = {
            "pending": "en_attente",
            "on-hold": "en_attente",
            "failed": "en_attente",
            "cancelled": "en_attente",
            "processing": "confirmée",
            "completed": "livrée",
            "refunded": "livrée",
        }
        # Le statut personnalisé « shipped » est compris s'il existe dans la boutique.
        status = "expédiée" if order.get("status") == "shipped" else mapping.get(order.get("status"), "en_attente")
        return {"order_id": str(order_id), "statut": status, "plateforme": "woocommerce"}
