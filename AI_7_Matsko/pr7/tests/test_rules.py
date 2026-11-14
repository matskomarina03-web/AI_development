import unittest
from unittest.mock import patch

from app.rules import check


class CheckRulesTests(unittest.TestCase):
    def setUp(self):
        self.company = {
            "name": "ТОВ «Сузірʼя Рітейл»",
            "code": "44172914",
        }
        self.suppliers = [
            {
                "name": "ТОВ «Оріон Аудіо Дистрибуція»",
                "code": "38124779",
                "iban": "UA663510050000026004017723561",
                "vat_payer": True,
            }
        ]
        self.document = {
            "document_type": "invoice",
            "invoice_number": "1",
            "date": "2025-01-01",
            "supplier": {
                "name": "ТОВ «Оріон Аудіо Дистрибуція»",
                "code": "38124779",
                "iban": "UA663510050000026004017723561",
            },
            "buyer": {
                "name": "ТОВ «Сузірʼя Рітейл»",
                "code": "44172914",
            },
            "items": [
                {
                    "quantity": "2",
                    "price": "12,50",
                    "amount": "25,00",
                }
            ],
            "total_without_vat": "25,00",
            "vat": "5,00",
            "total_due": "30,00",
        }
        self.reference = patch(
            "app.rules.load_reference",
            return_value=(self.company, self.suppliers),
        )
        self.reference.start()
        self.addCleanup(self.reference.stop)

    def test_comma_decimal_amounts_are_checked(self):
        issues = check(self.document)
        rules = {issue.rule for issue in issues}

        self.assertNotIn("number", rules)
        self.assertNotIn("arithmetic", rules)
        self.assertNotIn("vat", rules)
        self.assertNotIn("iban_checksum", rules)
        self.assertNotIn("edrpou_checksum", rules)

    def test_invalid_iban_and_edrpou_check_digits_are_reported(self):
        self.document["supplier"]["iban"] = "UA663510050000026004017723562"
        self.document["supplier"]["code"] = "38124770"
        self.document["buyer"]["code"] = "44172915"

        issues = check(self.document)
        failures = {(issue.field, issue.rule) for issue in issues}

        self.assertIn(("supplier.iban", "iban_checksum"), failures)
        self.assertIn(("supplier.code", "edrpou_checksum"), failures)
        self.assertIn(("buyer.code", "edrpou_checksum"), failures)

    def test_edrpou_checksum_fallback_is_supported(self):
        self.document["buyer"]["code"] = "00000035"

        issues = check(self.document)

        self.assertNotIn(
            ("buyer.code", "edrpou_checksum"),
            {(issue.field, issue.rule) for issue in issues},
        )

    def test_invalid_comma_decimal_is_reported_instead_of_skipping_arithmetic(self):
        self.document["total_without_vat"] = "25,00,00"

        issues = check(self.document)
        failures = {(issue.field, issue.rule) for issue in issues}

        self.assertIn(("total_without_vat", "number"), failures)


if __name__ == "__main__":
    unittest.main()
