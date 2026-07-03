import os
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from commerce.exceptions import CommerceError
from commerce.paytech_client import PayTechClient
from commerce.woo_client import WooCommerceClient
from commerce.models import (
    ApiLog,
    Cart,
    ConversationState,
    HumanTransfer,
    ProcessedRequest,
    ProductSelection,
    Product,
    ShopPolicy,
    UserOrder,
)


class CommerceEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_endpoint_is_public(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

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

    def test_unknown_action_returns_available_actions(self):
        response = self.client.post(
            "/api/commerce/", {"action": "delete_order", "data": {}}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["data"]["message"], "Action non reconnue")
        self.assertIn("search_products", response.json()["data"]["available_actions"])

    def test_get_method_uses_error_contract(self):
        response = self.client.get("/api/commerce/")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(set(response.json()), {"success", "error", "data"})

    def test_malformed_json_uses_error_contract(self):
        response = self.client.post(
            "/api/commerce/", data="{", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"success", "error", "data"})

    def test_api_call_is_logged(self):
        response = self.client.post(
            "/api/commerce/",
            {"action": "cart_view", "data": {"user_id": "log-user"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        log = ApiLog.objects.get(user_id="log-user", action="cart_view")
        self.assertTrue(log.success)
        self.assertGreaterEqual(log.duration_ms, 0)

    def test_unknown_user_has_empty_cart_default_state_and_no_human(self):
        cart = self.client.post(
            "/api/commerce/",
            {"action": "cart_view", "data": {"user_id": "new-user"}},
            format="json",
        )
        state = self.client.post(
            "/api/commerce/",
            {"action": "get_state", "data": {"user_id": "new-user"}},
            format="json",
        )
        human = self.client.post(
            "/api/commerce/",
            {"action": "check_human_status", "data": {"user_id": "new-user"}},
            format="json",
        )
        self.assertEqual(cart.json()["data"]["items"], [])
        self.assertEqual(state.json()["data"]["state"], "browsing")
        self.assertFalse(human.json()["data"]["human_active"])

    def test_missing_parameter_has_explicit_uniform_error(self):
        response = self.client.post(
            "/api/commerce/",
            {"action": "cart_add", "data": {"user_id": "missing-field"}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"success": False, "error": "Paramètre manquant: product_id", "data": {}},
        )

    @patch("commerce.views.HANDLERS")
    def test_woocommerce_failure_is_normalized(self, handlers):
        handlers.__getitem__.return_value.side_effect = CommerceError(
            "WooCommerce est inaccessible : timeout", 502
        )
        response = self.client.post(
            "/api/commerce/",
            {"action": "get_product", "data": {"product_id": "1"}},
            format="json",
        )
        self.assertEqual(response.json()["error"], "Boutique temporairement inaccessible")
        self.assertEqual(response.json()["data"], {})

    @patch("commerce.views.HANDLERS")
    def test_unexpected_exception_never_returns_http_500(self, handlers):
        handlers.__getitem__.return_value.side_effect = RuntimeError("boom")
        response = self.client.post(
            "/api/commerce/",
            {"action": "get_state", "data": {"user_id": "unexpected"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"success": False, "error": "Erreur inattendue, réessayez", "data": {}},
        )

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

    @patch("commerce.views.WooCommerceClient")
    def test_execute_intent_uses_kimi_intention_without_raw_message(self, woo_class):
        woo_class.return_value.search_products.return_value = [
            {"id": "10", "nom": "Batterie externe", "prix": "22000", "stock": 13}
        ]
        response = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "session_key": "kimi-session",
                "intention": "search_products",
                "params": {"query": "batterie"},
                "confidence": 0.98,
                "reformulation": "Le client cherche une batterie.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["executed"])
        woo_class.return_value.search_products.assert_called_once_with("batterie")
        self.assertEqual(ProductSelection.objects.get(user_id=self.user_id).product_id, "10")

    def test_execute_intent_rejects_unknown_kimi_intention(self):
        response = self.post(
            "execute_intent",
            {"user_id": self.user_id, "intention": "delete_everything", "params": {}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])

    @patch("commerce.views.WooCommerceClient")
    def test_execute_intent_stages_and_confirms_order(self, woo_class):
        woo_class.return_value.create_order.return_value = {
            "order_id": "88",
            "montant_total": "5000",
            "devise": "XOF",
            "plateforme": "woocommerce",
        }
        Cart.objects.create(
            user_id=self.user_id,
            product_id="18",
            product_name="Bissap",
            quantity=2,
            price="2500",
        )
        staged = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "create_order",
                "params": {},
                "confidence": 0.99,
                "timestamp": "turn-1",
            },
        )
        self.assertFalse(staged.json()["data"]["executed"])
        self.assertTrue(staged.json()["data"]["requires_confirmation"])
        state = ConversationState.objects.get(user_id=self.user_id)
        self.assertEqual(state.pending_action, "create_order")
        self.assertEqual(state.state, "confirming")
        woo_class.return_value.create_order.assert_not_called()

        confirmed = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "confirm_action",
                "params": {},
                "confidence": 0.99,
            },
        )
        self.assertTrue(confirmed.json()["data"]["executed"])
        self.assertEqual(confirmed.json()["data"]["confirmed_action"], "create_order")
        self.assertEqual(confirmed.json()["data"]["result"]["order_id"], "88")
        state.refresh_from_db()
        self.assertIsNone(state.pending_action)
        self.assertEqual(state.pending_order_id, "88")

    @patch("commerce.views.WooCommerceClient")
    def test_sensitive_order_actions_wait_for_confirmation(self, woo_class):
        UserOrder.objects.create(user_id=self.user_id, order_id="77")
        ConversationState.objects.create(
            user_id=self.user_id,
            state="ordering",
            previous_state="confirming",
            pending_order_id="77",
            pending_amount="2500",
        )
        woo_class.return_value.cancel_order.return_value = {
            "order_id": "77", "statut": "annulee", "plateforme": "woocommerce"
        }
        staged = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "cancel_order",
                "params": {"reason": "Erreur client"},
                "timestamp": "turn-2",
            },
        )
        self.assertTrue(staged.json()["data"]["requires_confirmation"])
        self.assertEqual(staged.json()["data"]["confirmation"]["order_id"], "77")
        woo_class.return_value.cancel_order.assert_not_called()
        confirmed = self.post(
            "execute_intent",
            {"user_id": self.user_id, "intention": "confirm", "params": {}},
        )
        self.assertTrue(confirmed.json()["data"]["executed"])
        woo_class.return_value.cancel_order.assert_called_once_with(
            "77", "Erreur client", self.user_id
        )

    def test_pending_action_can_be_refused(self):
        Cart.objects.create(
            user_id=self.user_id,
            product_id="18",
            product_name="Bissap",
            quantity=1,
            price="2500",
        )
        self.post(
            "execute_intent",
            {"user_id": self.user_id, "intention": "create_order", "params": {}},
        )
        refused = self.post(
            "execute_intent",
            {"user_id": self.user_id, "intention": "cancel_pending_action", "params": {}},
        )
        self.assertEqual(refused.json()["data"]["cancelled_action"], "create_order")
        state = ConversationState.objects.get(user_id=self.user_id)
        self.assertIsNone(state.pending_action)
        self.assertEqual(state.state, "browsing")

    @patch("commerce.views.WooCommerceClient")
    def test_low_confidence_never_calls_commerce_provider(self, woo_class):
        response = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "search_products",
                "params": {"query": "telephone"},
                "confidence": 0.2,
            },
        )
        self.assertTrue(response.json()["data"]["requires_clarification"])
        woo_class.assert_not_called()

    @patch("commerce.views.WooCommerceClient")
    def test_coupon_variant_and_policy_parameters_are_executable(self, woo_class):
        woo_class.return_value.validate_coupon.return_value = {"code": "PROMO", "valide": True}
        woo_class.return_value.check_variant_stock.return_value = {
            "product_id": "10", "variant_id": "11", "en_stock": True
        }
        coupon = self.post(
            "execute_intent",
            {"user_id": self.user_id, "intention": "validate_coupon", "params": {"code": "PROMO"}},
        )
        variant = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "check_variant_stock",
                "params": {"product_id": "10", "variant_id": "11"},
            },
        )
        ShopPolicy.objects.update_or_create(
            policy_type="delivery", defaults={"content": "Livraison sous 48 h"}
        )
        policy = self.post(
            "execute_intent",
            {"user_id": self.user_id, "intention": "get_policy", "params": {"policy_type": "livraison"}},
        )
        self.assertTrue(coupon.json()["data"]["executed"])
        self.assertTrue(variant.json()["data"]["result"]["en_stock"])
        self.assertEqual(policy.json()["data"]["result"]["policy_type"], "delivery")

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


