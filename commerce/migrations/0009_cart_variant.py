from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0008_product_catalogue_metadata"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="cart",
            name="unique_cart_product_per_user",
        ),
        migrations.AddField(
            model_name="cart",
            name="variant_id",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddConstraint(
            model_name="cart",
            constraint=models.UniqueConstraint(
                fields=("user_id", "product_id", "variant_id"),
                name="unique_cart_product_variant_per_user",
            ),
        ),
    ]
