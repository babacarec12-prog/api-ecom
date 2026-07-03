# Journal des changements

## API robuste et workflow final

### `commerce/views.py`

- Uniformisation des erreurs métier sous la forme `{"success": false, "error": "...", "data": {}}` afin que n8n puisse toujours les interpréter.
- Une action inconnue renvoie maintenant un succès informatif avec `Action non reconnue` et la liste triée des actions disponibles, au lieu de lever une erreur.
- Les paramètres obligatoires absents renvoient `Paramètre manquant: nom_du_param`, ce qui évite les `KeyError` opaques.
- Les exceptions inattendues sont journalisées côté serveur et renvoient `Erreur inattendue, réessayez` sans réponse HTTP 500.
- Les erreurs de configuration, connexion ou JSON WooCommerce sont converties en `Boutique temporairement inaccessible`.
- `check_human_status` expose désormais `human_active` tout en conservant `human_takeover` pour la rétrocompatibilité.
- Chaque appel métier enregistre, sans bloquer la réponse principale, `user_id`, `action`, `success`, `error` et `duration_ms` dans la table Supabase `api_logs`.
- Les actions et parcours existants (`message_turn`, confirmations, catalogue en base, idempotence) sont conservés.

### Autres fichiers nécessaires

- `commerce/models.py` et la migration `0006_api_log.py` ajoutent le modèle/table `api_logs`.
- `commerce/exception_handler.py` applique le même contrat d’erreur aux erreurs produites par Django REST Framework.
- `commerce/woo_client.py` accepte les variables historiques `WOO_STORE_URL`, `WOO_CONSUMER_KEY`, `WOO_CONSUMER_SECRET` ainsi que les alias `WOO_URL`, `WOO_KEY`, `WOO_SECRET`.
- `.env.example` contient tous les placeholders demandés, sans aucun secret réel.
- `workflow-final.json` fournit le flux OpenWA → Kimi → Django → Kimi → Supabase → OpenWA avec clarification, prise en charge humaine et fallback global.

### Pourquoi

Ces changements empêchent une entrée inattendue de devenir une panne visible dans WhatsApp, rendent les erreurs exploitables par n8n et ajoutent une traçabilité opérationnelle sans réécrire l’architecture métier validée.
