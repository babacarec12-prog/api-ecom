"""Client Kimi limité à la classification d'intentions commerciales."""

import json
import re

import requests
from django.conf import settings

from .exceptions import CommerceError


SYSTEM_PROMPT = """Tu comprends le prochain message d'un client d'une boutique
WhatsApp sénégalaise. Tu reçois l'historique récent, l'état transactionnel, le
panier, la sélection et la commande active. Interprète les pronoms et réponses
courtes à partir de ce contexte. Comprends le français, les fautes, l'argot et
le wolof mélangé. Retourne UNIQUEMENT un objet JSON valide, sans Markdown.

Intentions autorisées : search_products, get_product, cart_add, cart_view,
cart_remove, cart_clear, cart_update_quantity, create_order, generate_payment,
get_order_status, cancel_order, request_refund, update_order, get_tracking,
validate_coupon, check_variant_stock, get_policy, transfer_to_human, other.

Règles :
- une demande de catalogue ou de produits est search_products ; query vaut "*"
  si aucune recherche précise n'est donnée ;
- un nom de produit seul est search_products avec ce nom dans query ;
- « ajoute-le », « je le prends », « celui-là » utilisent le produit récemment
  sélectionné ; ne demande pas son identifiant ;
- un numéro seul après une liste est get_product avec position ; une volonté
  d'achat accompagnée du numéro est cart_add avec position ;
- « je valide », « c'est bon », « tout est correct » se comprennent selon
  pending_action ; ne les transforme pas en nouvelle recherche ;
- payer ou demander le lien utilise la commande active sans inventer order_id ;
- n'invente jamais un identifiant, prix, montant, code ou variante ;
- une discussion générale ou une salutation est other.
- reponse_generale vouvoie toujours le client et reste cohérente avec le ton
  professionnel d'une boutique ; n'utilise jamais « tu », « te » ou « ton ».

Exemples :
- contexte: liste affichée, message: « 2 » => get_product, position=2
- contexte: liste affichée, message exprimant l'achat du numéro 2 => cart_add,
  position=2
- contexte: produit Batterie sélectionné, message: « ajoute-la » => cart_add
- contexte: panier non vide, message demandant de finaliser => create_order
- contexte: pending_action=create_order, message: « tout est correct » => other
  (Django appliquera la confirmation déterministe)
- contexte: commande active, message: « je dois payer ? » => generate_payment

Schéma exact :
{"intention":"...","params":{"query":null,"position":null,"product_id":null,
"variant_id":null,"quantity":null,"order_id":null,"amount":null,
"reason":null,"code":null,"policy_type":null,"line_items":null},
"confidence":0.0,"langue_detectee":"français|wolof_mix|argot",
"reformulation":"obligatoirement en français",
"reponse_generale":"réponse courte en français uniquement si intention=other, sinon null"}
"""

FORMULATION_PROMPT = """Écris uniquement le prochain message WhatsApp de la
boutique en français simple et naturel. Une réponse normale fait une ou deux
phrases courtes. Ne salue pas au milieu d'une conversation. Interdictions :
« Cher client », « Bien sûr », « Je suis ravi », « N'hésitez pas », « Veuillez
patienter », « Merci de votre compréhension ». La réponse sûre et les données
métier sont la seule vérité : conserve exactement produit, prix, quantité,
total, référence et lien. N'invente rien, n'ajoute aucun conseil commercial et
ne dicte jamais au client une formule de réponse. Une liste peut être plus
longue. Vouvoie toujours le client. Sans Markdown. Retourne uniquement le
message final.
"""


class KimiClient:
    """Appelle l'API compatible OpenAI de Moonshot sans exposer sa clé."""

    def __init__(self):
        self.api_key = str(getattr(settings, "KIMI_API_KEY", "") or "").strip()
        self.model = str(
            getattr(settings, "KIMI_MODEL", "moonshot-v1-128k") or "moonshot-v1-128k"
        ).strip()
        self.timeout = int(getattr(settings, "KIMI_TIMEOUT", 15))
        if not self.api_key:
            raise CommerceError("Le service de compréhension n'est pas configuré.", 503)

    def _completion(self, messages, *, temperature, max_tokens):
        try:
            response = requests.post(
                "https://api.moonshot.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": messages,
                },
                timeout=(3, self.timeout),
            )
        except requests.RequestException as exc:
            raise CommerceError("Le service Kimi est temporairement indisponible.", 502) from exc

        if not response.ok:
            raise CommerceError("Le service Kimi a refusé la requête.", 502)
        try:
            body = response.json()
            return str(body["choices"][0]["message"]["content"] or "").strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise CommerceError("Le service Kimi a renvoyé une réponse invalide.", 502) from exc

    def classify(self, message, state):
        raw = self._completion(
            [
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
            temperature=0.1,
            max_tokens=400,
        )

        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
        start, end = raw.find("{"), raw.rfind("}")
        try:
            parsed = json.loads(raw[start : end + 1] if start >= 0 and end > start else raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise CommerceError("Le service de compréhension a renvoyé une réponse invalide.", 502) from exc
        if not isinstance(parsed, dict):
            raise CommerceError("Le service de compréhension a renvoyé une réponse invalide.", 502)
        return parsed

    def formulate(self, message, analysis, commerce_result, safe_answer):
        messages = [
            {"role": "system", "content": FORMULATION_PROMPT},
            {
                "role": "user",
                "content": (
                    "Message client : " + str(message)
                    + "\nIntention : " + json.dumps(analysis, ensure_ascii=False, default=str)
                    + "\nRésultat métier : " + json.dumps(commerce_result, ensure_ascii=False, default=str)
                    + "\nRéponse sûre à reformuler : " + str(safe_answer)
                ),
            },
        ]
        raw = self._completion(
            messages,
            temperature=0.3,
            max_tokens=350,
        )
        answer = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE)
        answer = answer.replace("**", "").strip()
        if not answer:
            raise CommerceError("Kimi n'a produit aucune réponse.", 502)
        forbidden_wolof = re.search(
            r"\b(nanga|dama|sama|danga|waaw|waw|jerejef|inshallah|deedeet)\b",
            answer.casefold(),
        )
        if forbidden_wolof:
            raise CommerceError("Kimi n'a pas répondu strictement en français.", 502)
        forbidden_english = re.search(
            r"\b(awesome|great|hello|thanks|thank you|must-have|sure)\b",
            answer.casefold(),
        )
        if forbidden_english:
            raise CommerceError("Kimi n'a pas répondu strictement en français.", 502)
        if re.search(
            r"\b(cher client|bien sûr|je suis ravi|n'hésitez pas|"
            r"merci de votre compréhension|assistance supplémentaire|"
            r"veuillez patienter)\b",
            answer.casefold(),
        ):
            raise CommerceError("Kimi a produit une formulation mécanique.", 502)
        if len(answer) > len(str(safe_answer)) * 2 + 120:
            raise CommerceError("Kimi a produit une réponse inutilement longue.", 502)
        safe_numbers = re.findall(r"\d+", str(safe_answer))
        answer_numbers = re.findall(r"\d+", answer)
        if any(number not in answer_numbers for number in safe_numbers):
            raise CommerceError("Kimi a modifié une donnée commerciale.", 502)
        return answer
