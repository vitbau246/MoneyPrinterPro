"""llm.use_model: chọn model riêng cho một yêu cầu (tuỳ chọn #high của bot Telegram)."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from openai.types.chat import ChatCompletion

from app.config import config
from app.services import llm


def _completion(text: str) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "c", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }],
        }
    )


class FakeOpenAI:
    models: list[str] = []

    def __init__(self, **kwargs):
        self.chat = self
        self.completions = self

    def create(self, model, messages, **kwargs):
        FakeOpenAI.models.append(model)
        return _completion("ok")


class TestModelOverride(unittest.TestCase):
    def setUp(self):
        self.original_app = dict(config.app)
        config.app.update(
            llm_provider="openai", openai_api_key="sk-test", openai_model_name="gpt-6-luna"
        )
        FakeOpenAI.models = []

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app)

    def test_override_applies_only_inside_the_block(self):
        with patch.object(llm, "OpenAI", FakeOpenAI):
            llm._generate_response("a")
            with llm.use_model("gpt-6.1-sol"):
                llm._generate_response("b")
            llm._generate_response("c")

        self.assertEqual(FakeOpenAI.models, ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-luna"])

    def test_override_for_another_provider_is_ignored(self):
        with patch.object(llm, "OpenAI", FakeOpenAI):
            with llm.use_model("gemini-x", provider="gemini"):
                llm._generate_response("a")

        self.assertEqual(FakeOpenAI.models, ["gpt-6-luna"])


if __name__ == "__main__":
    unittest.main()
