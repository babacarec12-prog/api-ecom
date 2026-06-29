from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIClient


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
