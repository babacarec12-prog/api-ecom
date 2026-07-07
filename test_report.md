# Rapport des scénarios AI Commerce Assistant

- URL : `https://ai-commerce-api-babacare.onrender.com/api/commerce/`
- Run : `2eeb8f1422`
- Total : **151**
- PASS : **147**
- FAIL : **4**

## Résultats

| Statut | Section | Scénario | HTTP | Temps | Raison |
|---|---|---|---:|---:|---|
| ✅ PASS | 01 Messages invalides | '' | 200 | 717 ms | OK |
| ✅ PASS | 01 Messages invalides | ' ' | 200 | 333 ms | OK |
| ✅ PASS | 01 Messages invalides | '😊' | 200 | 3969 ms | OK |
| ✅ PASS | 01 Messages invalides | '👍👍👍' | 200 | 3250 ms | OK |
| ✅ PASS | 01 Messages invalides | '...' | 200 | 3071 ms | OK |
| ✅ PASS | 01 Messages invalides | '???' | 200 | 3467 ms | OK |
| ✅ PASS | 01 Messages invalides | 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' | 200 | 3561 ms | OK |
| ✅ PASS | 01 Messages invalides | '!@#$%' | 200 | 3810 ms | OK |
| ✅ PASS | 01 Messages invalides | '[MEDIA_SANS_TEXTE]' | 200 | 344 ms | OK |
| ✅ PASS | 01 Messages invalides | '[MESSAGE_VIDE]' | 200 | 334 ms | OK |
| ✅ PASS | 02 Messages courts | '2' | 200 | 3400 ms | OK |
| ✅ PASS | 02 Messages courts | 'oui' | 200 | 2897 ms | OK |
| ✅ PASS | 02 Messages courts | 'non' | 200 | 3237 ms | OK |
| ✅ PASS | 02 Messages courts | 'ok' | 200 | 3260 ms | OK |
| ✅ PASS | 02 Messages courts | 'hp' | 200 | 3428 ms | OK |
| ✅ PASS | 02 Messages courts | 'a' | 200 | 3713 ms | OK |
| ✅ PASS | 02 Messages courts | '1 2 3' | 200 | 4173 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'dama bëgg sa truc' | 200 | 3649 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'waw je prend' | 200 | 3915 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'déedéet laisse tomber' | 200 | 6593 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'bi ana mon colis' | 200 | 4241 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'lii bakh na combien' | 200 | 3187 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'man dina commande' | 200 | 3966 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'yow vous livrez ci dakar?' | 200 | 3553 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'c tro cher' | 200 | 4217 ms | OK |
| ✅ PASS | 03 Argot sénégalais | '2 bissap' | 200 | 4467 ms | OK |
| ✅ PASS | 03 Argot sénégalais | 'je vé sa en rouge' | 200 | 3590 ms | OK |
| ✅ PASS | 04 Fautes | 'montre moi les produit' | 200 | 3468 ms | OK |
| ✅ PASS | 04 Fautes | 'je veux comander' | 200 | 3539 ms | OK |
| ✅ PASS | 04 Fautes | 'cest combien la livraison' | 200 | 3635 ms | OK |
| ✅ PASS | 04 Fautes | 'anuler ma commande' | 200 | 3892 ms | OK |
| ✅ PASS | 04 Fautes | 'je veu voir mon panier' | 200 | 3908 ms | OK |
| ✅ PASS | 04 Fautes | 'ajoute 2 de sa' | 200 | 4053 ms | OK |
| ✅ PASS | 05 Hors sujet | 'quelle heure est-il' | 200 | 4201 ms | OK |
| ✅ PASS | 05 Hors sujet | 'tu connais Dakar?' | 200 | 4837 ms | OK |
| ✅ PASS | 05 Hors sujet | 'raconte moi une blague' | 200 | 5354 ms | OK |
| ✅ PASS | 05 Hors sujet | "c'est quoi ton nom" | 200 | 5672 ms | OK |
| ✅ PASS | 05 Hors sujet | 'tu es une IA?' | 200 | 4431 ms | OK |
| ✅ PASS | 05 Hors sujet | 'bonjour comment tu vas' | 200 | 3541 ms | OK |
| ✅ PASS | 05 Hors sujet | 'météo à Dakar' | 200 | 4455 ms | OK |
| ✅ PASS | 06 Abus | 'vous êtes nuls' | 200 | 3561 ms | OK |
| ✅ PASS | 06 Abus | "c'est une arnaque" | 200 | 5132 ms | OK |
| ✅ PASS | 06 Abus | 'idiot' | 200 | 3982 ms | OK |
| ✅ PASS | 06 Abus | 'HELP HELP HELP' | 200 | 3770 ms | OK |
| ✅ PASS | 06 Abus | spam même message x5 | 200 | 4668 ms | OK |
| ✅ PASS | 07 Recherche produits | query='' | 400 | 228 ms | OK |
| ✅ PASS | 07 Recherche produits | query='bissap' | 200 | 376 ms | OK |
| ✅ PASS | 07 Recherche produits | query='hp' | 200 | 248 ms | OK |
| ✅ PASS | 07 Recherche produits | query='nike air max 42' | 200 | 229 ms | OK |
| ✅ PASS | 07 Recherche produits | query='produit inexistant xyz' | 200 | 225 ms | OK |
| ✅ PASS | 07 Recherche produits | query='@#$%' | 200 | 283 ms | OK |
| ✅ PASS | 07 Recherche produits | query='xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' | 200 | 238 ms | OK |
| ✅ PASS | 07 Recherche produits | catalogue complet | 200 | 390 ms | OK |
| ✅ PASS | 08 Détails produit | product_id valide | 200 | 332 ms | OK |
| ✅ PASS | 08 Détails produit | product_id inexistant | 404 | 224 ms | OK |
| ✅ PASS | 08 Détails produit | product_id vide | 400 | 227 ms | OK |
| ✅ PASS | 08 Détails produit | product_id null | 400 | 229 ms | OK |
| ✅ PASS | 09 Variantes | produit sans variante | 404 | 232 ms | OK |
| ✅ PASS | 09 Variantes | variante inexistante | 404 | 235 ms | OK |
| ✅ PASS | 09 Variantes | product_id manquant | 400 | 232 ms | OK |
| ✅ PASS | 10 Sélection | save liste | 200 | 403 ms | OK |
| ✅ PASS | 10 Sélection | position 1 | 200 | 256 ms | OK |
| ✅ PASS | 10 Sélection | dernière position | 200 | 272 ms | OK |
| ✅ PASS | 10 Sélection | position 0 | 404 | 219 ms | OK |
| ✅ PASS | 10 Sélection | position 99 | 404 | 257 ms | OK |
| ✅ PASS | 10 Sélection | position -1 | 404 | 322 ms | OK |
| ✅ PASS | 10 Sélection | sans liste | 404 | 241 ms | OK |
| ✅ PASS | 11 Ajout panier | quantité 1 | 200 | 382 ms | OK |
| ✅ PASS | 11 Ajout panier | quantité 5 | 200 | 283 ms | OK |
| ✅ PASS | 11 Ajout panier | même produit cumul | 200 | 259 ms | OK |
| ✅ PASS | 11 Ajout panier | quantité 0 | 400 | 286 ms | OK |
| ✅ PASS | 11 Ajout panier | quantité -1 | 400 | 201 ms | OK |
| ✅ PASS | 11 Ajout panier | product_id manquant | 400 | 622 ms | OK |
| ✅ PASS | 11 Ajout panier | price manquant | 400 | 203 ms | OK |
| ✅ PASS | 11 Ajout panier | product_name manquant | 400 | 219 ms | OK |
| ✅ PASS | 12 Vue panier | panier plein | 200 | 242 ms | OK |
| ✅ PASS | 12 Vue panier | panier vide | 200 | 220 ms | OK |
| ✅ PASS | 12 Vue panier | user inconnu | 200 | 219 ms | OK |
| ✅ PASS | 13 Modification panier | retire inexistant | 404 | 349 ms | OK |
| ✅ PASS | 13 Modification panier | quantité 3 | 200 | 257 ms | OK |
| ✅ PASS | 13 Modification panier | quantité 0 retire | 200 | 439 ms | OK |
| ✅ PASS | 13 Modification panier | quantité négative après retrait | 404 | 232 ms | OK |
| ✅ PASS | 13 Modification panier | clear plein | 200 | 326 ms | OK |
| ✅ PASS | 13 Modification panier | cart_clear | 200 | 310 ms | OK |
| ✅ PASS | 13 Modification panier | cart_clear déjà vide | 200 | 320 ms | OK |
| ✅ PASS | 14 États | user inconnu browsing | 200 | 257 ms | OK |
| ✅ PASS | 14 États | set browsing | 200 | 223 ms | OK |
| ✅ PASS | 14 États | set selecting | 200 | 236 ms | OK |
| ✅ PASS | 14 États | set cart_review | 200 | 239 ms | OK |
| ✅ PASS | 14 États | set confirming | 200 | 234 ms | OK |
| ✅ PASS | 14 États | set ordering | 200 | 222 ms | OK |
| ✅ PASS | 14 États | set payment_pending | 200 | 314 ms | OK |
| ✅ PASS | 14 États | set completed | 200 | 246 ms | OK |
| ✅ PASS | 14 États | set human_takeover | 200 | 223 ms | OK |
| ✅ PASS | 14 États | état invalide | 400 | 219 ms | OK |
| ✅ PASS | 14 États | revert avec historique | 200 | 226 ms | OK |
| ✅ PASS | 14 États | revert sans historique | 200 | 1316 ms | OK |
| ✅ PASS | 15 Création commande | panier vide | 409 | 300 ms | OK |
| ✅ PASS | 15 Création commande | ajout fixture | 200 | 367 ms | OK |
| ✅ PASS | 15 Création commande | state browsing | 409 | 315 ms | OK |
| ✅ PASS | 15 Création commande | state confirming | 200 | 303 ms | OK |
| ✅ PASS | 15 Création commande | création valide | 200 | 467 ms | OK |
| ✅ PASS | 15 Création commande | idempotence | 200 | 236 ms | OK |
| ✅ PASS | 16-19 Commande Woo | statut order_id manquant | 400 | 527 ms | OK |
| ✅ PASS | 16-19 Commande Woo | statut inexistant | 500 | 238 ms | OK |
| ✅ PASS | 16-19 Commande Woo | annulation order_id manquant | 400 | 225 ms | OK |
| ✅ PASS | 16-19 Commande Woo | annulation mauvais user | 404 | 239 ms | OK |
| ✅ PASS | 16-19 Commande Woo | update mauvais user | 404 | 210 ms | OK |
| ✅ PASS | 16-19 Commande Woo | tracking mauvais user | 404 | 234 ms | OK |
| ✅ PASS | 20 Paiement | sans order_id | 400 | 198 ms | OK |
| ✅ PASS | 20 Paiement | order fictif | 404 | 354 ms | OK |
| ✅ PASS | 20 Paiement | amount 0 | 400 | 251 ms | OK |
| ✅ PASS | 20 Paiement | amount -1 | 400 | 227 ms | OK |
| ❌ FAIL | 20 Paiement | paiement valide | 500 | 312 ms | success=true attendu; HTTP=500; réponse={"success": false, "error": "La configuration PayTech est incomplète.", "data": {}} |
| ❌ FAIL | 20 Paiement | paiement idempotent | 500 | 315 ms | success=true attendu; HTTP=500; réponse={"success": false, "error": "La configuration PayTech est incomplète.", "data": {}} |
| ✅ PASS | 21 Transfert humain | sans raison | 200 | 1131 ms | OK |
| ✅ PASS | 21 Transfert humain | status actif | 200 | 229 ms | OK |
| ✅ PASS | 21 Transfert humain | bot suspendu | 200 | 252 ms | OK |
| ✅ PASS | 21 Transfert humain | reprise browsing | 200 | 229 ms | OK |
| ✅ PASS | 21 Transfert humain | status inconnu | 200 | 269 ms | OK |
| ✅ PASS | 21 Transfert humain | raison fournie | 200 | 427 ms | OK |
| ✅ PASS | 22-23 Remboursement et coupon | refund mauvais user | 404 | 258 ms | OK |
| ✅ PASS | 22-23 Remboursement et coupon | coupon vide | 400 | 320 ms | OK |
| ✅ PASS | 22-23 Remboursement et coupon | coupon invalide | 500 | 1293 ms | OK |
| ✅ PASS | 24 Politiques | delivery | 200 | 246 ms | OK |
| ✅ PASS | 24 Politiques | returns | 200 | 362 ms | OK |
| ✅ PASS | 24 Politiques | refund | 200 | 219 ms | OK |
| ✅ PASS | 24 Politiques | type inconnu | 400 | 210 ms | OK |
| ✅ PASS | 24 Politiques | type manquant | 400 | 344 ms | OK |
| ✅ PASS | 25-30 Parcours complets | normal 1: montre les produits | 200 | 2482 ms | OK |
| ✅ PASS | 25-30 Parcours complets | normal 2: je prends le 1 | 200 | 3469 ms | OK |
| ✅ PASS | 25-30 Parcours complets | normal 3: mon panier | 200 | 4444 ms | OK |
| ✅ PASS | 25-30 Parcours complets | normal 4: commander | 200 | 3717 ms | OK |
| ❌ FAIL | 25-30 Parcours complets | normal 5: oui | 200 | 3932 ms | commande ou lien PayTech absent du dernier tour |
| ✅ PASS | 25-30 Parcours complets | correction: montre les produits | 200 | 3587 ms | OK |
| ✅ PASS | 25-30 Parcours complets | correction: je prends le 1 | 200 | 3817 ms | OK |
| ✅ PASS | 25-30 Parcours complets | correction: laisse tomber | 200 | 3896 ms | OK |
| ✅ PASS | 25-30 Parcours complets | correction: montre les produits | 200 | 3422 ms | OK |
| ✅ PASS | 25-30 Parcours complets | transfert: montre les produits | 200 | 3609 ms | OK |
| ✅ PASS | 25-30 Parcours complets | transfert: je veux parler à quelqu'un | 200 | 6305 ms | OK |
| ✅ PASS | 25-30 Parcours complets | transfert: bonjour | 200 | 347 ms | OK |
| ✅ PASS | 31 Sécurité | sans token | 401 | 141 ms | OK |
| ✅ PASS | 31 Sécurité | mauvais token | 401 | 161 ms | OK |
| ✅ PASS | 31 Sécurité | action inconnue | 400 | 691 ms | OK |
| ❌ FAIL | 31 Sécurité | injection SQL neutralisée | 403 | 583 ms | success=true attendu; HTTP=403; réponse={"_invalid_json": "<!DOCTYPE html>\n<html lang=\"en\">\n  <head>\n    <meta charset=\"utf-8\" />\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n    <title>Blocked</title>\n    <style>@font-face {\n  font-family: \"Roobert\";\n  font-weight: 500;\n  font-style: normal;\n  font-stretch: normal;\n  src: url(\"data:font/woff2;base64,d09GMk9UVE8AAKewAAwAAAABa6QAAKdfAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAADYKmehqCHhuC4UocpRQGYACLBgE2AiQDkygEBgWFRwcgW8pqkQKZcr0u0nk2H+gc25rBL5C |
| ✅ PASS | 31 Sécurité | paramètres null | 400 | 256 ms | OK |
| ✅ PASS | 31 Sécurité | undefined omis | 400 | 243 ms | OK |
| ✅ PASS | 31 Sécurité | JSON malformé | 400 | 275 ms | OK |
| ✅ PASS | 32 Performance | temps < 3 secondes | 200 | 267 ms | OK |
| ✅ PASS | 32 Performance | 10 requêtes simultanées | 200 | 780 ms | OK |
| ✅ PASS | 31 Sécurité | 61 requêtes/minute → 429 | 429 | 9692 ms | OK |

## Échecs et corrections suggérées

### 1. 20 Paiement — paiement valide

- Cause probable : Les variables PAYTECH_API_KEY/PAYTECH_API_SECRET de Render sont absentes ou contiennent encore des placeholders.
- Correction suggérée : Renseigner les clés sandbox PayTech dans Render ; `views.py` ne peut pas fabriquer ces secrets.
- Détail : success=true attendu; HTTP=500; réponse={"success": false, "error": "La configuration PayTech est incomplète.", "data": {}}

### 2. 20 Paiement — paiement idempotent

- Cause probable : Les variables PAYTECH_API_KEY/PAYTECH_API_SECRET de Render sont absentes ou contiennent encore des placeholders.
- Correction suggérée : Renseigner les clés sandbox PayTech dans Render ; `views.py` ne peut pas fabriquer ces secrets.
- Détail : success=true attendu; HTTP=500; réponse={"success": false, "error": "La configuration PayTech est incomplète.", "data": {}}

### 3. 25-30 Parcours complets — normal 5: oui

- Cause probable : Clés PayTech absentes ou confirmation finale incomplète.
- Correction suggérée : Configurer les clés sandbox PayTech sur Render puis relancer ce scénario.
- Détail : commande ou lien PayTech absent du dernier tour

### 4. 31 Sécurité — injection SQL neutralisée

- Cause probable : Le pare-feu Render bloque la signature d'injection avant que la requête atteigne Django.
- Correction suggérée : Conserver ce blocage protecteur ou configurer Render pour renvoyer une erreur JSON uniforme.
- Détail : success=true attendu; HTTP=403; réponse={"_invalid_json": "<!DOCTYPE html>\n<html lang=\"en\">\n  <head>\n    <meta charset=\"utf-8\" />\n    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n    <title>Blocked</title>\n    <style>@font-face {\n  font-family: \"Roobert\";\n  font-weight: 500;\n  font-style: normal;\n  font-stretch: normal;\n  src: url(\"data:font/woff2;base64,d09GMk9UVE8AAKewAAwAAAABa6QAAKdfAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAADYKmehqCHhuC4UocpRQGYACLBgE2AiQDkygEBgWFRwcgW8pqkQKZcr0u0nk2H+gc25rBL5C
