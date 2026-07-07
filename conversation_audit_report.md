# Audit conversationnel qualitatif

- Run : `28a24bb4bd`
- Dialogues : **8**
- Tours : **35**
- PASS : **35**
- FAIL : **0**
- Temps médian : **801 ms** (PASS, objectif majorité < 3 s)
- P95 : **3988 ms**

## Catalogue Et Pronoms

**✅ Client :** Salut

**Assistant :** Bonjour ! Comment puis-je vous aider ? 😊

Intention : `-` — 618 ms

**✅ Client :** montre-moi ce que vous avez

**Assistant :** Voici les produits disponibles :
1. Batterie externe 10 000 mAh - 22 000 FCFA
2. Bissap naturel 1 litre - 2 500 FCFA
3. Écouteurs Bluetooth Nomad - 18 500 FCFA
4. Sac à dos urbain Dakar - 15 000 FCFA
5. T-shirt coton Sénégal - 7 500 FCFA
Lequel vous intéresse ?

Intention : `search_products` — 1002 ms

**✅ Client :** le 2 m'intéresse

**Assistant :** Bissap naturel 1 litre - 2 500 FCFA
Je peux vous l'ajouter au panier si vous le souhaitez.

Intention : `get_product` — 7461 ms

**✅ Client :** ajoute-le

**Assistant :** Votre panier :
- 1 × Bissap naturel 1 litre : 2 500 FCFA
Total : 2 500 FCFA

Intention : `cart_add` — 2156 ms

**✅ Client :** et mets-en 3 au total

**Assistant :** Votre panier :
- 3 × Bissap naturel 1 litre : 7 500 FCFA
Total : 7 500 FCFA

Intention : `cart_update_quantity` — 458 ms

**✅ Client :** ça fait combien maintenant ?

**Assistant :** Votre panier :
- 3 × Bissap naturel 1 litre : 7 500 FCFA
Total : 7 500 FCFA

Intention : `cart_view` — 425 ms

## Achat Direct Naturel

**✅ Client :** je cherche du bissap

**Assistant :** Voici les produits disponibles :
1. Bissap naturel 1 litre - 2 500 FCFA
Lequel vous intéresse ?

Intention : `search_products` — 3988 ms

**✅ Client :** j'en prends deux

**Assistant :** Votre panier :
- 2 × Bissap naturel 1 litre : 5 000 FCFA
Total : 5 000 FCFA

Intention : `cart_add` — 689 ms

**✅ Client :** je veux commander

**Assistant :** Votre panier :
- 2 × Bissap naturel 1 litre : 5 000 FCFA
Total : 5 000 FCFA
Voulez-vous confirmer et créer la commande ?

Intention : `create_order` — 758 ms

**✅ Client :** attends, pas encore

**Assistant :** L'action en attente a été annulée.

Intention : `cancel_pending_action` — 3357 ms

**✅ Client :** montre mon panier

**Assistant :** Votre panier :
- 2 × Bissap naturel 1 litre : 5 000 FCFA
Total : 5 000 FCFA

Intention : `cart_view` — 443 ms

## Correction De Choix

**✅ Client :** affiche les produits

**Assistant :** Voici les produits disponibles :
1. Batterie externe 10 000 mAh - 22 000 FCFA
2. Bissap naturel 1 litre - 2 500 FCFA
3. Écouteurs Bluetooth Nomad - 18 500 FCFA
4. Sac à dos urbain Dakar - 15 000 FCFA
5. T-shirt coton Sénégal - 7 500 FCFA
Lequel vous intéresse ?

Intention : `search_products` — 592 ms

**✅ Client :** je prends le premier

**Assistant :** Votre panier :
- 1 × Batterie externe 10 000 mAh : 22 000 FCFA
Total : 22 000 FCFA

Intention : `cart_add` — 1551 ms

**✅ Client :** non enlève-le finalement

**Assistant :** Votre panier est vide.

Intention : `cart_remove` — 3495 ms

**✅ Client :** je préfère le bissap

**Assistant :** Bissap naturel 1 litre - 2 500 FCFA
Je peux vous l'ajouter au panier si vous le souhaitez.

Intention : `get_product` — 480 ms

**✅ Client :** ajoutes-en 2

**Assistant :** Votre panier :
- 2 × Bissap naturel 1 litre : 5 000 FCFA
Total : 5 000 FCFA

Intention : `cart_add` — 519 ms

## Langage Senegalais

**✅ Client :** nanga def

**Assistant :** Bonjour ! Je vais bien, merci. Comment puis-je vous aider ?

Intention : `-` — 1560 ms

**✅ Client :** am nga bissap ?

