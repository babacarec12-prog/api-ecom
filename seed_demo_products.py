"""Ajoute un catalogue fictif idempotent dans WooCommerce.

Les produits utilisent des SKU DEMO-AICA-* afin qu'une seconde exécution
mette à jour les mêmes fiches au lieu de créer des doublons.
"""

import argparse

from dotenv import load_dotenv

from commerce.woo_client import WooCommerceClient


PRODUCTS = [
    ("Bissap naturel 1 L", "Boissons", "2500", 30, "Boisson rafraîchissante à base de fleurs d’hibiscus."),
    ("Jus de gingembre 1 L", "Boissons", "2800", 24, "Jus de gingembre légèrement citronné, prêt à servir."),
    ("Café Touba premium 250 g", "Épicerie", "3500", 18, "Café sénégalais aromatisé au poivre de Guinée."),
    ("Miel naturel 500 g", "Épicerie", "4500", 16, "Miel fictif de démonstration, doux et non pasteurisé."),
    ("Riz parfumé 5 kg", "Épicerie", "6500", 20, "Sac de riz parfumé adapté aux repas familiaux."),
    ("T-shirt Dakar essentiel", "Mode", "7500", 25, "T-shirt unisexe en coton avec motif Dakar minimaliste."),
    ("Sac cabas wax", "Mode", "12000", 12, "Sac cabas coloré en tissu wax, pratique au quotidien."),
    ("Sandales artisanales", "Mode", "15000", 10, "Sandales de démonstration au style artisanal contemporain."),
    ("Bougie parfumée Baobab", "Maison", "6000", 14, "Bougie décorative aux notes boisées, durée indicative de 35 heures."),
    ("Panier tressé décoratif", "Maison", "13500", 9, "Panier de rangement tressé pour salon ou chambre."),
    ("Coussin wax 45 × 45 cm", "Maison", "8500", 15, "Coussin décoratif déhoussable avec motif wax."),
    ("Savon noir naturel", "Beauté", "3000", 32, "Savon noir de démonstration pour une routine corps douce."),
    ("Huile de baobab 100 ml", "Beauté", "5500", 17, "Huile cosmétique nourrissante pour la peau et les cheveux."),
    ("Écouteurs Bluetooth Nomad", "Électronique", "18500", 11, "Écouteurs sans fil avec boîtier de recharge compact."),
    ("Batterie externe 10 000 mAh", "Électronique", "22000", 13, "Batterie portable USB-C pour les déplacements."),
]


def ensure_categories(client, names):
    categories = client._request("GET", "products/categories", params={"per_page": 100})
    by_name = {item.get("name", "").casefold(): item["id"] for item in categories}
    missing = [name for name in names if name.casefold() not in by_name]
    if missing:
        result = client._request(
            "POST",
            "products/categories/batch",
            json={"create": [{"name": name} for name in missing]},
        )
        for item in result.get("create", []):
            by_name[item["name"].casefold()] = item["id"]
    return {name: by_name[name.casefold()] for name in names}


def product_payload(index, product, category_id, status, with_image=True):
    name, _category, price, stock, description = product
    payload = {
        "name": name,
        "type": "simple",
        "status": status,
        "sku": f"DEMO-AICA-{index:03d}",
        "regular_price": price,
        "description": f"<p>{description}</p><p><em>Produit fictif pour démonstration AI Commerce Assistant.</em></p>",
        "short_description": description,
        "manage_stock": True,
        "stock_quantity": stock,
        "categories": [{"id": category_id}],
        "meta_data": [{"key": "ai_commerce_demo", "value": "true"}],
    }
    if with_image:
        payload["images"] = [
            {
                "src": f"https://placehold.co/800x800/png?text=Produit+Demo+{index:02d}",
                "alt": name,
            }
        ]
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", choices=("draft", "publish"), default="draft")
    args = parser.parse_args()

    load_dotenv()
    client = WooCommerceClient()
    category_ids = ensure_categories(client, sorted({p[1] for p in PRODUCTS}))
    existing_products = client._request(
        "GET", "products", params={"per_page": 100, "status": "any"}
    )
    existing_by_sku = {
        item.get("sku"): item for item in existing_products if item.get("sku")
    }

    create_payloads = []
    update_payloads = []
    for index, product in enumerate(PRODUCTS, start=1):
        payload = product_payload(
            index, product, category_ids[product[1]], args.status, with_image=False
        )
        existing = existing_by_sku.get(payload["sku"])
        if existing:
            payload["id"] = existing["id"]
            update_payloads.append(payload)
        else:
            create_payloads.append(payload)

    result = client._request(
        "POST",
        "products/batch",
        json={"create": create_payloads, "update": update_payloads},
    )
    saved = result.get("create", []) + result.get("update", [])
    for item in saved:
        print(f"{item['id']}: {item['name']} [{item['status']}]")

    print(
        f"Terminé : {len(result.get('create', []))} produit(s) créé(s), "
        f"{len(result.get('update', []))} mis à jour."
    )


if __name__ == "__main__":
    main()
