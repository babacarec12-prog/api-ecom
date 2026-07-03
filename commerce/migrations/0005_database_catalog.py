from django.db import migrations, models


PRODUCTS = [
    {
        "external_id": "DB-001",
        "name": "Batterie externe 10 000 mAh",
        "description": "Batterie portable USB-C avec charge rapide.",
        "category": "Électronique",
        "price": "22000",
        "stock": 15,
        "sku": "BAT-10000",
    },
    {
        "external_id": "DB-002",
        "name": "Écouteurs Bluetooth Nomad",
        "description": "Écouteurs sans fil avec boîtier de recharge.",
        "category": "Électronique",
        "price": "18500",
        "stock": 20,
        "sku": "ECO-NOMAD",
    },
    {
        "external_id": "DB-003",
        "name": "Bissap naturel 1 litre",
        "description": "Boisson artisanale au bissap, sans conservateur.",
        "category": "Boissons",
        "price": "2500",
        "stock": 40,
        "sku": "BIS-1L",
    },
    {
        "external_id": "DB-004",
        "name": "Sac à dos urbain Dakar",
        "description": "Sac résistant avec compartiment pour ordinateur portable.",
        "category": "Accessoires",
        "price": "15000",
        "stock": 12,
        "sku": "SAC-DAKAR",
    },
    {
        "external_id": "DB-005",
        "name": "T-shirt coton Sénégal",
        "description": "T-shirt unisexe en coton, tailles S à XXL.",
        "category": "Vêtements",
        "price": "7500",
        "stock": 30,
        "sku": "TS-SEN",
    },
]


def seed_products(apps, schema_editor):
    product = apps.get_model("commerce", "Product")
    for item in PRODUCTS:
        product.objects.update_or_create(
            external_id=item["external_id"], defaults=item
        )


class Migration(migrations.Migration):
    dependencies = [("commerce", "0004_correct_default_shop_policies")]

    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("category", models.CharField(blank=True, db_index=True, max_length=100)),
                ("price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("stock", models.PositiveIntegerField(default=0)),
                ("sku", models.CharField(blank=True, max_length=100)),
                ("image_url", models.URLField(blank=True)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "products", "ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="userorder",
            name="amount_total",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name="userorder",
            name="currency",
            field=models.CharField(default="XOF", max_length=10),
        ),
        migrations.AddField(
            model_name="userorder",
            name="items",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="userorder",
            name="status",
            field=models.CharField(default="pending", max_length=30),
        ),
        migrations.RunPython(seed_products, migrations.RunPython.noop),
    ]
