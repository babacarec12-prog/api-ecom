from django.db import migrations, models


def drop_legacy_constraint_if_present(apps, schema_editor):
    """Certaines bases Supabase historiques ont la table sans cette contrainte."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            'ALTER TABLE "carts" '
            'DROP CONSTRAINT IF EXISTS "unique_cart_product_per_user"'
        )


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0008_product_catalogue_metadata"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    drop_legacy_constraint_if_present,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="cart",
                    name="unique_cart_product_per_user",
                ),
            ],
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
