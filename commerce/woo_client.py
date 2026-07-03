"""Client minimal pour l'API REST WooCommerce."""
from difflib import SequenceMatcher
import hashlib
import os
import re
import unicodedata

import requests
from django.core.cache import cache

from .exceptions import CommerceError


class WooCommerceClient:
    FUZZY_BLOCKED_QUERIES = {
        "oui",
        "non",
        "ok",
        "okay",
        "confirme",
        "confirmation",
        "bonjour",
        "bonsoir",
        "salut",
        "merci",
        "commande",
    }
    def __init__(self):
        # Les alias courts gardent la compatibilité avec le cahier des charges
        # sans casser les noms historiques déjà utilisés sur Render.
        store_url = (os.getenv("WOO_STORE_URL") or os.getenv("WOO_URL", "")).strip().rstrip("/")
        key = (os.getenv("WOO_CONSUMER_KEY") or os.getenv("WOO_KEY", "")).strip()
        secret = (os.getenv("WOO_CONSUMER_SECRET") or os.getenv("WOO_SECRET", "")).strip()
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
        quantity = product.get("stock_quantity")
        if quantity is not None:
            return quantity
        return 0 if product.get("stock_status") == "outofstock" else None

    @staticmethod
    def _normalize(value):
        """Normalise un texte pour comparer les recherches avec le catalogue."""
        value = unicodedata.normalize("NFKD", str(value or ""))
        value = "".join(char for char in value if not unicodedata.combining(char))
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

    @classmethod
    def _fuzzy_score(cls, query, product):
        """Retourne un score simple et déterministe de proximité avec un produit."""
        fields = [
            product.get("name"),
            product.get("slug"),
            product.get("sku"),
            product.get("short_description"),
            product.get("description"),
            *(item.get("name") for item in product.get("categories", [])),
            *(item.get("name") for item in product.get("tags", [])),
        ]
        searchable = cls._normalize(" ".join(str(field or "") for field in fields))
        normalized_query = cls._normalize(query)
        if not normalized_query or not searchable:
            return 0.0
        if normalized_query in searchable:
            return 1.0

        searchable_words = searchable.split()
        query_words = normalized_query.split()
        word_score = sum(
            max(
                (SequenceMatcher(None, query_word, word).ratio() for word in searchable_words),
                default=0.0,
            )
            for query_word in query_words
        ) / len(query_words)
        name_score = SequenceMatcher(
            None, normalized_query, cls._normalize(product.get("name"))
        ).ratio()
        return max(word_score, name_score)

    @classmethod
    def _can_use_fuzzy_fallback(cls, query):
        """Évite de prendre une réponse conversationnelle pour un produit."""
        normalized_query = cls._normalize(query)
        return (
            len(normalized_query) >= 4
            and not normalized_query.isdigit()
            and normalized_query not in cls.FUZZY_BLOCKED_QUERIES
        )

    @classmethod
    def _format_products(cls, products):
        return [
            {
                "id": str(product["id"]),
                "nom": product.get("name"),
                "prix": product.get("price"),
                "stock": cls._stock(product),
                "plateforme": "woocommerce",
            }
            for product in products
        ]

    def search_products(self, query):
        query = str(query or "").strip()
        cache_key = "woo:products:" + hashlib.sha256(
            self._normalize(query).encode("utf-8")
        ).hexdigest()
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # L'astérisque permet à l'agent de demander explicitement le catalogue.
        if query == "*":
            products = self._request("GET", "products", params={"per_page": 100})
            formatted = self._format_products(products)
            cache.set(cache_key, formatted, timeout=60)
            return formatted

        products = self._request(
            "GET", "products", params={"search": query, "per_page": 50}
        )
        if products:
            formatted = self._format_products(products)
            cache.set(cache_key, formatted, timeout=60)
            return formatted

        if not self._can_use_fuzzy_fallback(query):
            cache.set(cache_key, [], timeout=30)
            return []

        # WooCommerce ne corrige pas les fautes de frappe. En cas de recherche
        # vide, on compare donc localement au plus 100 produits du catalogue.
        catalogue = self._request("GET", "products", params={"per_page": 100})
        matches = [
            (self._fuzzy_score(query, product), product) for product in catalogue
        ]
        matches = [item for item in matches if item[0] >= 0.72]
        matches.sort(key=lambda item: item[0], reverse=True)
        formatted = self._format_products([product for _, product in matches[:50]])
        cache.set(cache_key, formatted, timeout=60)
        return formatted

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
            "failed": "échouée",
            "cancelled": "annulée",
            "processing": "confirmée",
            "completed": "livrée",
            "refunded": "remboursée",
        }
        # Le statut personnalisé « shipped » est compris s'il existe dans la boutique.
        status = "expédiée" if order.get("status") == "shipped" else mapping.get(order.get("status"), "en_attente")
        return {"order_id": str(order_id), "statut": status, "plateforme": "woocommerce"}

    @staticmethod
    def _whatsapp_user_id(order):
        for item in order.get("meta_data", []):
            if item.get("key") == "whatsapp_user_id":
                return str(item.get("value", ""))
        return ""

    def order_belongs_to_user(self, order_id, user_id):
        """Vérifie le propriétaire d'une ancienne commande via ses métadonnées."""
        order = self._request("GET", f"orders/{order_id}")
        return self._whatsapp_user_id(order) == str(user_id)

    def cancel_order(self, order_id, reason="", user_id=None):
        """Annule uniquement une commande appartenant au client WhatsApp."""
        order = self._request("GET", f"orders/{order_id}")
        owner = self._whatsapp_user_id(order)
        if not user_id or not owner or owner != str(user_id):
            raise CommerceError(
                "Cette commande n'appartient pas à cet utilisateur WhatsApp.", 403
            )
        payload = {"status": "cancelled"}
        if reason:
            payload["customer_note"] = str(reason).strip()
        order = self._request("PUT", f"orders/{order_id}", json=payload)
        return {
            "order_id": str(order.get("id", order_id)),
            "statut": "annulée",
            "plateforme": "woocommerce",
        }

    def request_refund(self, order_id, amount, reason=""):
        """Crée un remboursement WooCommerce pour un montant explicitement validé."""
        refund = self._request(
            "POST",
            f"orders/{order_id}/refunds",
            json={
                "amount": f"{amount:.2f}",
                "reason": str(reason or "Remboursement demandé via WhatsApp").strip(),
                # En phase MVP, enregistrer le remboursement sans déclencher
                # automatiquement un mouvement financier chez la passerelle.
                "api_refund": False,
            },
        )
        return {
            "order_id": str(order_id),
            "refund_id": str(refund.get("id")),
            "montant": refund.get("amount", f"{amount:.2f}"),
            "statut": "remboursement_enregistré",
            "plateforme": "woocommerce",
        }

    def update_order(self, order_id, line_items):
        """Met à jour les quantités de lignes existantes d'une commande."""
        order = self._request(
            "PUT", f"orders/{order_id}", json={"line_items": line_items}
        )
        return {
            "order_id": str(order.get("id", order_id)),
            "montant_total": order.get("total"),
            "devise": order.get("currency"),
            "lignes": [
                {
                    "line_item_id": str(item.get("id")),
                    "product_id": str(item.get("product_id")),
                    "quantity": item.get("quantity"),
                }
                for item in order.get("line_items", [])
            ],
            "plateforme": "woocommerce",
        }

    def get_tracking(self, order_id):
        """Lit les informations de suivi ajoutées par les extensions WooCommerce courantes."""
        order = self._request("GET", f"orders/{order_id}")
        metadata = {
            str(item.get("key")): item.get("value")
            for item in order.get("meta_data", [])
            if item.get("key")
        }
        tracking_items = metadata.get("_wc_shipment_tracking_items") or metadata.get(
            "shipment_tracking_items"
        )
        if isinstance(tracking_items, list) and tracking_items:
            item = tracking_items[-1]
            number = item.get("tracking_number") or item.get("number")
            provider = item.get("tracking_provider") or item.get("provider")
            url = item.get("custom_tracking_link") or item.get("tracking_link")
        else:
            number = metadata.get("_tracking_number") or metadata.get("tracking_number")
            provider = metadata.get("_tracking_provider") or metadata.get("tracking_provider")
            url = metadata.get("_tracking_link") or metadata.get("tracking_link")
        return {
            "order_id": str(order_id),
            "numero_suivi": number,
            "transporteur": provider,
            "url_suivi": url,
            "suivi_disponible": bool(number or url),
            "plateforme": "woocommerce",
        }

    def validate_coupon(self, code):
        coupons = self._request("GET", "coupons", params={"code": code, "per_page": 10})
        coupon = next(
            (item for item in coupons if str(item.get("code", "")).casefold() == code.casefold()),
            None,
        )
        if not coupon:
            return {"code": code, "valide": False, "plateforme": "woocommerce"}
        return {
            "code": coupon.get("code"),
            "valide": coupon.get("status", "publish") == "publish",
            "type_remise": coupon.get("discount_type"),
            "montant": coupon.get("amount"),
            "date_expiration": coupon.get("date_expires"),
            "minimum": coupon.get("minimum_amount"),
            "maximum": coupon.get("maximum_amount"),
            "plateforme": "woocommerce",
        }

    def check_variant_stock(self, product_id, variant_id):
        variant = self._request("GET", f"products/{product_id}/variations/{variant_id}")
        return {
            "product_id": str(product_id),
            "variant_id": str(variant_id),
            "en_stock": variant.get("stock_status") != "outofstock",
            "stock": self._stock(variant),
            "prix": variant.get("price"),
            "attributs": variant.get("attributes", []),
            "plateforme": "woocommerce",
        }
