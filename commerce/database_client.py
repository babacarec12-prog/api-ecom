"""Catalogue et commandes de démonstration stockés dans PostgreSQL/SQLite."""

from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.db.models import Q

from .exceptions import CommerceError
from .models import Product


class DatabaseCatalogClient:
    platform = "database"

    @staticmethod
    def _format(product):
        return {
            "id": product.external_id,
            "nom": product.name,
            "description": product.description,
            "categorie": product.category,
            "prix": str(product.price),
            "stock": product.stock,
            "image": product.image_url or None,
            "images": product.images or ([product.image_url] if product.image_url else []),
            "variantes": product.variants or [],
            "plateforme": product.platform,
        }

    def search_products(self, query):
        query = str(query or "").strip()
        products = Product.objects.filter(active=True, stock__gt=0)
        if query and query != "*":
            words = [word for word in query.split() if len(word) >= 2]
            filters = Q()
            for word in words:
                filters |= (
                    Q(name__icontains=word)
                    | Q(description__icontains=word)
                    | Q(category__icontains=word)
                    | Q(sku__icontains=word)
                )
            products = products.filter(filters) if words else products.none()
        return [self._format(product) for product in products.order_by("name")[:50]]

    def get_product(self, product_id):
        product = Product.objects.filter(
            external_id=str(product_id), active=True
        ).first()
        if not product:
            raise CommerceError("Produit introuvable dans le catalogue.", 404)
        return self._format(product)

    def check_variant_stock(self, product_id, variant_id):
        product = self.get_product(product_id)
        variant = next(
            (
                item for item in product.get("variantes", [])
                if str(item.get("id")) == str(variant_id)
            ),
            None,
        )
        if not variant:
            raise CommerceError("Variante introuvable dans le catalogue.", 404)
        stock = variant.get("stock")
        return {
            "product_id": str(product_id),
            "variant_id": str(variant_id),
            "en_stock": variant.get("en_stock", stock is None or int(stock) > 0),
            "stock": stock,
            "prix": variant.get("prix") or product.get("prix"),
            "attributs": variant.get("attributs", []),
            "plateforme": product.get("plateforme", "database"),
        }

    def create_order(self, user_id, cart):
        items = []
        total = Decimal("0")
        with transaction.atomic():
            for line in cart:
                product = Product.objects.select_for_update().filter(
                    external_id=str(line["product_id"]), active=True
                ).first()
                if not product:
                    raise CommerceError("Un produit du panier n'existe plus.", 409)
                quantity = int(line.get("quantity", 1))
                if product.stock < quantity:
                    raise CommerceError(
                        f"Stock insuffisant pour {product.name} : {product.stock} disponible(s).",
                        409,
                    )
                product.stock -= quantity
                product.save(update_fields=["stock", "updated_at"])
                line_total = product.price * quantity
                total += line_total
                items.append(
                    {
                        "product_id": product.external_id,
                        "variant_id": line.get("variant_id"),
                        "product_name": product.name,
                        "quantity": quantity,
                        "price": str(product.price),
                        "line_total": str(line_total),
                    }
                )
        return {
            "order_id": "DB-" + uuid4().hex[:10].upper(),
            "montant_total": str(total),
            "devise": "XOF",
            "statut": "pending",
            "items": items,
            "plateforme": "database",
        }
