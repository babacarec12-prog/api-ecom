"""Création des sessions de paiement Stripe Checkout."""
import os
from decimal import Decimal, InvalidOperation

import stripe

from .exceptions import CommerceError


class StripeClient:
    def __init__(self):
        secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
        if not secret:
            raise CommerceError("La configuration Stripe est incomplète.", 500)
        stripe.api_key = secret
        self.currency = os.getenv("STRIPE_CURRENCY", "xof").lower()
        self.success_url = os.getenv("STRIPE_SUCCESS_URL", "").strip()
        self.cancel_url = os.getenv("STRIPE_CANCEL_URL", "").strip()
        if not self.success_url or not self.cancel_url:
            raise CommerceError("Les URL de retour Stripe sont manquantes.", 500)

    def generate_payment(self, order_id, amount):
        try:
            # Stripe attend le montant dans la plus petite unité de la devise.
            amount_int = int(Decimal(str(amount)))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise CommerceError("Le montant du paiement est invalide.", 400) from exc
        if amount_int <= 0:
            raise CommerceError("Le montant du paiement doit être supérieur à zéro.", 400)

        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                success_url=self.success_url,
                cancel_url=self.cancel_url,
                client_reference_id=str(order_id),
                metadata={"order_id": str(order_id)},
                line_items=[
                    {
                        "price_data": {
                            "currency": self.currency,
                            "unit_amount": amount_int,
                            "product_data": {"name": f"Commande #{order_id}"},
                        },
                        "quantity": 1,
                    }
                ],
            )
        except stripe.StripeError as exc:
            message = getattr(exc, "user_message", None) or str(exc)
            raise CommerceError(f"Erreur Stripe : {message}") from exc
        return {"payment_url": session.url, "session_id": session.id}
