from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("commerce", "0010_payment_transaction")]
    operations = [
        migrations.AddField(
            model_name="conversationstate",
            name="recent_messages",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
