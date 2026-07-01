# n8n — retry et fallback Qwen gratuit

Le fichier `n8n_ai_ecom_corrige.json` contient déjà les réglages ci-dessous. Ces étapes servent à les vérifier dans l’interface n8n après import.

## 1. Sauvegarder avant modification

1. Ouvrir le workflow actuel.
2. Menu `…` en haut à droite → **Download**.
3. Importer ensuite `n8n_ai_ecom_corrige.json` comme une nouvelle version de test.
4. Ne publier la nouvelle version qu’après les tests.

## 2. Configurer deux tentatives Qwen au total

1. Ouvrir le nœud **Agent IA Commerce**.
2. Aller dans l’onglet **Settings**.
3. Activer **Retry On Fail**.
4. Régler **Max Tries** sur `2`.
5. Régler **Wait Between Tries** sur `3000 ms`.
6. Régler **On Error** sur **Continue (using error output)**.

Dans l’export JSON, cela correspond à :

```json
{
  "retryOnFail": true,
  "maxTries": 2,
  "waitBetweenTries": 3000,
  "onError": "continueErrorOutput",
  "alwaysOutputData": false
}
```

`Max Tries: 2` signifie une tentative initiale et une seconde tentative, pas deux retries supplémentaires.

Ne pas activer un second retry sur le sous-nœud **Qwen via OpenRouter** : deux couches de retry pourraient produire quatre appels et aggraver la limite de débit.

## 3. Ajouter le fallback sans nouvel appel IA

1. Ajouter un nœud **Code** nommé `Fallback Qwen`.
2. Coller :

```javascript
return [{
  json: {
    output: 'Un instant, je rencontre un souci technique. Merci de réessayer dans quelques instants ou demandez un conseiller.',
    technicalFallback: true
  }
}];
```

3. Relier la **sortie d’erreur** de `Agent IA Commerce` à `Fallback Qwen`.
4. Relier `Fallback Qwen` à `Préparer réponse OpenWA`.
5. Conserver la sortie normale de l’Agent vers `Préparer réponse OpenWA`.

Ne jamais reconnecter le fallback à l’Agent : cela créerait une boucle et consommerait davantage de requêtes OpenRouter.

## 4. Gérer les messages non textuels sans planter

Le nœud `Normaliser message entrant`, placé juste après le Webhook :

- ignore les messages `fromMe` pour empêcher une boucle du bot ;
- transforme une image/document sans texte en `[MEDIA_SANS_TEXTE]` ;
- transforme un message réellement vide en `[MESSAGE_VIDE]`.

Le prompt doit répondre à `[MEDIA_SANS_TEXTE]` :

> Je peux traiter uniquement les messages texte pour le moment. Pouvez-vous décrire votre demande par écrit ?

Les messages vocaux ne sont pas proposés dans ce MVP.

## 5. Installer le prompt v2

1. Ouvrir `Agent IA Commerce` → **Options** → **System Message**.
2. Remplacer entièrement l’ancien contenu par celui de `system-prompt-v2.txt`.
3. Vérifier qu’un seul champ **System Message** existe.
4. Conserver la mémoire Supabase connectée.

Le prompt demande à Qwen de réutiliser les informations déjà connues, de rester concis, de changer de langue avec le client et de transférer au lieu d’halluciner.

## 6. Vérifier le transfert humain

L’actuel outil `transfer_to_human` doit recevoir ces quatre valeurs :

- `customer_id` → `{{ $('Extraire message OpenWA').first().json.userId }}`
- `customer_message` → `{{ $('Extraire message OpenWA').first().json.chatInput }}`
- `reason` → motif produit par l’agent ou `Demande explicite du client`
- `session_id` → `{{ $('Extraire message OpenWA').first().json.sessionId }}`

Pour une demande explicite contenant `humain`, `conseiller` ou `agent`, une future amélioration doit router directement vers le sous-workflow sans dépendre de Qwen. Après transfert, stocker `human_mode=true` dans Supabase afin d’empêcher le bot de continuer à répondre.

## 7. Scénarios de test

Tester au minimum :

1. Message normal : Qwen répond une seule fois.
2. Timeout simulé : une seconde tentative est visible, puis le fallback est envoyé.
3. Erreur 429 : le workflow ne s’arrête pas avant le nœud d’envoi.
4. Image seule : réponse texte de limitation.
5. Emoji seul : demande de précision.
6. `Je veux parler à un humain` : transfert et accusé de réception.
7. Même question trois fois : proposition de transfert, sans boucle.
8. Réponse du bot : aucun nouveau déclenchement grâce à `fromMe`.

## 8. Publication

1. Cliquer **Save**.
2. Cliquer **Publish** — dans n8n 2.x, cela active la version de production.
3. Configurer OpenWA avec l’URL `/webhook/ai-commerce-openwa-v2`, jamais `/webhook-test/`.
4. Vérifier l’onglet **Executions** avec un vrai message WhatsApp.
