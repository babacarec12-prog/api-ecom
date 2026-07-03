"""Test fonctionnel de l'API AI Commerce Assistant.

Mode par défaut : lecture seule. Les opérations qui changent WooCommerce ne sont
jamais lancées sans ``--allow-writes`` et leurs paramètres explicites.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

DEFAULT_URL = os.getenv(
    "COMMERCE_API_URL", "http://127.0.0.1:8000/api/commerce/"
).strip()
DEFAULT_API_TOKEN = os.getenv("N8N_API_TOKEN", "").strip()


@dataclass
class Result:
    action: str
    status: str
    http_status: int | None
    duration_ms: int
    detail: str
    response: Any = None


class CommerceTester:
    def __init__(self, url: str, timeout: int, api_token: str = "") -> None:
        self.url = url
        self.timeout = timeout
        self.api_token = api_token
        self.results: list[Result] = []

    def call(self, action: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        payload = json.dumps({"action": action, "data": data}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "commerce-mvp-tester/1.0",
        }
        if self.api_token:
            headers["X-API-Token"] = self.api_token
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return response.status, json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"success": False, "error": body or str(exc)}
            return exc.code, parsed

    def run(
        self,
        action: str,
        data: dict[str, Any],
        *,
        expected_success: bool = True,
        skip_reason: str | None = None,
    ) -> dict[str, Any] | None:
        if skip_reason:
            self.results.append(Result(action, "SKIP", None, 0, skip_reason))
            print(f"[SKIP] {action}: {skip_reason}")
            return None

        started = time.perf_counter()
        try:
            http_status, response = self.call(action, data)
            duration = round((time.perf_counter() - started) * 1000)
            actual_success = response.get("success") is True
            passed = http_status == 200 and actual_success == expected_success
            detail = "Réponse conforme"
            if not passed:
                detail = str(response.get("error") or f"Réponse inattendue: {response}")
            status = "PASS" if passed else "FAIL"
            self.results.append(Result(action, status, http_status, duration, detail, response))
            print(f"[{status}] {action} ({http_status}, {duration} ms): {detail}")
            return response
        except Exception as exc:  # Le rapport doit continuer après un timeout/réseau indisponible.
            duration = round((time.perf_counter() - started) * 1000)
            self.results.append(Result(action, "FAIL", None, duration, str(exc)))
            print(f"[FAIL] {action} ({duration} ms): {exc}")
            return None

    def write_report(self, path: Path, url: str) -> None:
        passed = sum(item.status == "PASS" for item in self.results)
        failed = sum(item.status == "FAIL" for item in self.results)
        skipped = sum(item.status == "SKIP" for item in self.results)
        lines = [
            "# Compte rendu des tests Commerce",
            "",
            f"- URL : `{url}`",
            f"- Résultat : **{passed} réussi(s), {failed} échec(s), {skipped} ignoré(s)**",
            "",
            "| Action | État | HTTP | Durée | Détail |",
            "|---|---:|---:|---:|---|",
        ]
        for item in self.results:
            detail = item.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{item.action}` | {item.status} | {item.http_status or '-'} | "
                f"{item.duration_ms} ms | {detail} |"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def products_from(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not response or response.get("success") is not True:
        return []
    return response.get("data", {}).get("products", []) or []


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste les 11 actions de /api/commerce/.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--api-token",
        default=DEFAULT_API_TOKEN,
        help="Valeur du header X-API-Token (par défaut : N8N_API_TOKEN du .env)",
    )
    parser.add_argument("--query", default="bissap")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--report", default="test-report.md")
    parser.add_argument("--order-id", help="Commande de TEST pour statut/tracking et écritures")
    parser.add_argument("--user-id", help="Identifiant WhatsApp propriétaire de la commande de test")
    parser.add_argument("--coupon", help="Code promo réel à vérifier")
    parser.add_argument("--product-id", help="Produit de test ; sinon le premier résultat est utilisé")
    parser.add_argument("--variant-id", help="Variante réelle à vérifier")
    parser.add_argument("--line-item-id", help="Ligne de commande réelle à modifier")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--refund-amount", type=float, help="Montant de remboursement à enregistrer")
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="Autorise create_order, update_order, cancel_order et request_refund",
    )
    parser.add_argument(
        "--allow-payment",
        action="store_true",
        help="Autorise generate_payment (nécessite --order-id et --payment-amount)",
    )
    parser.add_argument("--payment-amount", type=int)
    parser.add_argument(
        "--confirm-cancel",
        action="store_true",
        help="Confirme spécifiquement l'annulation irréversible de --order-id",
    )
    args = parser.parse_args()

    tester = CommerceTester(args.url, args.timeout, args.api_token)

    search = tester.run("search_products", {"query": args.query})
    products = products_from(search)
    product_id = args.product_id or (str(products[0].get("id")) if products else None)

    tester.run(
        "get_product",
        {"product_id": product_id, "platform": "woocommerce"},
        skip_reason=None if product_id else "Aucun product_id disponible",
    )
    tester.run(
        "check_variant_stock",
        {"product_id": product_id, "variant_id": args.variant_id, "platform": "woocommerce"},
        skip_reason=None if product_id and args.variant_id else "Fournir --variant-id et un produit variable",
    )
    tester.run(
        "validate_coupon",
        {"code": args.coupon, "platform": "woocommerce"},
        skip_reason=None if args.coupon else "Fournir --coupon",
    )
    tester.run(
        "get_order_status",
        {"order_id": args.order_id, "platform": "woocommerce"},
        skip_reason=None if args.order_id else "Fournir --order-id",
    )
    tester.run(
        "get_tracking",
        {"order_id": args.order_id, "platform": "woocommerce", "user_id": args.user_id},
        skip_reason=None if args.order_id else "Fournir --order-id",
    )

    # Écritures : elles restent impossibles par accident en mode par défaut.
    tester.run(
        "create_order",
        {
            "user_id": args.user_id,
            "platform": "woocommerce",
            "cart": [{"product_id": product_id, "quantity": args.quantity, "platform": "woocommerce"}],
        },
        skip_reason=(
            None
            if args.allow_writes and args.user_id and product_id
            else "Nécessite --allow-writes, --user-id et un produit"
        ),
    )
    tester.run(
        "update_order",
        {
            "order_id": args.order_id,
            "line_items": [{"line_item_id": args.line_item_id, "quantity": args.quantity}],
            "platform": "woocommerce",
            "user_id": args.user_id,
        },
        skip_reason=(
            None
            if args.allow_writes and args.order_id and args.line_item_id
            else "Nécessite --allow-writes, --order-id et --line-item-id"
        ),
    )
    tester.run(
        "request_refund",
        {
            "order_id": args.order_id,
            "amount": args.refund_amount,
            "reason": "Test fonctionnel contrôlé",
            "platform": "woocommerce",
            "user_id": args.user_id,
        },
        skip_reason=(
            None
            if args.allow_writes and args.order_id and args.refund_amount
            else "Nécessite --allow-writes, --order-id et --refund-amount"
        ),
    )
    tester.run(
        "generate_payment",
        {"order_id": args.order_id, "amount": args.payment_amount},
        skip_reason=(
            None
            if args.allow_payment and args.order_id and args.payment_amount
            else "Nécessite --allow-payment, --order-id et --payment-amount"
        ),
    )
    tester.run(
        "cancel_order",
        {
            "order_id": args.order_id,
            "user_id": args.user_id,
            "reason": "Test fonctionnel contrôlé",
            "platform": "woocommerce",
        },
        skip_reason=(
            None
            if args.allow_writes and args.confirm_cancel and args.order_id and args.user_id
            else "Nécessite --allow-writes, --confirm-cancel, --order-id et --user-id"
        ),
    )

    report = Path(args.report)
    tester.write_report(report, args.url)
    failures = sum(item.status == "FAIL" for item in tester.results)
    print(f"\nRapport écrit dans {report.resolve()}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
