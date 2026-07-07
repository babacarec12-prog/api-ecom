"""Campagne de validation externe de l'API Render AI Commerce Assistant.

Le script n'utilise que des identifiants synthétiques préfixés ``scenario-``.
Il produit toujours ``test_report.md``, même lorsqu'une requête échoue.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


ROOT = Path(__file__).resolve().parent
API_URL = os.getenv("COMMERCE_TEST_URL", "https://ai-commerce-api-babacare.onrender.com/api/commerce/")
TIMEOUT = int(os.getenv("COMMERCE_TEST_TIMEOUT", "150"))


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


ENV = load_env()
TOKEN = os.getenv("N8N_API_TOKEN") or ENV.get("N8N_API_TOKEN", "")


@dataclass
class Result:
    section: str
    name: str
    passed: bool
    duration_ms: int
    status: int | None
    reason: str
    probable_cause: str = ""
    suggestion: str = ""


class Runner:
    def __init__(self) -> None:
        if not TOKEN:
            raise RuntimeError("N8N_API_TOKEN absent de .env")
        self.run_id = uuid.uuid4().hex[:10]
        self.results: list[Result] = []
        self.request_times: list[float] = []
        self.created_order_id: str | None = None
        self.created_order_amount: str | None = None
        self.product: dict[str, Any] | None = None
        self.products: list[dict[str, Any]] = []

    def user(self, suffix: str) -> str:
        return f"scenario-{self.run_id}-{suffix}"

    def _throttle(self) -> None:
        now = time.monotonic()
        self.request_times = [stamp for stamp in self.request_times if now - stamp < 61]
        if len(self.request_times) >= 45:
            wait = 61 - (now - self.request_times[0])
            if wait > 0:
                time.sleep(wait)
            now = time.monotonic()
            self.request_times = [stamp for stamp in self.request_times if now - stamp < 61]
        self.request_times.append(time.monotonic())

    def request(
        self,
        action: str,
        data: Any,
        *,
        token: str | None = TOKEN,
        raw_body: str | None = None,
        throttle: bool = True,
    ) -> tuple[int | None, dict[str, Any], int]:
        if throttle:
            self._throttle()
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-API-Token"] = token
        started = time.perf_counter()
        try:
            if raw_body is None:
                response = requests.post(
                    API_URL,
                    headers=headers,
                    json={"action": action, "data": data},
                    timeout=TIMEOUT,
                )
            else:
                response = requests.post(API_URL, headers=headers, data=raw_body, timeout=TIMEOUT)
            duration = int((time.perf_counter() - started) * 1000)
            try:
                payload = response.json()
            except ValueError:
                payload = {"_invalid_json": response.text[:500]}
            return response.status_code, payload, duration
        except requests.RequestException as exc:
            return None, {"_transport_error": str(exc)}, int((time.perf_counter() - started) * 1000)

    @staticmethod
    def uniform(payload: dict[str, Any]) -> bool:
        return set(("success", "data")).issubset(payload) and isinstance(payload.get("data"), dict)

    @staticmethod
    def no_forbidden(payload: dict[str, Any]) -> bool:
        text = json.dumps(payload, ensure_ascii=False).casefold()
        return "service indisponible" not in text

    def add(
        self,
        section: str,
        name: str,
        status: int | None,
        payload: dict[str, Any],
        duration: int,
        predicate: Callable[[int | None, dict[str, Any]], bool],
        reason: str,
        cause: str = "Contrat ou transition métier incorrecte.",
        suggestion: str = "Vérifier le handler, ses préconditions et le format uniforme de réponse.",
    ) -> dict[str, Any]:
        passed = bool(predicate(status, payload)) and self.no_forbidden(payload)
        actual_reason = "OK" if passed else f"{reason}; HTTP={status}; réponse={json.dumps(payload, ensure_ascii=False)[:500]}"
        self.results.append(Result(section, name, passed, duration, status, actual_reason, cause, suggestion))
        print(("✅ PASS" if passed else "❌ FAIL") + f" [{section}] {name} ({duration} ms)")
        return payload

    def expect_success(self, section: str, name: str, action: str, data: Any) -> dict[str, Any]:
        status, payload, duration = self.request(action, data)
        return self.add(
            section,
            name,
            status,
            payload,
            duration,
            lambda s, p: s == 200 and p.get("success") is True and self.uniform(p),
            "success=true attendu",
        )

    def expect_failure(self, section: str, name: str, action: str, data: Any) -> dict[str, Any]:
        status, payload, duration = self.request(action, data)
        return self.add(
            section,
            name,
            status,
            payload,
            duration,
            lambda s, p: s in {200, 400, 401, 404, 409, 422, 429, 500, 502, 503} and p.get("success") is False and self.uniform(p),
            "échec métier uniforme attendu",
        )

    def message(self, section: str, text: str, index: int) -> dict[str, Any]:
        user = self.user(f"msg-{index}")
        status, payload, duration = self.request(
            "message_turn",
            {
                "user_id": user,
                "session_key": user,
                "message_id": f"{self.run_id}-message-{index}",
                "message": text,
                "naturalize": False,
            },
        )
        return self.add(
            section,
            repr(text),
            status,
            payload,
            duration,
            lambda s, p: s == 200 and p.get("success") is True and self.uniform(p) and (
                p["data"].get("silent") is True or isinstance(p["data"].get("message"), str)
            ),
            "message_turn doit produire message ou silent=true",
            "Classification, mémoire ou formulation défaillante.",
            "Inspecter analysis, state, recent_messages et le fallback déterministe.",
        )

    def incoming_messages(self) -> None:
        groups = {
            "01 Messages invalides": ["", " ", "😊", "👍👍👍", "...", "???", "x" * 500, "!@#$%", "[MEDIA_SANS_TEXTE]", "[MESSAGE_VIDE]"],
            "02 Messages courts": ["2", "oui", "non", "ok", "hp", "a", "1 2 3"],
            "03 Argot sénégalais": ["dama bëgg sa truc", "waw je prend", "déedéet laisse tomber", "bi ana mon colis", "lii bakh na combien", "man dina commande", "yow vous livrez ci dakar?", "c tro cher", "2 bissap", "je vé sa en rouge"],
            "04 Fautes": ["montre moi les produit", "je veux comander", "cest combien la livraison", "anuler ma commande", "je veu voir mon panier", "ajoute 2 de sa"],
            "05 Hors sujet": ["quelle heure est-il", "tu connais Dakar?", "raconte moi une blague", "c'est quoi ton nom", "tu es une IA?", "bonjour comment tu vas", "météo à Dakar"],
            "06 Abus": ["vous êtes nuls", "c'est une arnaque", "idiot", "HELP HELP HELP"],
        }
        index = 0
        for section, messages in groups.items():
            for text in messages:
                index += 1
                self.message(section, text, index)

        spam_user = self.user("spam")
        first: dict[str, Any] | None = None
        all_ok = True
        total_duration = 0
        last_status: int | None = None
        for index in range(5):
            status, payload, duration = self.request(
                "message_turn",
                {"user_id": spam_user, "session_key": spam_user, "message_id": f"spam-{index}", "message": "HELP HELP HELP", "naturalize": False},
            )
            first = first or payload
            all_ok = all_ok and status == 200 and payload.get("success") is True
            total_duration += duration
            last_status = status
        self.add("06 Abus", "spam même message x5", last_status, first or {}, total_duration, lambda _s, _p: all_ok, "les cinq messages doivent être traités uniformément")

    def catalogue_and_selection(self) -> None:
        section = "07 Recherche produits"
        queries = ["", "bissap", "hp", "nike air max 42", "produit inexistant xyz", "@#$%", "x" * 200]
        for query in queries:
            expected_failure = query == ""
            payload = (self.expect_failure if expected_failure else self.expect_success)(section, f"query={query!r}", "search_products", {"query": query, "user_id": self.user("search")})
            if query == "" or payload.get("success") is not True:
                continue
            products = payload.get("data", {}).get("products") or []
            if query == "bissap" and products:
                self.product = products[0]

        all_products = self.expect_success(section, "catalogue complet", "search_products", {"query": "*", "user_id": self.user("catalogue"), "session_key": self.run_id})
        self.products = all_products.get("data", {}).get("products") or []
        if not self.product and self.products:
            self.product = self.products[0]

        section = "08 Détails produit"
        if self.product:
            self.expect_success(section, "product_id valide", "get_product", {"product_id": self.product["id"], "platform": "database"})
        self.expect_failure(section, "product_id inexistant", "get_product", {"product_id": "XYZ-INEXISTANT", "platform": "database"})
        self.expect_failure(section, "product_id vide", "get_product", {"product_id": "", "platform": "database"})
        self.expect_failure(section, "product_id null", "get_product", {"product_id": None, "platform": "database"})

        section = "09 Variantes"
        if self.product:
            variants = self.product.get("variantes") or []
            if variants:
                self.expect_success(section, "variante valide", "check_variant_stock", {"product_id": self.product["id"], "variant_id": variants[0]["id"], "platform": "database"})
            else:
                self.expect_failure(section, "produit sans variante", "check_variant_stock", {"product_id": self.product["id"], "variant_id": "NONE", "platform": "database"})
            self.expect_failure(section, "variante inexistante", "check_variant_stock", {"product_id": self.product["id"], "variant_id": "XYZ", "platform": "database"})
        self.expect_failure(section, "product_id manquant", "check_variant_stock", {"variant_id": "1", "platform": "database"})

        section = "10 Sélection"
        selection_user = self.user("selection")
        products = [
            {"position": index, "product_id": product["id"], "product_name": product.get("nom") or "Produit", "price": product.get("prix")}
            for index, product in enumerate(self.products[:5], start=1)
        ]
        if products:
            self.expect_success(section, "save liste", "save_selection_list", {"user_id": selection_user, "session_key": self.run_id, "products": products})
            self.expect_success(section, "position 1", "get_product_by_position", {"user_id": selection_user, "position": 1})
            self.expect_success(section, "dernière position", "get_product_by_position", {"user_id": selection_user, "position": len(products)})
        for position in (0, 99, -1):
            self.expect_failure(section, f"position {position}", "get_product_by_position", {"user_id": selection_user, "position": position})
        self.expect_failure(section, "sans liste", "get_product_by_position", {"user_id": self.user("no-selection"), "position": 1})

    def cart_and_state(self) -> None:
        if not self.product:
            return
        product_id = self.product["id"]
        product_name = self.product.get("nom") or "Produit"
        price = self.product.get("prix") or "1"
        user = self.user("cart")
        base = {"user_id": user, "product_id": product_id, "product_name": product_name, "price": price, "platform": "database"}
        section = "11 Ajout panier"
        self.expect_success(section, "quantité 1", "cart_add", {**base, "quantity": 1})
        self.expect_success(section, "quantité 5", "cart_add", {**base, "quantity": 5})
        self.expect_success(section, "même produit cumul", "cart_add", {**base, "quantity": 1})
        for quantity in (0, -1):
            self.expect_failure(section, f"quantité {quantity}", "cart_add", {**base, "quantity": quantity})
        self.expect_failure(section, "product_id manquant", "cart_add", {"user_id": user, "product_name": product_name, "quantity": 1, "price": price})
        self.expect_failure(section, "price manquant", "cart_add", {"user_id": user, "product_id": product_id, "product_name": product_name, "quantity": 1})
        self.expect_failure(section, "product_name manquant", "cart_add", {"user_id": user, "product_id": product_id, "quantity": 1, "price": price})

        section = "12 Vue panier"
        self.expect_success(section, "panier plein", "cart_view", {"user_id": user})
        self.expect_success(section, "panier vide", "cart_view", {"user_id": self.user("empty-cart")})
        self.expect_success(section, "user inconnu", "cart_view", {"user_id": self.user("unknown-cart")})

        section = "13 Modification panier"
        self.expect_failure(section, "retire inexistant", "cart_remove", {"user_id": user, "product_id": "XYZ"})
        self.expect_success(section, "quantité 3", "cart_update_quantity", {"user_id": user, "product_id": product_id, "quantity": 3})
        self.expect_success(section, "quantité 0 retire", "cart_update_quantity", {"user_id": user, "product_id": product_id, "quantity": 0})
        self.expect_failure(section, "quantité négative après retrait", "cart_update_quantity", {"user_id": user, "product_id": product_id, "quantity": -1})
        self.expect_success(section, "clear plein", "cart_add", {**base, "quantity": 1})
        self.expect_success(section, "cart_clear", "cart_clear", {"user_id": user})
        self.expect_success(section, "cart_clear déjà vide", "cart_clear", {"user_id": user})

        section = "14 États"
        state_user = self.user("state")
        self.expect_success(section, "user inconnu browsing", "get_state", {"user_id": state_user})
        valid_states = ["browsing", "selecting", "cart_review", "confirming", "ordering", "payment_pending", "completed", "human_takeover"]
        for state in valid_states:
            payload = self.expect_success(section, f"set {state}", "set_state", {"user_id": state_user, "state": state})
            if payload.get("success") and payload.get("data", {}).get("state") != state:
                self.results[-1].passed = False
                self.results[-1].reason = f"état retourné={payload.get('data', {}).get('state')}"
        self.expect_failure(section, "état invalide", "set_state", {"user_id": state_user, "state": "etat_invalide"})
        self.expect_success(section, "revert avec historique", "revert_state", {"user_id": state_user})
        self.expect_success(section, "revert sans historique", "revert_state", {"user_id": self.user("revert-empty")})

    def order_payment_and_service(self) -> None:
        if not self.product:
            return
        product = self.product
        user = self.user("order")
        cart_data = {"user_id": user, "product_id": product["id"], "product_name": product.get("nom") or "Produit", "quantity": 1, "price": product.get("prix") or "1", "platform": "database"}
        section = "15 Création commande"
        self.expect_failure(section, "panier vide", "create_order", {"user_id": self.user("order-empty"), "platform": "database", "idempotency_key": self.run_id + "-empty"})
        self.expect_success(section, "ajout fixture", "cart_add", cart_data)
        self.expect_failure(section, "state browsing", "create_order", {"user_id": user, "platform": "database", "idempotency_key": self.run_id + "-browse"})
        self.expect_success(section, "state confirming", "set_state", {"user_id": user, "state": "confirming"})
        order = self.expect_success(section, "création valide", "create_order", {"user_id": user, "platform": "database", "idempotency_key": self.run_id + "-order"})
        self.created_order_id = str(order.get("data", {}).get("order_id") or "") or None
        self.created_order_amount = str(order.get("data", {}).get("montant_total") or "") or None
        repeat = self.expect_success(section, "idempotence", "create_order", {"user_id": user, "platform": "database", "idempotency_key": self.run_id + "-order"})
        if order.get("data") != repeat.get("data"):
            self.results[-1].passed = False
            self.results[-1].reason = "résultats idempotents différents"

        section = "16-19 Commande Woo"
        missing = {"user_id": user, "platform": "woocommerce"}
        self.expect_failure(section, "statut order_id manquant", "get_order_status", missing)
        self.expect_failure(section, "statut inexistant", "get_order_status", {**missing, "order_id": "999999999"})
        self.expect_failure(section, "annulation order_id manquant", "cancel_order", missing)
        self.expect_failure(section, "annulation mauvais user", "cancel_order", {**missing, "user_id": self.user("wrong"), "order_id": self.created_order_id or "999"})
        self.expect_failure(section, "update mauvais user", "update_order", {**missing, "user_id": self.user("wrong2"), "order_id": self.created_order_id or "999", "line_items": [{"line_item_id": 1, "quantity": 0}]})
        self.expect_failure(section, "tracking mauvais user", "get_tracking", {**missing, "user_id": self.user("wrong3"), "order_id": self.created_order_id or "999"})

        section = "20 Paiement"
        self.expect_failure(section, "sans order_id", "generate_payment", {"user_id": user, "amount": self.created_order_amount or "1", "idempotency_key": self.run_id + "-pay-missing"})
        self.expect_failure(section, "order fictif", "generate_payment", {"user_id": user, "order_id": "FAKE", "amount": "1000", "idempotency_key": self.run_id + "-pay-fake"})
        for amount in (0, -1):
            self.expect_failure(section, f"amount {amount}", "generate_payment", {"user_id": user, "order_id": self.created_order_id or "FAKE", "amount": amount, "idempotency_key": f"{self.run_id}-pay-{amount}"})
        if self.created_order_id and self.created_order_amount:
            payment_data = {"user_id": user, "order_id": self.created_order_id, "amount": self.created_order_amount, "idempotency_key": self.run_id + "-pay"}
            payment = self.expect_success(section, "paiement valide", "generate_payment", payment_data)
            repeated = self.expect_success(section, "paiement idempotent", "generate_payment", payment_data)
            if payment.get("data") != repeated.get("data"):
                self.results[-1].passed = False
                self.results[-1].reason = "paiements idempotents différents"

        section = "21 Transfert humain"
        human = self.user("human")
        self.expect_success(section, "sans raison", "transfer_to_human", {"user_id": human})
        self.expect_success(section, "status actif", "check_human_status", {"user_id": human})
        silent = self.expect_success(section, "bot suspendu", "message_turn", {"user_id": human, "session_key": human, "message_id": self.run_id + "-human", "message": "bonjour"})
        if silent.get("data", {}).get("silent") is not True:
            self.results[-1].passed = False
            self.results[-1].reason = "silent=true attendu"
        self.expect_success(section, "reprise browsing", "set_state", {"user_id": human, "state": "browsing"})
        self.expect_success(section, "status inconnu", "check_human_status", {"user_id": self.user("human-unknown")})
        self.expect_success(section, "raison fournie", "transfer_to_human", {"user_id": self.user("human-reason"), "reason": "Besoin d'aide"})

        section = "22-23 Remboursement et coupon"
        self.expect_failure(section, "refund mauvais user", "request_refund", {"user_id": self.user("refund-wrong"), "order_id": self.created_order_id or "999", "amount": "1", "reason": "test", "idempotency_key": self.run_id + "-refund"})
        self.expect_failure(section, "coupon vide", "validate_coupon", {"code": "", "platform": "woocommerce"})
        self.expect_failure(section, "coupon invalide", "validate_coupon", {"code": "SCENARIO-INEXISTANT", "platform": "woocommerce"})

        section = "24 Politiques"
        for policy in ("delivery", "returns", "refund"):
            self.expect_success(section, policy, "get_policy", {"policy_type": policy})
        self.expect_failure(section, "type inconnu", "get_policy", {"policy_type": "unknown"})
        self.expect_failure(section, "type manquant", "get_policy", {})

    def full_conversations(self) -> None:
        section = "25-30 Parcours complets"
        user = self.user("full")
        turns = ["montre les produits", "je prends le 1", "mon panier", "commander", "oui"]
        for index, message in enumerate(turns, start=1):
            payload = self.expect_success(section, f"normal {index}: {message}", "message_turn", {"user_id": user, "session_key": user, "message_id": f"{self.run_id}-full-{index}", "message": message, "naturalize": False})
            if index == len(turns) and payload.get("success"):
                result = payload.get("data", {}).get("commerce", {}).get("result", {})
                if not result.get("order_id") or not result.get("payment_url"):
                    self.results[-1].passed = False
                    self.results[-1].reason = "commande ou lien PayTech absent du dernier tour"
                    self.results[-1].probable_cause = "Clés PayTech absentes ou confirmation finale incomplète."
                    self.results[-1].suggestion = "Configurer les clés sandbox PayTech sur Render puis relancer ce scénario."

        correction = self.user("correction")
        for index, message in enumerate(["montre les produits", "je prends le 1", "laisse tomber", "montre les produits"]):
            self.expect_success(section, f"correction: {message}", "message_turn", {"user_id": correction, "session_key": correction, "message_id": f"{self.run_id}-correction-{index}", "message": message, "naturalize": False})

        transfer = self.user("full-human")
        for index, message in enumerate(["montre les produits", "je veux parler à quelqu'un", "bonjour"]):
            payload = self.expect_success(section, f"transfert: {message}", "message_turn", {"user_id": transfer, "session_key": transfer, "message_id": f"{self.run_id}-transfer-{index}", "message": message, "naturalize": False})
            if index == 2 and payload.get("data", {}).get("silent") is not True:
                self.results[-1].passed = False
                self.results[-1].reason = "bot non suspendu"

    def security_and_performance(self) -> None:
        section = "31 Sécurité"
        status, payload, duration = self.request("cart_view", {"user_id": self.user("security")}, token=None)
        self.add(section, "sans token", status, payload, duration, lambda s, p: s == 401 and p.get("success") is False and self.uniform(p), "401 uniforme attendu")
        status, payload, duration = self.request("cart_view", {"user_id": self.user("security")}, token="mauvais-token")
        self.add(section, "mauvais token", status, payload, duration, lambda s, p: s == 401 and p.get("success") is False and self.uniform(p), "401 uniforme attendu")
        self.expect_failure(section, "action inconnue", "action_inconnue", {})
        self.expect_success(section, "injection SQL neutralisée", "search_products", {"query": "'; DROP TABLE products; --", "user_id": self.user("sql")})
        self.expect_failure(section, "paramètres null", "cart_add", {"user_id": None, "product_id": None})
        self.expect_failure(section, "undefined omis", "cart_add", {})
        status, payload, duration = self.request("", {}, raw_body="{", token=TOKEN)
        self.add(section, "JSON malformé", status, payload, duration, lambda s, p: s == 400 and p.get("success") is False and self.uniform(p), "400 uniforme attendu")

        section = "32 Performance"
        status, payload, duration = self.request("cart_view", {"user_id": self.user("perf")})
        self.add(section, "temps < 3 secondes", status, payload, duration, lambda s, p: s == 200 and duration < 3000 and p.get("success") is True, "temps inférieur à 3000 ms attendu", "Render, base ou réseau trop lent.", "Profiler les dépendances et éviter tout appel LLM pour cart_view.")

        def concurrent_call(index: int) -> tuple[int | None, dict[str, Any], int]:
            return self.request("cart_view", {"user_id": self.user(f"concurrent-{index}")}, throttle=False)

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as pool:
            calls = list(pool.map(concurrent_call, range(10)))
        elapsed = int((time.perf_counter() - started) * 1000)
        ok = all(status == 200 and payload.get("success") is True for status, payload, _ in calls)
        sample = calls[0][1] if calls else {}
        self.add(section, "10 requêtes simultanées", calls[0][0] if calls else None, sample, elapsed, lambda _s, _p: ok, "10 réponses 200 attendues")

        # Le test de rate-limit est volontairement le dernier : il bloque l'IP
        # de campagne pendant environ une minute.
        observed_429 = False
        last_payload: dict[str, Any] = {}
        last_status: int | None = None
        started = time.perf_counter()
        for index in range(65):
            status, payload, _ = self.request("cart_view", {"user_id": self.user(f"rate-{index}")}, throttle=False)
            last_status, last_payload = status, payload
            if status == 429:
                observed_429 = True
                break
        elapsed = int((time.perf_counter() - started) * 1000)
        self.add("31 Sécurité", "61 requêtes/minute → 429", last_status, last_payload, elapsed, lambda _s, _p: observed_429, "429 non observé")

    def report(self) -> None:
        passed = sum(result.passed for result in self.results)
        failed = len(self.results) - passed
        lines = [
            "# Rapport des scénarios AI Commerce Assistant",
            "",
            f"- URL : `{API_URL}`",
            f"- Run : `{self.run_id}`",
            f"- Total : **{len(self.results)}**",
            f"- PASS : **{passed}**",
            f"- FAIL : **{failed}**",
            "",
            "## Résultats",
            "",
            "| Statut | Section | Scénario | HTTP | Temps | Raison |",
            "|---|---|---|---:|---:|---|",
        ]
        for result in self.results:
            reason = result.reason.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {'✅ PASS' if result.passed else '❌ FAIL'} | {result.section} | {result.name} | {result.status or '-'} | {result.duration_ms} ms | {reason} |")
        failures = [result for result in self.results if not result.passed]
        lines.extend(["", "## Échecs et corrections suggérées", ""])
        if not failures:
            lines.append("Aucun échec détecté.")
        else:
            for index, result in enumerate(failures, start=1):
                lines.extend([
                    f"### {index}. {result.section} — {result.name}",
                    "",
                    f"- Cause probable : {result.probable_cause}",
                    f"- Correction suggérée : {result.suggestion}",
                    f"- Détail : {result.reason}",
                    "",
                ])
        (ROOT / "test_report.md").write_text("\n".join(lines), encoding="utf-8")

    def run(self) -> int:
        try:
            self.incoming_messages()
            self.catalogue_and_selection()
            self.cart_and_state()
            self.order_payment_and_service()
            self.full_conversations()
            self.security_and_performance()
        finally:
            self.report()
        return 0 if all(result.passed for result in self.results) else 1


if __name__ == "__main__":
    raise SystemExit(Runner().run())
