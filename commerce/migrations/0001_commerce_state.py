from django.db import migrations, models


def seed_policies(apps, schema_editor):
    policy = apps.get_model("commerce", "ShopPolicy")
    values = {
        "delivery": "Livraison sous 3-5 jours ouvrés. Gratuite dès 50 € d'achats.",
        "returns": "Retours acceptés sous 14 jours. Produit non utilisé dans son emballage d'origine.",
        "refund": "Remboursement sous 5-7 jours ouvrés après réception du retour.",
    }
    for policy_type, content in values.items():
        policy.objects.update_or_create(
            policy_type=policy_type, defaults={"content": content}
        )


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Cart",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=50)),
                ("product_id", models.CharField(max_length=50)),
                ("product_name", models.CharField(blank=True, max_length=255)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("platform", models.CharField(default="woocommerce", max_length=20)),
                ("idempotency_key", models.CharField(blank=True, max_length=100, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("user_id", "product_id"), name="unique_cart_product_per_user")]},
        ),
        migrations.CreateModel(
            name="ProductSelection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=50)),
                ("session_key", models.CharField(max_length=100)),
                ("position", models.PositiveIntegerField()),
                ("product_id", models.CharField(max_length=50)),
                ("product_name", models.CharField(blank=True, max_length=255)),
                ("price", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("user_id", "session_key", "position"), name="unique_selection_position")]},
        ),
        migrations.CreateModel(
            name="ConversationState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(max_length=50, unique=True)),
                ("state", models.CharField(default="browsing", max_length=50)),
                ("previous_state", models.CharField(default="browsing", max_length=50)),
                ("pending_product_id", models.CharField(blank=True, max_length=50, null=True)),
                ("pending_order_id", models.CharField(blank=True, max_length=50, null=True)),
                ("pending_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("last_updated", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="ProcessedRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("idempotency_key", models.CharField(max_length=100, unique=True)),
                ("action", models.CharField(max_length=50)),
                ("result", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="UserOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=50)),
                ("order_id", models.CharField(max_length=50, unique=True)),
                ("platform", models.CharField(default="woocommerce", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="HumanTransfer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=50)),
                ("reason", models.TextField(blank=True)),
                ("status", models.CharField(default="pending", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="ShopPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("policy_type", models.CharField(max_length=50, unique=True)),
                ("content", models.TextField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.RunPython(seed_policies, migrations.RunPython.noop),
    ]
