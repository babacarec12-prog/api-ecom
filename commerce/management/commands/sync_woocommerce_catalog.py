from django.core.management.base import BaseCommand
from django.db import transaction

from commerce.models import Product
from commerce.woo_client import WooCommerceClient


class Command(BaseCommand):
    help = "Synchronise le catalogue WooCommerce dans la table products."

    def handle(self, *args, **options):
        catalogue = WooCommerceClient().export_catalogue()
        identifiers = {item["external_id"] for item in catalogue}
        with transaction.atomic():
            for item in catalogue:
                external_id = item["external_id"]
                defaults = {
                    key: value for key, value in item.items() if key != "external_id"
                }
                Product.objects.update_or_create(
                    external_id=external_id,
                    defaults=defaults,
                )
            stale = Product.objects.filter(platform="woocommerce")
            if identifiers:
                stale = stale.exclude(external_id__in=identifiers)
            stale.update(active=False)
        self.stdout.write(
            self.style.SUCCESS(f"Catalogue WooCommerce synchronisé : {len(catalogue)} produit(s).")
        )
