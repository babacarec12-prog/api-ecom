from django.db import migrations


DEFAULT_POLICIES = {
    "delivery": (
        "Livraison sous 3 à 5 jours ouvrés. Les frais et le délai exact sont "
        "confirmés selon la zone de livraison au Sénégal."
    ),
    "returns": (
        "Retours acceptés sous 14 jours pour un produit non utilisé, complet et "
        "dans son emballage d'origine."
    ),
    "refund": (
        "Après validation du retour, le remboursement est enregistré puis traité "
        "selon le moyen de paiement utilisé."
    ),
}


def correct_policies(apps, schema_editor):
    ShopPolicy = apps.get_model("commerce", "ShopPolicy")
    for policy_type, content in DEFAULT_POLICIES.items():
        ShopPolicy.objects.update_or_create(
            policy_type=policy_type,
            defaults={"content": content},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0003_conversation_pending_action"),
    ]

    operations = [
        migrations.RunPython(correct_policies, migrations.RunPython.noop),
    ]
