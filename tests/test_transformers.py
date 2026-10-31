import unittest

from open_llm_vtuber.agent.output_types import Actions, DisplayText
from open_llm_vtuber.agent.transformers import sentence_divider, tts_filter
from open_llm_vtuber.utils.sentence_divider import (
    SentenceWithTags,
    TagInfo,
    TagState,
)


async def _stream(items):
    for item in items:
        yield item


class SentenceDividerDecoratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_valid_tags_keep_think_markers(self):
        async def source():
            yield "<think>a</think>b。"

        outputs = [
            item async for item in sentence_divider(segment_method="regex")(source)()
        ]

        self.assertEqual(
            [(item.text, item.tags[0].name) for item in outputs],
            [
                ("<think>", "think"),
                ("a", "think"),
                ("</think>", "think"),
                ("b。", ""),
            ],
        )


class TTSFilterDecoratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_config_uses_defaults(self):
        async def source():
            yield (
                SentenceWithTags(text="**hello**", tags=[TagInfo("", TagState.NONE)]),
                DisplayText(text="**hello**"),
                Actions(),
            )

        outputs = [item async for item in tts_filter(None)(source)()]

        self.assertEqual(outputs[0].tts_text, "hello")

    async def test_think_content_skips_tts(self):
        async def source():
            yield (
                SentenceWithTags(
                    text="secret", tags=[TagInfo("think", TagState.INSIDE)]
                ),
                DisplayText(text="secret"),
                Actions(),
            )

        outputs = [item async for item in tts_filter(None)(source)()]

        self.assertEqual(outputs[0].tts_text, "")


if __name__ == "__main__":
    unittest.main()
