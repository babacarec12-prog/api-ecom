import os
import hashlib
import hmac
from io import StringIO
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from commerce.exceptions import CommerceError
from commerce.paytech_client import PayTechClient
from commerce.woo_client import WooCommerceClient
from commerce.views import (
    ALLOWED_ACTIONS,
    HANDLERS,
    _apply_conversation_rules,
    _conversation_decision,
)
from commerce.models import (
    ApiLog,
    Cart,
    ConversationState,
    HumanTransfer,
    PaymentTransaction,
    ProcessedRequest,
    ProductSelection,
    Product,
    ShopPolicy,
    UserOrder,
)


class ConversationDecisionMatrixTests(SimpleTestCase):
    """Matrice de formulations libres qui ne doivent jamais dépendre de Kimi."""

    def test_thirty_one_natural_decisions(self):
        confirmations = [
            "oui", "ok", "d'accord", "je confirme", "je valide", "valide",
            "vas-y", "allez-y", "c'est bon", "tout est correct",
            "vous pouvez continuer", "on peut continuer", "procédez",
            "faites-le", "fais-le", "go", "waw", "waaw", "c'est correct",
        ]
        refusals = [
            "non", "annule", "annulez", "laisse tomber", "pas maintenant",
            "je refuse", "ne faites pas", "stop", "deedeet", "no",
            "je ne confirme pas", "je ne valide pas",
        ]
        self.assertEqual(len(confirmations) + len(refusals), 31)
        for phrase in confirmations:
            with self.subTest(phrase=phrase):
                self.assertEqual(_conversation_decision(phrase), "confirm")
        for phrase in refusals:
            with self.subTest(phrase=phrase):
                self.assertEqual(_conversation_decision(phrase), "cancel")


class ConversationQualityInvariantTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def post(self, action, data):
        return self.client.post(
            "/api/commerce/", {"action": action, "data": data}, format="json"
        )

    def test_removing_selected_product_clears_stale_context(self):
        Cart.objects.create(
            user_id="quality-remove",
            product_id="DB-001",
            product_name="Batterie",
            quantity=1,
            price="22000",
            platform="database",
        )
        ConversationState.objects.create(
            user_id="quality-remove",
            state="cart_review",
            previous_state="selecting",
            pending_product_id="DB-001",
        )
        response = self.post(
            "cart_remove", {"user_id": "quality-remove", "product_id": "DB-001"}
        )
        state = ConversationState.objects.get(user_id="quality-remove")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(state.pending_product_id)
        self.assertEqual(state.state, "browsing")

    def test_explicit_preference_overrides_previous_selection(self):
        state = ConversationState.objects.create(
            user_id="quality-preference",
            state="cart_review",
            pending_product_id="DB-001",
        )
        result = _apply_conversation_rules(
            {
                "intention": "cart_add",
                "params": {"product_name": "bissap"},
                "confidence": 0.9,
            },
            "je préfère le bissap",
            state,
        )
        self.assertEqual(result["intention"], "get_product")
        self.assertEqual(result["params"], {"product_name": "bissap"})

    def test_delivery_question_is_deterministic(self):
        state = ConversationState.objects.create(user_id="quality-delivery")
        result = _apply_conversation_rules(
            {"intention": "other", "params": {}, "confidence": 0.2},
            "vous livrez à Dakar ?",
            state,
        )
        self.assertEqual(result["intention"], "get_policy")
        self.assertEqual(result["params"], {"policy_type": "delivery"})
        self.assertEqual(result["confidence"], 1)

    def test_wait_not_yet_cancels_pending_confirmation(self):
        self.assertEqual(_conversation_decision("attends, pas encore"), "cancel")

    @patch("commerce.views.KimiClient")
    def test_clear_general_question_is_not_replaced_by_clarification(self, kimi_class):
        kimi_class.return_value.classify.return_value = {
            "intention": "other",
            "params": {},
            "confidence": 0.3,
            "langue_detectee": "français",
            "reformulation": "Le client demande une blague.",
            "reponse_generale": "Avec plaisir : pourquoi le panier était-il heureux ? Il était bien rempli !",
        }
        response = self.post(
            "message_turn",
            {
                "user_id": "quality-general",
                "message_id": "quality-general-1",
                "message": "raconte-moi une blague",
                "naturalize": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("panier", response.json()["data"]["message"])
        self.assertNotIn("préciser", response.json()["data"]["message"].casefold())


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

    def test_unknown_action_uses_error_contract(self):
        response = self.client.post(
            "/api/commerce/", {"action": "delete_order", "data": {}}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"success": False, "error": "Action non reconnue.", "data": {}},
        )

    def test_all_cdc_actions_are_exposed_and_have_handlers(self):
        cdc_actions = {
            "search_products", "get_product", "check_variant_stock",
            "save_selection_list", "get_product_by_position",
            "cart_add", "cart_view", "cart_remove", "cart_update_quantity",
            "cart_clear", "get_state", "set_state", "revert_state",
            "create_order", "get_order_status", "cancel_order", "update_order",
            "get_tracking", "generate_payment", "transfer_to_human",
            "check_human_status", "request_refund", "validate_coupon",
            "get_policy",
        }
        self.assertTrue(cdc_actions.issubset(ALLOWED_ACTIONS))
        self.assertEqual(ALLOWED_ACTIONS, set(HANDLERS))

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
        self.assertEqual(log.error_message, "")
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

    def test_empty_message_uses_conversational_clarification(self):
        response = self.client.post(
            "/api/commerce/",
            {
                "action": "message_turn",
                "data": {"user_id": "empty-message", "message_id": "empty-1", "message": ""},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertIn("préciser", response.json()["data"]["message"].casefold())

    def test_cart_remove_missing_product_is_explicit(self):
        response = self.client.post(
            "/api/commerce/",
            {"action": "cart_remove", "data": {"user_id": "cart-owner", "product_id": "absent"}},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["success"])

    def test_payment_amount_is_validated_before_provider_configuration(self):
        response = self.client.post(
            "/api/commerce/",
            {
                "action": "generate_payment",
                "data": {
                    "user_id": "pay-owner",
                    "order_id": "pay-order",
                    "amount": 0,
                    "idempotency_key": "pay-zero",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertIn("positif", response.json()["error"])

    def test_wrong_order_owner_is_rejected_before_woocommerce_initialization(self):
        UserOrder.objects.create(
            user_id="real-owner", order_id="owned-order", platform="woocommerce"
        )
        response = self.client.post(
            "/api/commerce/",
            {
                "action": "cancel_order",
                "data": {"user_id": "wrong-owner", "order_id": "owned-order"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["success"])
        self.assertNotIn("temporairement", response.json()["error"].casefold())

    @override_settings(COMMERCE_RATE_LIMIT=2)
    def test_rate_limit_is_shared_and_uniform(self):
        for index in range(2):
            response = self.client.post(
                "/api/commerce/",
                {"action": "cart_view", "data": {"user_id": f"rate-{index}"}},
                format="json",
                REMOTE_ADDR="203.0.113.9",
            )
            self.assertEqual(response.status_code, 200)
        blocked = self.client.post(
            "/api/commerce/",
            {"action": "cart_view", "data": {"user_id": "rate-blocked"}},
            format="json",
            REMOTE_ADDR="203.0.113.9",
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(set(blocked.json()), {"success", "error", "data"})

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

    @patch.dict(os.environ, config)
    def test_ipn_hmac_verification(self):
        payload = {"item_price": "8900", "ref_command": "order-456-test"}
        message = b"8900|order-456-test|test-api-key"
        payload["hmac_compute"] = hmac.new(
            b"test-api-secret", message, hashlib.sha256
        ).hexdigest()
        self.assertTrue(PayTechClient().verify_ipn(payload))
        payload["hmac_compute"] = "invalid"
        self.assertFalse(PayTechClient().verify_ipn(payload))


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

    @patch.dict(os.environ, config)
    def test_export_catalogue_includes_images_categories_stock_and_variants(self):
        client = WooCommerceClient()
        client._request = Mock(
            side_effect=[
                [{
                    "id": 18,
                    "name": "T-shirt Sénégal",
                    "description": "Coton",
                    "price": "7500",
                    "stock_quantity": 8,
                    "stock_status": "instock",
                    "status": "publish",
                    "sku": "TS-SN",
                    "categories": [{"name": "Vêtements"}],
                    "images": [{"src": "https://shop.example/tshirt.jpg"}],
                    "variations": [21],
                }],
                [{
                    "id": 21,
                    "sku": "TS-SN-M",
                    "price": "7500",
                    "stock_quantity": 3,
                    "stock_status": "instock",
                    "attributes": [{"name": "Taille", "option": "M"}],
                    "image": {"src": "https://shop.example/tshirt-m.jpg"},
                }],
            ]
        )

        result = client.export_catalogue()

        self.assertEqual(result[0]["external_id"], "18")
        self.assertEqual(result[0]["category"], "Vêtements")
        self.assertEqual(result[0]["images"], ["https://shop.example/tshirt.jpg"])
        self.assertEqual(result[0]["variants"][0]["id"], "21")
        self.assertEqual(result[0]["variants"][0]["stock"], 3)


class WooCommerceCatalogueSyncTests(TestCase):
    @patch("commerce.management.commands.sync_woocommerce_catalog.WooCommerceClient")
    def test_sync_is_idempotent_and_deactivates_missing_products(self, woo_class):
        Product.objects.create(
            external_id="99", name="Ancien produit", price="1000", stock=1,
            platform="woocommerce", active=True,
        )
        woo_class.return_value.export_catalogue.return_value = [{
            "external_id": "18", "name": "T-shirt Sénégal", "description": "Coton",
            "category": "Vêtements", "price": "7500", "stock": 8,
            "sku": "TS-SN", "image_url": "https://shop.example/tshirt.jpg",
            "images": ["https://shop.example/tshirt.jpg"], "variants": [],
            "platform": "woocommerce", "active": True,
        }]

        call_command("sync_woocommerce_catalog", stdout=StringIO())
        call_command("sync_woocommerce_catalog", stdout=StringIO())

        synced = Product.objects.get(external_id="18")
        self.assertEqual(synced.stock, 8)
        self.assertEqual(synced.platform, "woocommerce")
        self.assertFalse(Product.objects.get(external_id="99").active)


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
            "token": "token-77",
            "reference": "order-77-test",
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
        self.assertEqual(PaymentTransaction.objects.get(order_id="77").status, "pending")

    @patch.dict(os.environ, PayTechClientTests.config)
    def test_paytech_ipn_completes_order_and_is_idempotent(self):
        UserOrder.objects.create(
            user_id=self.user_id, order_id="77", amount_total="2500", status="pending"
        )
        ConversationState.objects.create(
            user_id=self.user_id,
            state="payment_pending",
            previous_state="ordering",
            pending_order_id="77",
            pending_amount="2500",
        )
        PaymentTransaction.objects.create(
            user_id=self.user_id,
            order_id="77",
            reference="order-77-ipn",
            token="token-ipn-77",
            payment_url="https://pay.example/77",
            amount="2500",
        )
        payload = {
            "type_event": "sale_complete",
            "item_price": "2500",
            "ref_command": "order-77-ipn",
        }
        message = b"2500|order-77-ipn|test-api-key"
        payload["hmac_compute"] = hmac.new(
            b"test-api-secret", message, hashlib.sha256
        ).hexdigest()

        first = self.client.post("/api/paytech/ipn/", payload, format="json")
        second = self.client.post("/api/paytech/ipn/", payload, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(PaymentTransaction.objects.get(order_id="77").status, "paid")
        self.assertEqual(UserOrder.objects.get(order_id="77").status, "processing")
        self.assertEqual(ConversationState.objects.get(user_id=self.user_id).state, "completed")

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

    def test_confirm_after_product_selection_adds_product_to_cart(self):
        ConversationState.objects.create(
            user_id="selection-confirm-user",
            state="selecting",
            previous_state="browsing",
            pending_product_id="DB-TEST",
        )
        response = self.post(
            "execute_intent",
            {
                "user_id": "selection-confirm-user",
                "intention": "confirm_action",
                "params": {},
                "confidence": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["executed"])
        self.assertEqual(response.json()["data"]["result"]["total"], "5000.00")

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

    @patch("commerce.views.PayTechClient")
    def test_required_catalogue_to_paid_order_flow(self, paytech_class):
        paytech_class.return_value.generate_payment.return_value = {
            "provider": "paytech",
            "reference": "PAY-FLOW-1",
            "token": "token-flow-1",
            "payment_url": "https://paytech.example/pay/token-flow-1",
        }

        def turn(message_id, message):
            return self.post(
                "message_turn",
                {
                    "user_id": "required-flow-user",
                    "session_key": "required-flow",
                    "message_id": message_id,
                    "message": message,
                    "naturalize": False,
                },
            ).json()["data"]

        catalogue = turn("required-1", "montre les produits")
        self.assertEqual(catalogue["analysis"]["intention"], "search_products")
        self.assertIn("2. Bissap naturel 1 litre", catalogue["message"])

        added = turn("required-2", "je prends le 2")
        self.assertEqual(added["analysis"]["intention"], "cart_add")
        self.assertEqual(added["commerce"]["result"]["total"], "2500.00")
        self.assertEqual(Cart.objects.get(user_id="required-flow-user").product_name, "Bissap naturel 1 litre")

        summary = turn("required-3", "commander")
        self.assertEqual(summary["analysis"]["intention"], "create_order")
        self.assertTrue(summary["commerce"]["requires_confirmation"])
        self.assertIn("Bissap naturel 1 litre", summary["message"])
        self.assertIn("2 500", summary["message"])

        confirmed = turn("required-4", "oui")
        self.assertEqual(confirmed["analysis"]["intention"], "confirm_action")
        self.assertIn("https://paytech.example/pay/token-flow-1", confirmed["message"])
        self.assertTrue(UserOrder.objects.filter(user_id="required-flow-user").exists())
        self.assertFalse(Cart.objects.filter(user_id="required-flow-user").exists())

    def test_selection_arbitration_is_semantic_not_phrase_specific(self):
        variants = ["ajoute le numéro 2", "je choisis le 2", "achète le 2"]
        for index, phrase in enumerate(variants, start=1):
            user_id = f"selection-variant-{index}"
            self.post(
                "execute_intent",
                {
                    "user_id": user_id,
                    "session_key": user_id,
                    "intention": "search_products",
                    "params": {"query": "*"},
                    "confidence": 1,
                },
            )
            state = ConversationState.objects.get(user_id=user_id)
            analysis = _apply_conversation_rules(
                {"intention": "get_product", "params": {}, "confidence": 0.8},
                phrase,
                state,
            )
            self.assertEqual(analysis["intention"], "cart_add")
            self.assertEqual(analysis["params"]["position"], 2)

    def test_message_turn_uses_supplied_kimi_analysis_and_resolves_product_name(self):
        response = self.post(
            "message_turn",
            {
                "user_id": "natural-cart-user",
                "session_key": "natural-cart",
                "message_id": "natural-cart-1",
                "message": "ajoute-moi le Produit Test Dakar",
                "naturalize": False,
                "analysis": {
                    "intention": "cart_add",
                    "params": {"product_name": "Produit Test Dakar", "quantity": 1},
                    "confidence": 0.97,
                    "langue_detectee": "français",
                    "reformulation": "Ajouter le produit au panier.",
                },
            },
        )
        payload = response.json()["data"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["analysis"]["intention"], "cart_add")
        self.assertIn("Produit Test Dakar", payload["message"])
        self.assertEqual(Cart.objects.get(user_id="natural-cart-user").quantity, 1)

    def test_message_turn_context_corrects_vague_analysis_for_number_selection(self):
        self.post(
            "message_turn",
            {
                "user_id": "context-user",
                "session_key": "context",
                "message_id": "context-1",
                "message": "Produit Test Dakar",
                "naturalize": False,
                "analysis": {
                    "intention": "search_products",
                    "params": {"query": "Produit Test Dakar"},
                    "confidence": 0.98,
                },
            },
        )
        response = self.post(
            "message_turn",
            {
                "user_id": "context-user",
                "session_key": "context",
                "message_id": "context-2",
                "message": "1",
                "naturalize": False,
                "analysis": {"intention": "other", "params": {}, "confidence": 0.4},
            },
        )
        payload = response.json()["data"]
        self.assertEqual(payload["analysis"]["intention"], "get_product")
        self.assertIn("Produit Test Dakar", payload["message"])

    def test_single_search_result_supports_natural_pronoun_addition(self):
        searched = self.post(
            "message_turn",
            {
                "user_id": "pronoun-user",
                "session_key": "pronoun",
                "message_id": "pronoun-1",
                "message": "vous avez le Produit Test Dakar ?",
                "naturalize": False,
                "analysis": {
                    "intention": "search_products",
                    "params": {"query": "Produit Test Dakar"},
                    "confidence": 0.99,
                },
            },
        )
        self.assertEqual(
            searched.json()["data"]["commerce"]["state"]["pending_product_id"],
            "DB-TEST",
        )
        response = self.post(
            "message_turn",
            {
                "user_id": "pronoun-user",
                "session_key": "pronoun",
                "message_id": "pronoun-2",
                "message": "ajoutez-le au panier",
                "naturalize": False,
                "analysis": {"intention": "cart_add", "params": {}, "confidence": 0.96},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Produit Test Dakar", response.json()["data"]["message"])
        self.assertEqual(Cart.objects.get(user_id="pronoun-user").quantity, 1)

    @patch("commerce.views.PayTechClient")
    def test_natural_confirmation_then_payment_uses_active_order(self, paytech_class):
        generate_payment = paytech_class.return_value.generate_payment
        generate_payment.return_value = {
            "provider": "paytech",
            "reference": "PAY-NATURAL-1",
            "token": "token-natural-1",
            "payment_url": "https://paytech.example/pay/token-natural-1",
        }
        Cart.objects.create(
            user_id="natural-order-user",
            product_id="DB-TEST",
            product_name="Produit Test Dakar",
            quantity=1,
            price="5000",
            platform="database",
        )

        staged = self.post(
            "message_turn",
            {
                "user_id": "natural-order-user",
                "session_key": "natural-order",
                "message_id": "natural-order-1",
                "message": "je veux commander",
                "naturalize": False,
                "analysis": {"intention": "create_order", "params": {}, "confidence": 0.98},
            },
        ).json()["data"]
        self.assertTrue(staged["commerce"]["requires_confirmation"])

        confirmed = self.post(
            "message_turn",
            {
                "user_id": "natural-order-user",
                "session_key": "natural-order",
                "message_id": "natural-order-2",
                "message": "tout est correct",
                "naturalize": False,
                "analysis": {"intention": "other", "params": {}, "confidence": 0.9},
            },
        ).json()["data"]
        self.assertEqual(confirmed["analysis"]["intention"], "confirm_action")
        order_id = confirmed["commerce"]["result"]["order_id"]
        self.assertIn(order_id, confirmed["message"])

        payment = self.post(
            "message_turn",
            {
                "user_id": "natural-order-user",
                "session_key": "natural-order",
                "message_id": "natural-order-3",
                "message": "je dois payer non ?",
                "naturalize": False,
                "analysis": {"intention": "other", "params": {}, "confidence": 0.8},
            },
        ).json()["data"]
        self.assertEqual(payment["analysis"]["intention"], "generate_payment")
        self.assertIn("https://paytech.example/pay/token-natural-1", payment["message"])
        self.assertEqual(generate_payment.call_count, 1)
        self.assertEqual(generate_payment.call_args.args[0], order_id)
        self.assertEqual(str(generate_payment.call_args.args[1]), "5000.00")

    def test_cart_keeps_variants_as_distinct_lines(self):
        product = Product.objects.get(external_id="DB-TEST")
        product.variants = [
            {"id": "M", "prix": "5000", "stock": 3, "en_stock": True,
             "attributs": [{"name": "Taille", "option": "M"}]},
            {"id": "L", "prix": "5500", "stock": 2, "en_stock": True,
             "attributs": [{"name": "Taille", "option": "L"}]},
        ]
        product.save(update_fields=["variants", "updated_at"])

        for variant_id in ("M", "L"):
            response = self.post(
                "execute_intent",
                {
                    "user_id": self.user_id,
                    "intention": "cart_add",
                    "params": {
                        "product_id": "DB-TEST",
                        "variant_id": variant_id,
                        "quantity": 1,
                    },
                    "confidence": 1,
                },
            )
            self.assertEqual(response.status_code, 200)

        cart = self.post("cart_view", {"user_id": self.user_id}).json()["data"]
        self.assertEqual(len(cart["items"]), 2)
        self.assertEqual({item["variant_id"] for item in cart["items"]}, {"M", "L"})
        self.assertEqual(cart["total"], "10500.00")

        ambiguous = self.post(
            "cart_update_quantity",
            {"user_id": self.user_id, "product_id": "DB-TEST", "quantity": 2},
        )
        self.assertEqual(ambiguous.status_code, 400)
        updated = self.post(
            "cart_update_quantity",
            {
                "user_id": self.user_id,
                "product_id": "DB-TEST",
                "variant_id": "L",
                "quantity": 2,
            },
        )
        self.assertEqual(updated.status_code, 200)


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
        self.assertEqual(payload["chat_id"], self.user_id)
        self.assertEqual(payload["session_id"], "whatsapp-test")
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
    def test_catalogue_uses_local_fallback_when_kimi_is_unavailable(self, kimi_class, woo_class):
        kimi_class.return_value.classify.side_effect = CommerceError("Kimi indisponible", 502)
        woo_class.return_value.search_products.return_value = [
            {"id": "10", "nom": "Batterie externe", "prix": "22000", "stock": 3}
        ]
        payload = self.post_message("montre moi les produits").json()["data"]
        self.assertTrue(payload["degraded"])
        self.assertIn("Batterie externe", payload["message"])
        kimi_class.return_value.classify.assert_called_once()
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

    @patch("commerce.views.WooCommerceClient")
    @patch("commerce.views.KimiClient")
    def test_second_turn_kimi_receives_persisted_history_and_state(self, kimi_class, woo_class):
        kimi_class.return_value.classify.side_effect = [
            {
                "intention": "search_products",
                "params": {"query": "batterie"},
                "confidence": 0.98,
                "langue_detectee": "français",
                "reformulation": "Le client cherche une batterie.",
            },
            {
                "intention": "cart_add",
                "params": {},
                "confidence": 0.97,
                "langue_detectee": "français",
                "reformulation": "Ajouter le produit sélectionné.",
            },
        ]
        product = {"id": "10", "nom": "Batterie externe", "prix": "22000", "stock": 3}
        woo_class.return_value.search_products.return_value = [product]
        woo_class.return_value.get_product.return_value = product

        self.post_message("batterie", message_id="history-1")
        second = self.post_message("ajoute-la", message_id="history-2").json()["data"]

        self.assertEqual(second["analysis"]["intention"], "cart_add")
        second_context = kimi_class.return_value.classify.call_args_list[1].args[1]
        self.assertEqual(second_context["recent_messages"][0]["content"], "batterie")
        self.assertIn("Batterie externe", second_context["recent_messages"][1]["content"])
        self.assertEqual(second_context["state"]["pending_product_id"], "10")
        state = ConversationState.objects.get(user_id=self.user_id)
        self.assertEqual(len(state.recent_messages), 4)

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
