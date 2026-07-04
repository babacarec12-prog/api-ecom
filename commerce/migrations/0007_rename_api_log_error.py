from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0006_api_log"),
    ]

    operations = [
        migrations.RenameField(
            model_name="apilog",
            old_name="error",
            new_name="error_message",
        ),
    ]
