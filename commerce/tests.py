import os
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from commerce.exceptions import CommerceError
from commerce.paytech_client import PayTechClient
from commerce.woo_client import WooCommerceClient
from commerce.models import (
    Cart,
    ConversationState,
    HumanTransfer,
    ProcessedRequest,
    ProductSelection,
    ShopPolicy,
    UserOrder,
)


class CommerceEndpointTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("commerce.views.HANDLERS")
    def test_success_response_contract(self, handlers):
        handlers.__getitem__.return_value = lambda data: {"products": []}
        response = self.client.post(
            "/api/commerce/",
            {"action": "search_products", "data": {"query": "nike"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True, "data": {"products": []}})

    def test_unknown_action_is_rejected(self):
        response = self.client.post(
            "/api/commerce/", {"action": "delete_order", "data": {}}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])

    def test_get_method_uses_error_contract(self):
        response = self.client.get("/api/commerce/")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(set(response.json()), {"success", "error"})

    def test_malformed_json_uses_error_contract(self):
        response = self.client.post(
            "/api/commerce/", data="{", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"success", "error"})

    @patch("commerce.views.HANDLERS")
    def test_search_accepts_plain_text_data_from_ai(self, handlers):
        handler = handlers.__getitem__.return_value
        handler.return_value = {"products": []}

        response = self.client.post(
            "/api/commerce/",
            {"action": "search_products", "data": "bissap"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        handler.assert_called_once_with({"query": "bissap"})

    @patch("commerce.views.HANDLERS")
    def test_search_accepts_json_string_data_from_ai(self, handlers):
        handler = handlers.__getitem__.return_value
        handler.return_value = {"products": []}

        response = self.client.post(
            "/api/commerce/",
            {"action": "search_products", "data": '{"query":"bissap"}'},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        handler.assert_called_once_with({"query": "bissap"})


class PayTechClientTests(SimpleTestCase):
    config = {
        "PAYTECH_API_KEY": "test-api-key",
        "PAYTECH_API_SECRET": "test-api-secret",
        "PAYTECH_API_URL": "https://paytech.example/request-payment",
        "PAYTECH_CURRENCY": "XOF",
        "PAYTECH_ENV": "test",
        "PAYTECH_IPN_URL": "https://example.com/ipn/",
        "PAYTECH_SUCCESS_URL": "https://example.com/success/",
        "PAYTECH_CANCEL_URL": "https://example.com/cancel/",
    }

    @patch.dict(os.environ, config)
    @patch("commerce.paytech_client.requests.post")
    def test_generate_payment_returns_paytech_url(self, post):
        response = Mock(ok=True, status_code=200, text="")
        response.json.return_value = {
            "success": 1,
            "token": "payment-token",
            "redirect_url": "https://paytech.sn/payment/checkout/payment-token",
        }
        post.return_value = response

        result = PayTechClient().generate_payment("456", 8900)

        self.assertEqual(result["provider"], "paytech")
        self.assertEqual(
            result["payment_url"],
            "https://paytech.sn/payment/checkout/payment-token",
        )
        sent = post.call_args.kwargs
        self.assertEqual(sent["json"]["item_price"], "8900")
        self.assertEqual(sent["json"]["currency"], "XOF")
        self.assertEqual(sent["headers"]["API_KEY"], "test-api-key")

    @patch.dict(os.environ, config)
    def test_generate_payment_rejects_fractional_amount(self):
        with self.assertRaises(CommerceError):
            PayTechClient().generate_payment("456", "8900.5")


class WooCommerceClientSearchTests(SimpleTestCase):
    config = {
        "WOO_STORE_URL": "https://shop.example",
        "WOO_CONSUMER_KEY": "ck_test",
        "WOO_CONSUMER_SECRET": "cs_test",
    }

    @staticmethod
    def product(product_id, name, **extra):
        return {
            "id": product_id,
            "name": name,
            "price": "2500",
            "stock_quantity": 12,
            "stock_status": "instock",
            **extra,
        }

    @patch.dict(os.environ, config)
    def test_search_returns_native_woocommerce_results_without_fallback(self):
        client = WooCommerceClient()
        client._request = Mock(return_value=[self.product(1, "Bissap naturel")])

        result = client.search_products("bissap")

        self.assertEqual(result[0]["nom"], "Bissap naturel")
        client._request.assert_called_once_with(
            "GET", "products", params={"search": "bissap", "per_page": 50}
        )

    @patch.dict(os.environ, config)
    def test_search_uses_local_fuzzy_fallback_for_typo(self):
        client = WooCommerceClient()
        client._request = Mock(
            side_effect=[
                [],
                [
                    self.product(2, "Jus de gingembre 1 L"),
                    self.product(3, "Bissap naturel 1 L"),
                ],
            ]
        )

        result = client.search_products("gingimbre")

        self.assertEqual([product["id"] for product in result], ["2"])
        self.assertEqual(client._request.call_count, 2)
        client._request.assert_called_with(
            "GET", "products", params={"per_page": 100}
        )

    @patch.dict(os.environ, config)
    def test_star_lists_up_to_100_catalogue_products(self):
        client = WooCommerceClient()
        client._request = Mock(return_value=[self.product(4, "Café Touba")])

        result = client.search_products("*")

        self.assertEqual(result[0]["id"], "4")
        client._request.assert_called_once_with(
            "GET", "products", params={"per_page": 100}
        )

    @patch.dict(os.environ, config)
    def test_fuzzy_fallback_rejects_unrelated_products(self):
        client = WooCommerceClient()
        client._request = Mock(
            side_effect=[[], [self.product(5, "Confiture de mangue")]]
        )

        self.assertEqual(client.search_products("ordinateur"), [])

    @patch.dict(os.environ, config)
    def test_confirmation_does_not_trigger_fuzzy_product_fallback(self):
        client = WooCommerceClient()
        client._request = Mock(return_value=[])

        self.assertEqual(client.search_products("oui"), [])
        client._request.assert_called_once_with(
            "GET", "products", params={"search": "oui", "per_page": 50}
        )

    @patch.dict(os.environ, config)
    def test_short_or_numeric_query_does_not_trigger_fuzzy_fallback(self):
        for query in ("abc", "12345"):
            with self.subTest(query=query):
                client = WooCommerceClient()
                client._request = Mock(return_value=[])

                self.assertEqual(client.search_products(query), [])
                self.assertEqual(client._request.call_count, 1)

    def test_stock_preserves_explicit_zero_quantity(self):
        self.assertEqual(
            WooCommerceClient._stock(
                {"stock_quantity": 0, "stock_status": "instock"}
            ),
            0,
        )

    @patch.dict(os.environ, config)
    def test_order_status_maps_terminal_states_correctly(self):
        expected = {
            "cancelled": "annulée",
            "refunded": "remboursée",
            "failed": "échouée",
        }
        for woo_status, api_status in expected.items():
            with self.subTest(woo_status=woo_status):
                client = WooCommerceClient()
                client._request = Mock(return_value={"status": woo_status})

                result = client.get_order_status("38")

                self.assertEqual(result["statut"], api_status)


class WooCommerceOrderActionTests(SimpleTestCase):
    config = WooCommerceClientSearchTests.config

    @patch.dict(os.environ, config)
    def test_cancel_order_updates_status(self):
        client = WooCommerceClient()
        client._request = Mock(
            side_effect=[
                {
                    "id": 42,
                    "meta_data": [
                        {"key": "whatsapp_user_id", "value": "221700000000"}
                    ],
                },
                {"id": 42, "status": "cancelled"},
            ]
        )

        result = client.cancel_order(
            "42", "Erreur de quantité", "221700000000"
        )

        self.assertEqual(result["statut"], "annulée")
        self.assertEqual(client._request.call_count, 2)
        client._request.assert_any_call("GET", "orders/42")
        client._request.assert_any_call(
            "PUT",
            "orders/42",
            json={"status": "cancelled", "customer_note": "Erreur de quantité"},
        )

    @patch.dict(os.environ, config)
    def test_cancel_order_rejects_another_whatsapp_user(self):
        client = WooCommerceClient()
        client._request = Mock(
            return_value={
                "id": 42,
                "meta_data": [
                    {"key": "whatsapp_user_id", "value": "221700000000"}
                ],
            }
        )

        with self.assertRaises(CommerceError) as error:
            client.cancel_order("42", "", "221711111111")

        self.assertEqual(error.exception.status_code, 403)
        client._request.assert_called_once_with("GET", "orders/42")

    @patch.dict(os.environ, config)
    def test_refund_uses_woocommerce_refund_endpoint(self):
        client = WooCommerceClient()
        client._request = Mock(return_value={"id": 7, "amount": "2500.00"})

        result = client.request_refund("42", 2500.0, "Produit endommagé")

        self.assertEqual(result["refund_id"], "7")
        client._request.assert_called_once_with(
            "POST",
            "orders/42/refunds",
            json={
                "amount": "2500.00",
                "reason": "Produit endommagé",
                "api_refund": False,
            },
        )

    @patch.dict(os.environ, config)
    def test_update_order_sends_existing_line_ids(self):
        client = WooCommerceClient()
        client._request = Mock(
            return_value={
                "id": 42,
                "total": "5000",
                "currency": "XOF",
                "line_items": [{"id": 8, "product_id": 18, "quantity": 2}],
            }
        )

        result = client.update_order("42", [{"id": 8, "quantity": 2}])

        self.assertEqual(result["lignes"][0]["quantity"], 2)
        client._request.assert_called_once_with(
            "PUT", "orders/42", json={"line_items": [{"id": 8, "quantity": 2}]}
        )

    @patch.dict(os.environ, config)
    def test_tracking_reads_common_woocommerce_metadata(self):
        client = WooCommerceClient()
        client._request = Mock(
            return_value={
                "meta_data": [
                    {"key": "_tracking_number", "value": "SN123"},
                    {"key": "_tracking_provider", "value": "DHL"},
                    {"key": "_tracking_link", "value": "https://track.example/SN123"},
                ]
            }
        )

        result = client.get_tracking("42")

        self.assertTrue(result["suivi_disponible"])
        self.assertEqual(result["numero_suivi"], "SN123")

    @patch.dict(os.environ, config)
    def test_coupon_is_matched_case_insensitively(self):
        client = WooCommerceClient()
        client._request = Mock(
            return_value=[
                {
                    "code": "PROMO10",
                    "status": "publish",
                    "discount_type": "percent",
                    "amount": "10",
                    "date_expires": None,
                    "minimum_amount": "0",
                    "maximum_amount": "",
                }
            ]
        )

        result = client.validate_coupon("promo10")

        self.assertTrue(result["valide"])
        self.assertEqual(result["montant"], "10")

    @patch.dict(os.environ, config)
    def test_variant_stock_uses_exact_product_and_variant(self):
        client = WooCommerceClient()
        client._request = Mock(
            return_value={
                "stock_status": "instock",
                "stock_quantity": 4,
                "price": "3000",
                "attributes": [{"name": "Taille", "option": "M"}],
            }
        )

        result = client.check_variant_stock("18", "21")

        self.assertEqual(result["stock"], 4)
        client._request.assert_called_once_with("GET", "products/18/variations/21")


class WooCommerceNewEndpointValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("commerce.views.WooCommerceClient")
    def test_cancel_order_is_dispatched_to_woocommerce(self, woo_class):
        woo_class.return_value.cancel_order.return_value = {
            "order_id": "42",
            "statut": "annulée",
        }
        woo_class.return_value.order_belongs_to_user.return_value = True
        response = self.client.post(
            "/api/commerce/",
            {
                "action": "cancel_order",
                "data": {
                    "order_id": "42",
                    "user_id": "221700000000",
                    "platform": "woocommerce",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        woo_class.return_value.cancel_order.assert_called_once_with(
            "42", "", "221700000000"
        )

    def test_refund_rejects_non_positive_amount(self):
        response = self.client.post(
            "/api/commerce/",
            {"action": "request_refund", "data": {"order_id": "42", "amount": 0}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])

    def test_update_order_requires_line_item_id(self):
        response = self.client.post(
            "/api/commerce/",
            {
                "action": "update_order",
                "data": {
                    "order_id": "42",
                    "user_id": "221700000000",
                    "line_items": [{"quantity": 2}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("line_item_id", response.json()["error"])

    def test_new_actions_reject_shopify_platform(self):
        response = self.client.post(
            "/api/commerce/",
            {
                "action": "get_tracking",
                "data": {
                    "order_id": "42",
                    "user_id": "221700000000",
                    "platform": "shopify",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("uniquement", response.json()["error"])


class PersistentCommerceActionsTests(TestCase):
    """Vérifie les actions persistantes sans contacter WooCommerce."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user_id = "221700000000"

    def post(self, action, data):
        return self.client.post(
            "/api/commerce/", {"action": action, "data": data}, format="json"
        )

    def test_cart_actions_return_complete_cart_and_total(self):
        add = self.post(
            "cart_add",
            {
                "user_id": self.user_id,
                "product_id": "18",
                "product_name": "Bissap naturel",
                "quantity": 2,
                "price": "2500",
            },
        )
        self.assertEqual(add.status_code, 200)
        self.assertEqual(add.json()["data"]["total"], "5000.00")
        self.assertEqual(ConversationState.objects.get(user_id=self.user_id).state, "cart_review")

        update = self.post(
            "cart_update_quantity",
            {"user_id": self.user_id, "product_id": "18", "quantity": 3},
        )
        self.assertEqual(update.json()["data"]["total"], "7500.00")
        view = self.post("cart_view", {"user_id": self.user_id})
        self.assertEqual(view.json()["data"]["items"][0]["quantity"], 3)
        remove = self.post(
            "cart_remove", {"user_id": self.user_id, "product_id": "18"}
        )
        self.assertEqual(remove.json()["data"]["items"], [])

        Cart.objects.create(
            user_id=self.user_id,
            product_id="19",
            product_name="Café",
            quantity=1,
            price="3500",
        )
        clear = self.post("cart_clear", {"user_id": self.user_id})
        self.assertEqual(clear.json()["data"]["total"], "0")

    def test_selection_position_is_deterministic(self):
        response = self.post(
            "save_selection_list",
            {
                "user_id": self.user_id,
                "session_key": "session-1",
                "products": [
                    {"position": 1, "product_id": "18", "product_name": "Bissap", "price": 2500},
                    {"position": 2, "product_id": "22", "product_name": "T-shirt", "price": 7500},
                ],
            },
        )
        self.assertEqual(response.json()["data"]["saved"], 2)
        selected = self.post(
            "get_product_by_position", {"user_id": self.user_id, "position": 2}
        )
        self.assertEqual(selected.json()["data"]["product_id"], "22")
        self.assertEqual(ProductSelection.objects.count(), 2)

    @patch("commerce.views.WooCommerceClient")
    def test_conversation_turn_catalogue_selection_and_cart_are_deterministic(self, woo_class):
        woo = woo_class.return_value
        woo.search_products.return_value = [
            {"id": "10", "nom": "Batterie externe", "prix": "22000", "stock": 13},
            {"id": "18", "nom": "Bissap naturel", "prix": "2500", "stock": 30},
        ]
        woo.get_product.return_value = {
            "id": "10",
            "nom": "Batterie externe",
            "prix": "22000",
            "stock": 13,
            "plateforme": "woocommerce",
        }

        catalogue = self.post(
            "conversation_turn",
            {"user_id": self.user_id, "message": "montre moi le catalogue", "session_key": "s1"},
        )
        self.assertEqual(catalogue.status_code, 200)
        self.assertIn("1. Batterie externe", catalogue.json()["data"]["direct_response"])
        self.assertEqual(ProductSelection.objects.get(user_id=self.user_id, position=1).product_id, "10")

        selection = self.post(
            "conversation_turn", {"user_id": self.user_id, "message": "1"}
        )
        self.assertIn("Batterie externe", selection.json()["data"]["direct_response"])
        self.assertEqual(ConversationState.objects.get(user_id=self.user_id).pending_product_id, "10")

        addition = self.post(
            "conversation_turn", {"user_id": self.user_id, "message": "oui"}
        )
        self.assertIn("ajouté au panier", addition.json()["data"]["direct_response"])
        self.assertEqual(Cart.objects.get(user_id=self.user_id).product_id, "10")
        self.assertEqual(ConversationState.objects.get(user_id=self.user_id).state, "cart_review")

    def test_state_progression_and_revert(self):
        initial = self.post("get_state", {"user_id": self.user_id})
        self.assertEqual(initial.json()["data"]["state"], "browsing")
        moved = self.post(
            "set_state", {"user_id": self.user_id, "state": "selecting"}
        )
        self.assertEqual(moved.json()["data"]["state"], "selecting")
        reverted = self.post("revert_state", {"user_id": self.user_id})
        self.assertEqual(reverted.json()["data"]["state"], "browsing")
        forbidden = self.post(
            "set_state", {"user_id": self.user_id, "state": "ordering"}
        )
        self.assertEqual(forbidden.status_code, 409)

    @patch("commerce.views.WooCommerceClient")
    def test_create_order_requires_state_and_is_idempotent(self, woo_class):
        woo_class.return_value.create_order.return_value = {
            "order_id": "77",
            "montant_total": "2500",
            "devise": "XOF",
            "plateforme": "woocommerce",
        }
        Cart.objects.create(
            user_id=self.user_id,
            product_id="18",
            product_name="Bissap",
            quantity=1,
            price="2500",
        )
        state = ConversationState.objects.create(
            user_id=self.user_id, state="confirming", previous_state="cart_review"
        )
        payload = {
            "user_id": self.user_id,
            "platform": "woocommerce",
            "idempotency_key": "order-key-1",
        }
        first = self.post("create_order", payload)
        second = self.post("create_order", payload)
        self.assertEqual(first.json()["data"]["order_id"], "77")
        self.assertEqual(second.json()["data"]["order_id"], "77")
        woo_class.return_value.create_order.assert_called_once()
        self.assertTrue(UserOrder.objects.filter(order_id="77", user_id=self.user_id).exists())
        self.assertEqual(ProcessedRequest.objects.count(), 1)
        state.refresh_from_db()
        self.assertEqual(state.state, "ordering")

    @patch("commerce.views.PayTechClient")
    def test_generate_payment_requires_real_owned_order_and_is_idempotent(self, paytech):
        paytech.return_value.generate_payment.return_value = {
            "payment_url": "https://pay.example/77",
            "provider": "paytech",
        }
        ConversationState.objects.create(
            user_id=self.user_id,
            state="ordering",
            previous_state="confirming",
            pending_order_id="77",
            pending_amount="2500",
        )
        UserOrder.objects.create(user_id=self.user_id, order_id="77")
        payload = {
            "user_id": self.user_id,
            "order_id": "77",
            "amount": 2500,
            "idempotency_key": "payment-key-1",
        }
        first = self.post("generate_payment", payload)
        second = self.post("generate_payment", payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json()["data"]["payment_url"], "https://pay.example/77")
        paytech.return_value.generate_payment.assert_called_once_with("77", 2500)

    @patch("commerce.views.WooCommerceClient")
    def test_owner_is_required_for_order_status(self, woo_class):
        woo_class.return_value.order_belongs_to_user.return_value = False
        response = self.post(
            "get_order_status", {"user_id": self.user_id, "order_id": "999"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Commande introuvable pour ce compte.")

    def test_transfer_human_persists_and_blocks_bot(self):
        transfer = self.post(
            "transfer_to_human", {"user_id": self.user_id, "reason": "Client demandé"}
        )
        self.assertTrue(transfer.json()["data"]["human_takeover"])
        self.assertTrue(HumanTransfer.objects.filter(user_id=self.user_id).exists())
        status = self.post("check_human_status", {"user_id": self.user_id})
        self.assertTrue(status.json()["data"]["human_takeover"])

    def test_policy_is_read_from_database(self):
        ShopPolicy.objects.update_or_create(
            policy_type="delivery", defaults={"content": "Livraison test"}
        )
        response = self.post("get_policy", {"policy_type": "delivery"})
        self.assertEqual(response.json()["data"]["content"], "Livraison test")

    @patch("commerce.views.WooCommerceClient")
    def test_modify_order_alias_checks_owner(self, woo_class):
        UserOrder.objects.create(user_id=self.user_id, order_id="77")
        woo_class.return_value.update_order.return_value = {"order_id": "77"}
        response = self.post(
            "modify_order",
            {
                "user_id": self.user_id,
                "order_id": "77",
                "line_items": [{"line_item_id": 4, "quantity": 2}],
            },
        )
        self.assertEqual(response.status_code, 200)
        woo_class.return_value.update_order.assert_called_once_with(
            "77", [{"id": 4, "quantity": 2}]
        )


class CommerceSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    @override_settings(N8N_API_TOKEN="test-secret")
    def test_api_token_is_required_when_configured(self):
        denied = self.client.post(
            "/api/commerce/", {"action": "cart_view", "data": {"user_id": "1"}}, format="json"
        )
        self.assertEqual(denied.status_code, 401)
        allowed = self.client.post(
            "/api/commerce/",
            {"action": "cart_view", "data": {"user_id": "1"}},
            format="json",
            HTTP_X_API_TOKEN="test-secret",
        )
        self.assertEqual(allowed.status_code, 200)

    @override_settings(COMMERCE_RATE_LIMIT=2)
    def test_rate_limit_returns_429(self):
        for _ in range(2):
            response = self.client.post(
                "/api/commerce/", {"action": "cart_view", "data": {"user_id": "1"}}, format="json"
            )
            self.assertEqual(response.status_code, 200)
        blocked = self.client.post(
            "/api/commerce/", {"action": "cart_view", "data": {"user_id": "1"}}, format="json"
        )
        self.assertEqual(blocked.status_code, 429)
