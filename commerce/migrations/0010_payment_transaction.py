from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("commerce", "0009_cart_variant")]

    operations = [
        migrations.CreateModel(
            name="PaymentTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=50)),
                ("order_id", models.CharField(db_index=True, max_length=50)),
                ("reference", models.CharField(max_length=100, unique=True)),
                ("token", models.CharField(max_length=255, unique=True)),
                ("payment_url", models.URLField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("currency", models.CharField(default="XOF", max_length=10)),
                ("provider", models.CharField(default="paytech", max_length=20)),
                ("status", models.CharField(db_index=True, default="pending", max_length=20)),
                ("last_event", models.CharField(blank=True, max_length=50)),
                ("callback_payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "payment_transactions"},
        ),
    ]
