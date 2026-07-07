from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("commerce", "0011_conversation_recent_messages")]

    operations = [
        migrations.CreateModel(
            name="RateLimitBucket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_ip", models.CharField(max_length=64, unique=True)),
                ("window_started_at", models.DateTimeField()),
                ("request_count", models.PositiveIntegerField(default=0)),
            ],
            options={"db_table": "commerce_rate_limits"},
        ),
    ]
