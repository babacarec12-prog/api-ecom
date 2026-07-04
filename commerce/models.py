"""Modèles persistants du parcours commercial WhatsApp."""

from django.db import models


class Product(models.Model):
    """Produit du catalogue interne utilisé avant la mise en ligne de WooCommerce."""

    external_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    sku = models.CharField(max_length=100, blank=True)
    image_url = models.URLField(blank=True)
    images = models.JSONField(default=list, blank=True)
    variants = models.JSONField(default=list, blank=True)
    platform = models.CharField(max_length=20, default="database", db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"
        ordering = ["name"]


class Cart(models.Model):
    """Ligne du panier courant d'un client WhatsApp."""

    user_id = models.CharField(max_length=50, db_index=True)
    product_id = models.CharField(max_length=50)
    variant_id = models.CharField(max_length=50, blank=True, default="")
    product_name = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    platform = models.CharField(max_length=20, default="woocommerce")
    idempotency_key = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carts"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "product_id", "variant_id"],
                name="unique_cart_product_variant_per_user",
            )
        ]


class ProductSelection(models.Model):
    """Correspondance exacte entre un numéro affiché et un produit."""

    user_id = models.CharField(max_length=50, db_index=True)
    session_key = models.CharField(max_length=100)
    position = models.PositiveIntegerField()
    product_id = models.CharField(max_length=50)
    product_name = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "product_selections"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "session_key", "position"],
                name="unique_selection_position",
            )
        ]


class ConversationState(models.Model):
    """État transactionnel courant et état précédent de la conversation."""

    user_id = models.CharField(max_length=50, unique=True)
    state = models.CharField(max_length=50, default="browsing")
    previous_state = models.CharField(max_length=50, default="browsing")
    pending_product_id = models.CharField(max_length=50, blank=True, null=True)
    pending_order_id = models.CharField(max_length=50, blank=True, null=True)
    pending_amount = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    pending_action = models.CharField(max_length=50, blank=True, null=True)
    pending_payload = models.JSONField(default=dict, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversation_states"


class ProcessedRequest(models.Model):
    """Résultat mémorisé d'une opération sensible idempotente."""

    idempotency_key = models.CharField(max_length=100, unique=True)
    action = models.CharField(max_length=50)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "processed_requests"


class UserOrder(models.Model):
    """Association entre une commande WooCommerce et son propriétaire WhatsApp."""

    user_id = models.CharField(max_length=50, db_index=True)
    order_id = models.CharField(max_length=50, unique=True)
    platform = models.CharField(max_length=20, default="woocommerce")
    amount_total = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    currency = models.CharField(max_length=10, default="XOF")
    status = models.CharField(max_length=30, default="pending")
    items = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_orders"


class PaymentTransaction(models.Model):
    """Transaction PayTech persistante et mise à jour par les notifications IPN."""

    user_id = models.CharField(max_length=50, db_index=True)
    order_id = models.CharField(max_length=50, db_index=True)
    reference = models.CharField(max_length=100, unique=True)
    token = models.CharField(max_length=255, unique=True)
    payment_url = models.URLField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="XOF")
    provider = models.CharField(max_length=20, default="paytech")
    status = models.CharField(max_length=20, default="pending", db_index=True)
    last_event = models.CharField(max_length=50, blank=True)
    callback_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payment_transactions"


class HumanTransfer(models.Model):
    """Demande persistante de prise en charge humaine."""

    user_id = models.CharField(max_length=50, db_index=True)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "human_transfers"


class ShopPolicy(models.Model):
    """Politique officielle présentée au client par l'agent."""

    policy_type = models.CharField(max_length=50, unique=True)
    content = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shop_policies"


class ApiLog(models.Model):
    """Journal technique minimal de chaque appel à l'API commerce."""

    user_id = models.CharField(max_length=100, blank=True, db_index=True)
    action = models.CharField(max_length=100, blank=True, db_index=True)
    success = models.BooleanField(default=False, db_index=True)
    error_message = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_logs"
        ordering = ["-created_at"]
