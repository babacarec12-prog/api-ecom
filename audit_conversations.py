"""Audit qualitatif multi-tour du cœur conversationnel déployé sur Render."""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
API_URL = os.getenv("COMMERCE_TEST_URL", "https://ai-commerce-api-babacare.onrender.com/api/commerce/")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def env_value(name: str) -> str:
    direct = os.getenv(name)
    if direct:
        return direct.strip()
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith(name + "="):
            return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


TOKEN = env_value("N8N_API_TOKEN")
FORBIDDEN = re.compile(
    r"cher client|bien sûr|je suis ravi|n'hésitez pas|veuillez patienter|"
    r"merci de votre compréhension|assistance supplémentaire|"
    r"réponse sûre|intention|traitement|système|tool_calls|service indisponible",
    re.IGNORECASE,
)
TUTOIEMENT = re.compile(r"\b(?:tu|te|toi|ton|ta|tes)\b", re.IGNORECASE)


@dataclass
class Turn:
    message: str
    intents: set[str] = field(default_factory=set)
    contains: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    silent: bool = False


SCENARIOS: dict[str, list[Turn]] = {
    "catalogue_et_pronoms": [
        Turn("Salut"),
        Turn("montre-moi ce que vous avez", {"search_products"}, ("FCFA",)),
        Turn("le 2 m'intéresse", {"get_product"}),
        Turn("ajoute-le", {"cart_add"}, ("panier",)),
        Turn("et mets-en 3 au total", {"cart_update_quantity"}, ("3",)),
        Turn("ça fait combien maintenant ?", {"cart_view"}, ("Total",)),
    ],
    "achat_direct_naturel": [
        Turn("je cherche du bissap", {"search_products", "get_product"}, ("Bissap", "FCFA")),
        Turn("j'en prends deux", {"cart_add"}, ("2", "panier")),
        Turn("je veux commander", {"create_order"}, ("confirmer", "Total")),
        Turn("attends, pas encore", {"cancel_pending_action"}, absent=("confirmée",)),
        Turn("montre mon panier", {"cart_view"}, ("Bissap",)),
    ],
    "correction_de_choix": [
        Turn("affiche les produits", {"search_products"}),
        Turn("je prends le premier", {"cart_add"}, ("panier",)),
        Turn("non enlève-le finalement", {"cart_remove"}, ("panier",)),
        Turn("je préfère le bissap", {"search_products", "get_product", "cart_add"}, ("Bissap",)),
        Turn("ajoutes-en 2", {"cart_add", "cart_update_quantity"}, ("2", "Bissap")),
    ],
    "langage_senegalais": [
        Turn("nanga def", contains=("Bonjour",)),
        Turn("am nga bissap ?", {"search_products", "get_product"}, ("Bissap",)),
        Turn("waw dama bëgg ñaar", {"cart_add"}, ("2",)),
        Turn("sama panier bi dafa am lan ?", {"cart_view"}, ("panier",)),
    ],
    "fautes_et_messages_courts": [
        Turn("vs avé koi kom produit", {"search_products"}, ("FCFA",)),
        Turn("3", {"get_product"}),
        Turn("pren le", {"cart_add"}, ("panier",)),
        Turn("panier", {"cart_view"}, ("Total",)),
    ],
    "politiques_et_hors_sujet": [
        Turn("vous livrez à Dakar ?", {"get_policy"}, absent=("préciser",)),
        Turn("et les retours ça marche comment ?", {"get_policy"}, absent=("préciser",)),
        Turn("raconte-moi une blague", {"other"}, absent=("préciser",)),
        Turn("bon revenons aux produits, vous avez du bissap ?", {"search_products", "get_product"}, ("Bissap",)),
    ],
    "confirmation_contextuelle": [
        Turn("montre les produits", {"search_products"}),
        Turn("je prends le 2", {"cart_add"}, ("panier",)),
        Turn("commander", {"create_order"}, ("confirmer",)),
        Turn("non laisse tomber", {"cancel_pending_action"}, absent=("commande est confirmée",)),
        Turn("mon panier", {"cart_view"}),
    ],
    "transfert_humain": [
        Turn("je veux parler à un conseiller", {"transfer_to_human"}),
        Turn("vous êtes là ?", silent=True),
    ],
}


