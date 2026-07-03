"""Client Kimi limité à la classification d'intentions commerciales."""

import json
import re

import requests
from django.conf import settings

from .exceptions import CommerceError


SYSTEM_PROMPT = """Tu classes les messages d'une boutique WhatsApp sénégalaise.
Comprends le français, les fautes, l'argot et le wolof. La reformulation doit
toujours être en français. Retourne UNIQUEMENT un objet JSON valide, sans
Markdown.

Intentions autorisées : search_products, get_product, cart_add, cart_view,
cart_remove, cart_clear, cart_update_quantity, create_order, generate_payment,
get_order_status, cancel_order, request_refund, update_order, get_tracking,
validate_coupon, check_variant_stock, get_policy, transfer_to_human, other.

Règles :
- une demande de catalogue ou de produits est search_products ; query vaut "*"
  si aucune recherche précise n'est donnée ;
- un numéro seul après une liste est get_product avec position ;
- n'invente jamais un identifiant, prix, montant, code ou variante ;
- une discussion générale ou une salutation est other.

Schéma exact :
{"intention":"...","params":{"query":null,"position":null,"product_id":null,
"variant_id":null,"quantity":null,"order_id":null,"amount":null,
"reason":null,"code":null,"policy_type":null,"line_items":null},
"confidence":0.0,"langue_detectee":"français|wolof_mix|argot",
"reformulation":"obligatoirement en français",
"reponse_generale":"réponse courte en français uniquement si intention=other, sinon null"}
"""


class KimiClient:
    """Appelle l'API compatible OpenAI de Moonshot sans exposer sa clé."""

    def __init__(self):
        self.api_key = str(getattr(settings, "KIMI_API_KEY", "") or "").strip()
        self.model = str(
            getattr(settings, "KIMI_MODEL", "moonshot-v1-8k") or "moonshot-v1-8k"
        ).strip()
        self.timeout = int(getattr(settings, "KIMI_TIMEOUT", 15))
        if not self.api_key:
            raise CommerceError("Le service de compréhension n'est pas configuré.", 503)

    def classify(self, message, state):
        try:
            response = requests.post(
                "https://api.moonshot.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "max_tokens": 400,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                "État commerce : "
                                + json.dumps(state, ensure_ascii=False, default=str)
                                + "\nMessage client : "
                                + str(message)
                            ),
                        },
                    ],
                },
                timeout=(3, self.timeout),
            )
        except requests.RequestException as exc:
            raise CommerceError("Le service de compréhension est temporairement indisponible.", 502) from exc

        if not response.ok:
            raise CommerceError("Le service de compréhension a refusé la requête.", 502)
        try:
            body = response.json()
            raw = str(body["choices"][0]["message"]["content"] or "").strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise CommerceError("Le service de compréhension a renvoyé une réponse invalide.", 502) from exc

        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
        start, end = raw.find("{"), raw.rfind("}")
        try:
            parsed = json.loads(raw[start : end + 1] if start >= 0 and end > start else raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise CommerceError("Le service de compréhension a renvoyé une réponse invalide.", 502) from exc
        if not isinstance(parsed, dict):
            raise CommerceError("Le service de compréhension a renvoyé une réponse invalide.", 502)
        return parsed
