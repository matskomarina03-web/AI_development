import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import APIStatusError, AuthenticationError

from app import llm


def api_error(error_type, status_code):
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(status_code, request=request)
    return error_type("provider error", response=response, body=None)


class LLMTests(unittest.TestCase):
    def test_authentication_error_is_not_retried(self):
        create = Mock(side_effect=api_error(AuthenticationError, 401))
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        with patch.object(llm, "get_client", return_value=client):
            with self.assertRaises(llm.LLMAuthError):
                llm.ask("Question", "Rules")

        create.assert_called_once()

    def test_temporary_server_error_is_retried(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Answer"))],
            usage=None,
        )
        create = Mock(side_effect=[api_error(APIStatusError, 500), response])
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        with patch.object(llm, "get_client", return_value=client), patch.object(llm.time, "sleep"):
            result = llm.ask("Question", "Rules")

        self.assertEqual(result["answer"], "Answer")
        self.assertEqual(create.call_count, 2)

    def test_support_schedule_is_taken_from_context(self):
        context = "Підтримка працює щодня з 10:00 до 15:00."

        messages = llm.build_messages("Question", context)

        self.assertIn(context, messages[1]["content"])
        self.assertNotIn("9:00–18:00", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