def nested(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        current = current.get(key) if isinstance(current, dict) else None
    return current


def run() -> int:
    if not TOKEN:
        raise RuntimeError("N8N_API_TOKEN absent")
    run_id = uuid.uuid4().hex[:10]
    rows: list[dict[str, Any]] = []
    headers = {"X-API-Token": TOKEN, "Content-Type": "application/json"}
    for scenario, turns in SCENARIOS.items():
        user = f"audit-{run_id}-{scenario}"[:50]
        for index, expected in enumerate(turns, 1):
            started = time.perf_counter()
            try:
                response = requests.post(
                    API_URL,
                    headers=headers,
                    json={
                        "action": "message_turn",
                        "data": {
                            "user_id": user,
                            "session_key": user,
                            "message_id": f"{run_id}-{scenario}-{index}",
                            "message": expected.message,
                            "naturalize": True,
                        },
                    },
                    timeout=45,
                )
                payload = response.json()
                status = response.status_code
            except Exception as exc:
                payload, status = {"error": str(exc)}, None
            elapsed = int((time.perf_counter() - started) * 1000)
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            answer = "" if data.get("message") is None else str(data.get("message", "")).strip()
            intent = str(nested(data, "analysis", "intention") or "")
            failures: list[str] = []
            if status != 200 or payload.get("success") is not True:
                failures.append(f"contrat HTTP/JSON invalide ({status})")
            if expected.silent:
                if data.get("silent") is not True:
                    failures.append("silent=true attendu")
            elif not answer:
                failures.append("réponse vide")
            if answer and FORBIDDEN.search(answer):
                failures.append("formulation mécanique ou fuite interne")
            if answer and TUTOIEMENT.search(answer):
                failures.append("tutoiement incohérent avec le ton boutique")
            if answer and len(answer) > 650 and "\n" not in answer:
                failures.append("réponse trop longue")
            if expected.intents and intent not in expected.intents:
                failures.append(f"intention={intent or 'absente'}, attendu={sorted(expected.intents)}")
            folded = answer.casefold()
            for text in expected.contains:
                if text.casefold() not in folded:
                    failures.append(f"réponse sans {text!r}")
            for text in expected.absent:
                if text.casefold() in folded:
                    failures.append(f"réponse contient indûment {text!r}")
            passed = not failures
            rows.append({
                "scenario": scenario,
                "turn": index,
                "client": expected.message,
                "assistant": answer or "[SILENCE]",
                "intent": intent or "-",
                "state": nested(data, "commerce", "state", "state") or nested(data, "commerce", "result", "state") or "-",
                "elapsed": elapsed,
                "passed": passed,
                "failures": failures,
            })
            print(("✅" if passed else "❌") + f" {scenario}/{index}: {expected.message} → {intent or '-'} ({elapsed} ms)")
            time.sleep(0.15)

    passed = sum(row["passed"] for row in rows)
    timings = [row["elapsed"] for row in rows if row["assistant"] != "[SILENCE]"]
    median_ms = int(statistics.median(timings)) if timings else 0
    p95_ms = sorted(timings)[max(0, int(len(timings) * 0.95) - 1)] if timings else 0
    performance_ok = median_ms < 3000
    lines = [
        "# Audit conversationnel qualitatif",
        "",
        f"- Run : `{run_id}`",
        f"- Dialogues : **{len(SCENARIOS)}**",
        f"- Tours : **{len(rows)}**",
        f"- PASS : **{passed}**",
        f"- FAIL : **{len(rows) - passed}**",
        f"- Temps médian : **{median_ms} ms** ({'PASS' if performance_ok else 'FAIL'}, objectif majorité < 3 s)",
        f"- P95 : **{p95_ms} ms**",
        "",
    ]
    for scenario in SCENARIOS:
        lines.extend([f"## {scenario.replace('_', ' ').title()}", ""])
        for row in [item for item in rows if item["scenario"] == scenario]:
            marker = "✅" if row["passed"] else "❌"
            lines.extend([
                f"**{marker} Client :** {row['client']}",
                "",
                f"**Assistant :** {row['assistant']}",
                "",
                f"Intention : `{row['intent']}` — {row['elapsed']} ms",
            ])
            if row["failures"]:
                lines.append("Problèmes : " + "; ".join(row["failures"]))
            lines.append("")
    (ROOT / "conversation_audit_report.md").write_text("\n".join(lines), encoding="utf-8")
    return 0 if passed == len(rows) and performance_ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
