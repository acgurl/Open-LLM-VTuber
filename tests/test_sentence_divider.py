import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from open_llm_vtuber.utils.sentence_divider import SentenceDivider
except ImportError as exc:
    raise unittest.SkipTest(f"Full runtime dependencies are unavailable: {exc}")


async def _stream(items):
    for item in items:
        yield item


async def _collect(divider, items):
    outputs = []
    async for output in divider.process_stream(_stream(items)):
        outputs.append(output)
    return outputs


class SentenceDividerTests(unittest.IsolatedAsyncioTestCase):
    async def test_splits_first_sentence_at_comma(self):
        divider = SentenceDivider(faster_first_response=True, segment_method="regex")

        outputs = await _collect(divider, ["你好，世界。", "第二句！"])

        self.assertEqual(
            [item.text for item in outputs], ["你好，", "世界。", "第二句！"]
        )

    async def test_emits_tag_start_inside_and_end_markers(self):
        divider = SentenceDivider(faster_first_response=False, segment_method="regex")

        outputs = await _collect(divider, ["<think>内", "部</think>回答。"])

        self.assertEqual(
            [
                (item.text, item.tags[0].name, item.tags[0].state.value)
                for item in outputs
            ],
            [
                ("<think>", "think", "start"),
                ("内部", "think", "inside"),
                ("</think>", "think", "end"),
                ("回答。", "", "none"),
            ],
        )

    async def test_splits_multiple_sentences_and_flushes_tail(self):
        divider = SentenceDivider(faster_first_response=False, segment_method="regex")

        outputs = await _collect(divider, ["a.b.c."])

        self.assertEqual([item.text for item in outputs], ["a.", "b.", "c."])

        divider = SentenceDivider(faster_first_response=False, segment_method="regex")
        outputs = await _collect(divider, ["abc"])
        self.assertEqual([item.text for item in outputs], ["abc"])

    async def test_tag_in_middle_splits_preceding_text(self):
        divider = SentenceDivider(faster_first_response=False, segment_method="regex")

        outputs = await _collect(divider, ["前文<think>思考</think>后文。"])

        self.assertEqual(
            [
                (item.text, item.tags[0].name, item.tags[0].state.value)
                for item in outputs
            ],
            [
                ("前文", "", "none"),
                ("<think>", "think", "start"),
                ("思考", "think", "inside"),
                ("</think>", "think", "end"),
                ("后文。", "", "none"),
            ],
        )

    async def test_passes_dicts_through_and_keeps_buffered_text(self):
        divider = SentenceDivider(faster_first_response=False, segment_method="regex")

        outputs = await _collect(
            divider,
            ["abc", {"type": "tool_call_status"}, "def。"],
        )

        self.assertEqual(outputs[0], {"type": "tool_call_status"})
        self.assertEqual(outputs[1].text, "abcdef。")


if __name__ == "__main__":
    unittest.main()
