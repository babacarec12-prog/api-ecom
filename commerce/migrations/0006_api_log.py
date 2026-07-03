from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("commerce", "0005_database_catalog")]

    operations = [
        migrations.CreateModel(
            name="ApiLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("user_id", models.CharField(blank=True, db_index=True, max_length=100)),
                ("action", models.CharField(blank=True, db_index=True, max_length=100)),
                ("success", models.BooleanField(db_index=True, default=False)),
                ("error", models.TextField(blank=True)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "api_logs", "ordering": ["-created_at"]},
        )
    ]
