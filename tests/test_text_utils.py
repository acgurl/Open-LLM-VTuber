import re
import unittest

from open_llm_vtuber.utils.audio import new_audio_file_stem
from open_llm_vtuber.utils.text import is_silent_text


class TextUtilsTests(unittest.TestCase):
    def test_detects_silent_text(self):
        for text in ("", "   ", "，。！？", ' "』」）】 '):
            self.assertTrue(is_silent_text(text), text)

    def test_keeps_text_with_content(self):
        for text in ("你好。", "a", "🎉"):
            self.assertFalse(is_silent_text(text), text)

    def test_ellipsis_is_currently_treated_as_speakable(self):
        self.assertFalse(is_silent_text("……"))

    def test_audio_file_stem_is_unique_and_safe(self):
        first = new_audio_file_stem()
        second = new_audio_file_stem()

        self.assertNotEqual(first, second)
        self.assertRegex(first, re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$"))


if __name__ == "__main__":
    unittest.main()
