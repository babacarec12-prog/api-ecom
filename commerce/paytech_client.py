"""Création de liens de paiement avec l'API PayTech."""

import json
import os
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import requests

from .exceptions import CommerceError


class PayTechClient:
    """Client minimal pour initier un paiement PayTech côté serveur."""

    def __init__(self):
        self.api_key = os.getenv("PAYTECH_API_KEY", "").strip()
        self.api_secret = os.getenv("PAYTECH_API_SECRET", "").strip()
        self.api_url = os.getenv(
            "PAYTECH_API_URL",
            "https://paytech.sn/api/payment/request-payment",
        ).strip()
        self.currency = os.getenv("PAYTECH_CURRENCY", "XOF").strip().upper()
        self.environment = os.getenv("PAYTECH_ENV", "test").strip().lower()
        self.ipn_url = os.getenv("PAYTECH_IPN_URL", "").strip()
        self.success_url = os.getenv("PAYTECH_SUCCESS_URL", "").strip()
        self.cancel_url = os.getenv("PAYTECH_CANCEL_URL", "").strip()

        placeholders = {
            "METS_TA_CLE_PAYTECH_ICI",
            "METS_TON_SECRET_PAYTECH_ICI",
            "YOUR_PAYTECH_API_KEY",
            "YOUR_PAYTECH_API_SECRET",
        }
        if (
            not self.api_key
            or not self.api_secret
            or self.api_key in placeholders
            or self.api_secret in placeholders
        ):
            raise CommerceError("La configuration PayTech est incomplète.", 500)
        if not self.ipn_url or not self.success_url or not self.cancel_url:
            raise CommerceError("Les URL de notification PayTech sont manquantes.", 500)
        if self.environment not in {"test", "prod"}:
            raise CommerceError("PAYTECH_ENV doit valoir 'test' ou 'prod'.", 500)

    @staticmethod
    def _amount(amount):
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise CommerceError("Le montant du paiement est invalide.", 400) from exc

        if value <= 0 or value != value.to_integral_value():
            raise CommerceError(
                "Le montant PayTech doit être un entier strictement positif.", 400
            )
        return int(value)

    def generate_payment(self, order_id, amount):
        """Demande un token PayTech et retourne son URL de paiement."""
        amount_int = self._amount(amount)
        reference = f"order-{order_id}-{uuid4().hex[:10]}"
        payload = {
            "item_name": f"Commande #{order_id}",
            "item_price": str(amount_int),
            "currency": self.currency,
            "ref_command": reference,
            "command_name": f"Paiement commande #{order_id}",
            "env": self.environment,
            "ipn_url": self.ipn_url,
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
            "custom_field": json.dumps({"order_id": str(order_id)}),
        }
        headers = {
            "API_KEY": self.api_key,
            "API_SECRET": self.api_secret,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise CommerceError(f"PayTech est inaccessible : {exc}") from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise CommerceError("PayTech a renvoyé une réponse JSON invalide.") from exc

        if not response.ok or result.get("success") not in {1, True, "1"}:
            message = result.get("message") or result.get("error") or response.text[:300]
            raise CommerceError(
                f"Erreur PayTech ({response.status_code}) : {message or 'réponse inconnue'}"
            )

        payment_url = result.get("redirect_url")
        token = result.get("token")
        if not payment_url or not token:
            raise CommerceError("PayTech n'a pas renvoyé de lien de paiement valide.")

        return {
            "payment_url": payment_url,
            "token": token,
            "reference": reference,
            "provider": "paytech",
        }
