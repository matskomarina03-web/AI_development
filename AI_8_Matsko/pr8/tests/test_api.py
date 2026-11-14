import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import assistant, main


class AskApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_blank_question_is_rejected_before_assistant(self):
        with patch.object(main.assistant, "answer") as answer:
            response = self.client.post(
                "/api/ask",
                json={"customer_id": "C-1001", "question": "   "},
            )

        self.assertEqual(response.status_code, 422)
        answer.assert_not_called()

    def test_unknown_customer_is_rejected_before_assistant(self):
        with patch.object(main.assistant, "answer") as answer:
            response = self.client.post(
                "/api/ask",
                json={"customer_id": "UNKNOWN", "question": "Де замовлення?"},
            )

        self.assertEqual(response.status_code, 404)
        answer.assert_not_called()

    def test_valid_request_is_trimmed_and_serialized(self):
        expected = assistant.Answer(text="mock answer")
        with patch.object(main.assistant, "answer", return_value=expected) as answer:
            response = self.client.post(
                "/api/ask",
                json={"customer_id": " C-1001 ", "question": "  Де замовлення?  "},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "mock answer")
        answer.assert_called_once_with("Де замовлення?", "C-1001")


if __name__ == "__main__":
    unittest.main()
