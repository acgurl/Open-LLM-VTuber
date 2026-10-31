import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_llm_vtuber import service_context as service_context_module
from open_llm_vtuber.agent.transformers import actions_extractor
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.utils.sentence_divider import (
    SentenceWithTags,
    TagInfo,
    TagState,
)


class Live2DFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_prompt_skips_live2d_prompt_without_model(self):
        context = ServiceContext()
        context.live2d_model = None
        context.system_config = SimpleNamespace(
            tool_prompts={"live2d_expression_prompt": "prompt.txt"}
        )

        with patch.object(
            service_context_module.prompt_loader, "load_util"
        ) as load_prompt:
            prompt = await context.construct_system_prompt("persona")

        self.assertEqual(prompt, "persona")
        load_prompt.assert_not_called()

    async def test_actions_extractor_handles_missing_model(self):
        async def source():
            yield SentenceWithTags(text="hello", tags=[TagInfo("", TagState.NONE)])

        wrapped = actions_extractor(None)(source)
        outputs = [item async for item in wrapped()]

        self.assertEqual(outputs[0][0].text, "hello")
        self.assertIsNone(outputs[0][1].expressions)
        self.assertIsNone(outputs[0][1].motions)

    def test_model_payload_tolerates_missing_model(self):
        context = ServiceContext()
        context.live2d_model = None
        context.character_config = SimpleNamespace(
            conf_name="Conf", conf_uid="uid", welcome_message=""
        )

        self.assertEqual(
            context.model_conf_payload(),
            {
                "type": "set-model-and-conf",
                "model_info": {},
                "conf_name": "Conf",
                "conf_uid": "uid",
                "welcome_message": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
