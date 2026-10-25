import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import open_llm_vtuber.utils.tts_preprocessor as preprocessor  # noqa: E402
from open_llm_vtuber.utils.tts_preprocessor import (  # noqa: E402
    markdown_to_plain_text,
    tts_filter,
)


def filter_for_tts(text: str, *, ignore_asterisks: bool = False) -> str:
    return tts_filter(
        text,
        remove_special_char=False,
        ignore_brackets=False,
        ignore_parentheses=False,
        ignore_asterisks=ignore_asterisks,
        ignore_angle_brackets=False,
    )


class MarkdownToPlainTextTests(unittest.TestCase):
    def test_flattens_headings_and_list_markers(self) -> None:
        self.assertEqual(markdown_to_plain_text("## 标题"), "标题")
        self.assertEqual(
            markdown_to_plain_text("- **粗体** 和 *斜体* 和 `code`"),
            "粗体 和 斜体 和 code",
        )

    def test_keeps_link_text_and_drops_images(self) -> None:
        self.assertEqual(
            markdown_to_plain_text("看[这里](https://example.com) 和 ![图](x.png)"),
            "看这里 和",
        )

    def test_removes_html_comments_and_tags(self) -> None:
        self.assertEqual(
            markdown_to_plain_text("A<!-- hidden -->B<span>C</span>"),
            "ABC",
        )
        self.assertEqual(markdown_to_plain_text("A &amp; B"), "A & B")

    def test_can_preserve_single_asterisk_spans(self) -> None:
        self.assertEqual(
            markdown_to_plain_text("*wave* hello", keep_single_asterisk_content=False),
            "*wave* hello",
        )
        self.assertEqual(markdown_to_plain_text("*wave* hello"), "wave hello")

    def test_failed_filter_keeps_the_unfiltered_text(self) -> None:
        with patch.object(
            preprocessor, "filter_brackets", side_effect=RuntimeError("boom")
        ):
            result = tts_filter(
                "[跳过] 保留",
                remove_special_char=False,
                ignore_brackets=True,
                ignore_parentheses=False,
                ignore_asterisks=False,
                ignore_angle_brackets=False,
            )
        self.assertEqual(result, "[跳过] 保留")

    def test_role_play_actions_are_removed_only_when_requested(self) -> None:
        self.assertEqual(filter_for_tts("**你好**", ignore_asterisks=True), "你好")
        self.assertEqual(filter_for_tts("*wave* hello", ignore_asterisks=True), "hello")
        self.assertEqual(
            filter_for_tts("*wave* hello", ignore_asterisks=False),
            "wave hello",
        )


if __name__ == "__main__":
    unittest.main()