@override_settings(COMMERCE_CATALOG_PROVIDER="database")
class DatabaseCatalogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user_id = "221700000077"
        Product.objects.create(
            external_id="DB-TEST",
            name="Produit Test Dakar",
            description="Produit réservé aux tests du catalogue interne.",
            category="Test",
            price="5000",
            stock=5,
            sku="TEST-001",
        )

    def post(self, action, data):
        return self.client.post(
            "/api/commerce/", {"action": action, "data": data}, format="json"
        )

    def test_database_catalog_cart_and_order_flow(self):
        search = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "session_key": "db-test",
                "intention": "search_products",
                "params": {"query": "Produit Test Dakar"},
                "confidence": 1,
            },
        )
        self.assertEqual(search.status_code, 200)
        products = search.json()["data"]["result"]["products"]
        self.assertEqual(products[0]["id"], "DB-TEST")

        selected = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "get_product",
                "params": {"position": 1},
                "confidence": 1,
            },
        )
        self.assertEqual(
            selected.json()["data"]["result"]["selected_product"]["product_id"],
            "DB-TEST",
        )

        added = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "cart_add",
                "params": {"quantity": 2},
                "confidence": 1,
            },
        )
        self.assertEqual(added.json()["data"]["result"]["total"], "10000.00")

        staged = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "create_order",
                "params": {},
                "confidence": 1,
                "timestamp": "db-order-1",
            },
        )
        self.assertTrue(staged.json()["data"]["requires_confirmation"])
        confirmed = self.post(
            "execute_intent",
            {
                "user_id": self.user_id,
                "intention": "confirm_action",
                "params": {},
                "confidence": 1,
            },
        )
        result = confirmed.json()["data"]["result"]
        self.assertTrue(result["order_id"].startswith("DB-"))
        self.assertEqual(result["montant_total"], "10000.00")
        self.assertEqual(Product.objects.get(external_id="DB-TEST").stock, 3)
        self.assertTrue(
            UserOrder.objects.filter(order_id=result["order_id"], platform="database").exists()
        )

    def test_full_message_flow_is_idempotent_and_clears_cart(self):
        def turn(message_id, message):
            return self.post(
                "message_turn",
                {
                    "user_id": "full-message-db-user",
                    "session_key": "full-message-db",
                    "message_id": message_id,
                    "message": message,
                },
            )

        self.assertEqual(turn("m1", "Produit Test Dakar").status_code, 200)
        selected = turn("m2", "1")
        self.assertIn("Produit Test Dakar", selected.json()["data"]["message"])
        self.assertEqual(turn("m3", "oui").status_code, 200)
        staged = turn("m4", "je le commande")
        self.assertIn("confirmer", staged.json()["data"]["message"].casefold())
        confirmed = turn("m5", "oui")
        self.assertEqual(confirmed.status_code, 200)
        repeated = turn("m5", "oui")
        self.assertEqual(repeated.json()["data"], confirmed.json()["data"])
        self.assertEqual(Product.objects.get(external_id="DB-TEST").stock, 4)
        self.assertFalse(Cart.objects.filter(user_id="full-message-db-user").exists())


class MessageTurnTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user_id = "221700000099"

    def post_message(self, message, **extra):
        return self.client.post(
            "/api/commerce/",
            {
                "action": "message_turn",
                "data": {
                    "user_id": self.user_id,
                    "session_key": "whatsapp-test",
                    "message_id": "message-1",
                    "message": message,
                    **extra,
                },
            },
            format="json",
        )

    @patch("commerce.views.KimiClient")
    def test_basic_greeting_is_immediate_and_french(self, kimi_class):
        response = self.post_message("nanga def")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("Bonjour", payload["message"])
        self.assertFalse(payload["silent"])
        self.assertEqual(payload["trace_id"], "message-1")
        kimi_class.assert_not_called()

    @override_settings(KIMI_NATURAL_RESPONSES=True)
    @patch("commerce.views.KimiClient")
    def test_basic_greeting_never_waits_for_kimi(self, kimi_class):
        payload = self.post_message("bonjour").json()["data"]
        repeated = self.post_message("bonjour").json()["data"]
        self.assertIn("Bonjour", payload["message"])
        self.assertEqual(repeated["message"], payload["message"])
        kimi_class.assert_not_called()

    @override_settings(KIMI_NATURAL_RESPONSES=True)
    @patch("commerce.views.KimiClient")
    def test_basic_greeting_ignores_formulation_error(self, kimi_class):
        kimi_class.return_value.formulate.side_effect = ValueError("format error")
        response = self.post_message("bonjour")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("Bonjour", payload["message"])
        self.assertFalse(payload["degraded"])
        kimi_class.assert_not_called()

    def test_wolof_number_selection_is_not_treated_as_quantity(self):
        ConversationState.objects.create(
            user_id=self.user_id, state="selecting", previous_state="browsing"
        )
        ProductSelection.objects.create(
            user_id=self.user_id,
            session_key="whatsapp-test",
            position=5,
            product_id="DB-005",
            product_name="T-shirt coton Sénégal",
            price="7500",
        )
        payload = self.post_message("5 bi nekh nama").json()["data"]
        self.assertEqual(payload["analysis"]["intention"], "get_product")
        self.assertEqual(payload["analysis"]["params"], {"position": 5})
        self.assertIn("T-shirt coton Sénégal", payload["message"])

    @patch("commerce.views.WooCommerceClient")
    @patch("commerce.views.KimiClient")
    def test_wolof_is_understood_but_answer_is_french(self, kimi_class, woo_class):
        kimi_class.return_value.classify.return_value = {
            "intention": "search_products",
            "params": {"query": "bissap"},
            "confidence": 0.97,
            "langue_detectee": "wolof_mix",
            "reformulation": "Le client cherche du bissap.",
        }
        woo_class.return_value.search_products.return_value = [
            {"id": "18", "nom": "Bissap naturel", "prix": "2500", "stock": 10}
        ]
        payload = self.post_message("dama bëgg bissap").json()["data"]
        self.assertIn("Voici les produits disponibles", payload["message"])
        self.assertIn("Bissap naturel", payload["message"])
        self.assertNotIn("dama", payload["message"].casefold())
        self.assertEqual(payload["analysis"]["langue_detectee"], "wolof_mix")

    @patch("commerce.views.WooCommerceClient")
    @patch("commerce.views.KimiClient")
    def test_catalogue_uses_fast_local_path_without_kimi(self, kimi_class, woo_class):
        kimi_class.return_value.classify.side_effect = CommerceError("Kimi indisponible", 502)
        woo_class.return_value.search_products.return_value = [
            {"id": "10", "nom": "Batterie externe", "prix": "22000", "stock": 3}
        ]
        payload = self.post_message("montre moi les produits").json()["data"]
        self.assertFalse(payload["degraded"])
        self.assertIn("Batterie externe", payload["message"])
        kimi_class.assert_not_called()
        woo_class.return_value.search_products.assert_called_once_with("*")

    @patch("commerce.views.KimiClient")
    def test_general_kimi_reply_is_forwarded_in_french(self, kimi_class):
        kimi_class.return_value.classify.return_value = {
            "intention": "other",
            "params": {},
            "confidence": 0.9,
            "langue_detectee": "wolof_mix",
            "reformulation": "Le client demande comment ça va.",
            "reponse_generale": "Je vais très bien, merci ! Comment puis-je vous aider ?",
        }
        payload = self.post_message("naka nga def tey").json()["data"]
        self.assertEqual(
            payload["message"],
            "Je vais très bien, merci ! Comment puis-je vous aider ?",
        )

    def test_human_takeover_keeps_the_bot_silent(self):
        ConversationState.objects.create(user_id=self.user_id, state="human_takeover")
        payload = self.post_message("bonjour").json()["data"]
        self.assertTrue(payload["silent"])
        self.assertIsNone(payload["message"])


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

    @override_settings(N8N_API_TOKEN="", COMMERCE_RATE_LIMIT=2)
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
