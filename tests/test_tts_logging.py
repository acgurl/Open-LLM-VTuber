import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class FishKeyLoggingTests(unittest.TestCase):
    def test_api_key_is_not_logged(self):
        fake_sdk = types.ModuleType("fish_audio_sdk")
        fake_sdk.Session = Mock()
        fake_sdk.TTSRequest = Mock()
        sys.modules.pop("open_llm_vtuber.tts.fish_api_tts", None)

        messages = []
        with patch.dict(sys.modules, {"fish_audio_sdk": fake_sdk}):
            module = importlib.import_module("open_llm_vtuber.tts.fish_api_tts")
            handler_id = logger.add(
                lambda message: messages.append(str(message)),
                level="INFO",
            )
            try:
                module.TTSEngine(api_key="fish-secret-key")
            finally:
                logger.remove(handler_id)

        self.assertNotIn("fish-secret-key", "\n".join(messages))


if __name__ == "__main__":
    unittest.main()
