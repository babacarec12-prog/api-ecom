from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0007_rename_api_log_error"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="images",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="product",
            name="variants",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="product",
            name="platform",
            field=models.CharField(db_index=True, default="database", max_length=20),
        ),
    ]
