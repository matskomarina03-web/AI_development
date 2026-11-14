import json
import os
import unittest
from unittest.mock import patch

from app import tools
from shop import service


class CatalogToolTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {"SHOP_FAILURE_RATE": "0", "SHOP_DELAY_MS": "0"},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        service.reset()

    def call_tool(self, name, arguments):
        result = tools.call(name, json.dumps(arguments, ensure_ascii=False), tools.Context("C-1001"))
        self.assertEqual(result.status, "ok", result.reason)
        return result.content

    def test_search_uses_the_service_summary_fields(self):
        products = self.call_tool("search_products", {"query": "AX3000"})

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["sku"], "ALT-AX3")
        self.assertNotIn("description", products[0])

    def test_product_card_maps_service_weight_and_warranty_fields(self):
        product = self.call_tool("get_product", {"sku": "ALT-AX3"})

        self.assertEqual(product["weight"], 1.1)
        self.assertEqual(product["warranty"], 24)

    def test_stock_maps_expected_restock_and_handles_no_date(self):
        restocking = self.call_tool("get_stock", {"sku": "ORN-PRO"})
        no_restock_date = self.call_tool("get_stock", {"sku": "ALT-M1"})

        self.assertEqual(restocking["incoming"], "2026-10-20")
        self.assertIsNone(no_restock_date["incoming"])

    def test_invalid_search_options_are_rejected_before_service_call(self):
        with patch.object(service, "search_products") as search:
            result = tools.call(
                "search_products",
                '{"query":"роутер","max_price":"безкоштовно"}',
                tools.Context("C-1001"),
            )

        self.assertEqual(result.status, "rejected")
        self.assertIn("max_price", result.content)
        search.assert_not_called()

    def test_delivery_schema_validates_nested_items_and_extra_arguments(self):
        malformed = tools.call(
            "delivery_quote",
            '{"city":"Львів","method":"branch","items":[{"sku":"ALT-AX3","quantity":"1"}]}',
            tools.Context("C-1001"),
        )
        extra = tools.call(
            "get_stock",
            '{"sku":"ORN-PRO","customer_id":"C-1002"}',
            tools.Context("C-1001"),
        )

        self.assertEqual(malformed.status, "rejected")
        self.assertIn("quantity", malformed.content)
        self.assertEqual(extra.status, "rejected")
        self.assertIn("customer_id", extra.content)

    def test_service_unavailable_error_is_returned_as_model_content(self):
        with patch.object(
            service,
            "_service_call",
            side_effect=service.Unavailable("сервіс тимчасово недоступний"),
        ):
            result = tools.call(
                "get_stock",
                '{"sku":"ORN-PRO"}',
                tools.Context("C-1001"),
            )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.content, result.reason)
        self.assertIn("тимчасово недоступний", result.content)


if __name__ == "__main__":
    unittest.main()
