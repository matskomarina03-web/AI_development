import json
import os
import unittest
from unittest.mock import patch

from app import assistant


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {"SHOP_FAILURE_RATE": "0", "SHOP_DELAY_MS": "0"},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_tool_error_is_returned_to_model_and_tool_time_is_counted(self):
        responses = [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "get_stock",
                                "arguments": '{"sku":"UNKNOWN-SKU"}',
                            },
                        }
                    ],
                },
                "elapsed": 0.1,
                "usage": None,
                "model": "mock-model",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "Товар не знайдено.",
                },
                "elapsed": 0.2,
                "usage": None,
                "model": "mock-model",
            },
        ]
        tool_messages = []

        def fake_chat(**kwargs):
            if len(responses) == 1:
                tool_messages.extend(
                    message
                    for message in kwargs["messages"]
                    if message.get("role") == "tool"
                )
            return responses.pop(0)

        with patch.object(assistant.llm, "chat", side_effect=fake_chat):
            answer = assistant.answer("Перевірте наявність", "C-1001")

        self.assertEqual(answer.stopped, "answer")
        self.assertEqual(answer.rounds, 2)
        self.assertEqual(len(answer.calls), 1)
        self.assertEqual(answer.calls[0].status, "error")
        self.assertEqual(answer.calls[0].result, answer.calls[0].reason)
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(
            json.loads(tool_messages[0]["content"]),
            answer.calls[0].reason,
        )
        self.assertAlmostEqual(answer.elapsed["model"], 0.3)
        self.assertGreaterEqual(answer.elapsed["tools"], 0)

    def test_model_error_includes_both_elapsed_categories(self):
        with patch.object(
            assistant.llm,
            "chat",
            side_effect=assistant.llm.LLMError("mock error"),
        ):
            answer = assistant.answer("Привіт", "C-1001")

        self.assertEqual(answer.stopped, "model_error")
        self.assertEqual(answer.elapsed, {"model": 0, "tools": 0})
