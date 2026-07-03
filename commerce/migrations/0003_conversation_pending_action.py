from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0002_align_supabase_table_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversationstate",
            name="pending_action",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="conversationstate",
            name="pending_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