**Assistant :** Voici les produits disponibles :
1. Bissap naturel 1 litre - 2 500 FCFA
Lequel vous intéresse ?

Intention : `search_products` — 769 ms

**✅ Client :** waw dama bëgg ñaar

**Assistant :** Votre panier :
- 1 × Bissap naturel 1 litre : 2 500 FCFA
Total : 2 500 FCFA

Intention : `cart_add` — 4242 ms

**✅ Client :** sama panier bi dafa am lan ?

**Assistant :** Votre panier :
- 1 × Bissap naturel 1 litre : 2 500 FCFA
Total : 2 500 FCFA

Intention : `cart_view` — 475 ms

## Fautes Et Messages Courts

**✅ Client :** vs avé koi kom produit

**Assistant :** Voici les produits disponibles :
1. Batterie externe 10 000 mAh - 22 000 FCFA
2. Bissap naturel 1 litre - 2 500 FCFA
3. Écouteurs Bluetooth Nomad - 18 500 FCFA
4. Sac à dos urbain Dakar - 15 000 FCFA
5. T-shirt coton Sénégal - 7 500 FCFA
Lequel vous intéresse ?

Intention : `search_products` — 1808 ms

**✅ Client :** 3

**Assistant :** Écouteurs Bluetooth Nomad - 18 500 FCFA
Je peux vous l'ajouter au panier si vous le souhaitez.

Intention : `get_product` — 1460 ms

**✅ Client :** pren le

**Assistant :** Votre panier :
- 1 × Écouteurs Bluetooth Nomad : 18 500 FCFA
Total : 18 500 FCFA

Intention : `cart_add` — 512 ms

**✅ Client :** panier

**Assistant :** Votre panier :
- 1 × Écouteurs Bluetooth Nomad : 18 500 FCFA
Total : 18 500 FCFA

Intention : `cart_view` — 1905 ms

## Politiques Et Hors Sujet

**✅ Client :** vous livrez à Dakar ?

**Assistant :** Livraison sous 3 à 5 jours ouvrés. Les frais et le délai exact sont confirmés selon la zone de livraison au Sénégal.

Intention : `get_policy` — 848 ms

**✅ Client :** et les retours ça marche comment ?

**Assistant :** Retours acceptés sous 14 jours pour un produit non utilisé, complet et dans son emballage d'origine.

Intention : `get_policy` — 388 ms

**✅ Client :** raconte-moi une blague

**Assistant :** Pourquoi le panier était-il content ? Parce qu’il était bien rempli ! 😊

Intention : `other` — 1375 ms

**✅ Client :** bon revenons aux produits, vous avez du bissap ?

**Assistant :** Voici les produits disponibles :
1. Batterie externe 10 000 mAh - 22 000 FCFA
2. Bissap naturel 1 litre - 2 500 FCFA
3. Écouteurs Bluetooth Nomad - 18 500 FCFA
4. Sac à dos urbain Dakar - 15 000 FCFA
5. T-shirt coton Sénégal - 7 500 FCFA
Lequel vous intéresse ?

Intention : `search_products` — 578 ms

## Confirmation Contextuelle

**✅ Client :** montre les produits

**Assistant :** Voici les produits disponibles :
1. Batterie externe 10 000 mAh - 22 000 FCFA
2. Bissap naturel 1 litre - 2 500 FCFA
3. Écouteurs Bluetooth Nomad - 18 500 FCFA
4. Sac à dos urbain Dakar - 15 000 FCFA
5. T-shirt coton Sénégal - 7 500 FCFA
Lequel vous intéresse ?

Intention : `search_products` — 834 ms

**✅ Client :** je prends le 2

**Assistant :** Votre panier :
- 1 × Bissap naturel 1 litre : 2 500 FCFA
Total : 2 500 FCFA

Intention : `cart_add` — 1894 ms

**✅ Client :** commander

**Assistant :** Votre panier :
- 1 × Bissap naturel 1 litre : 2 500 FCFA
Total : 2 500 FCFA
Voulez-vous confirmer et créer la commande ?

Intention : `create_order` — 928 ms

**✅ Client :** non laisse tomber

**Assistant :** L'action en attente a été annulée.

Intention : `cancel_pending_action` — 361 ms

**✅ Client :** mon panier

**Assistant :** Votre panier :
- 1 × Bissap naturel 1 litre : 2 500 FCFA
Total : 2 500 FCFA

Intention : `cart_view` — 477 ms

## Transfert Humain

**✅ Client :** je veux parler à un conseiller

**Assistant :** Votre demande a été transmise à un conseiller.

Intention : `transfer_to_human` — 466 ms

**✅ Client :** vous êtes là ?

**Assistant :** [SILENCE]

Intention : `-` — 381 ms
