import unittest
from unittest.mock import AsyncMock, patch

from open_llm_vtuber import service_context as service_context_module, session_factory
from open_llm_vtuber.config_manager.utils import read_yaml, validate_config
from open_llm_vtuber.connectors.formatting import strip_markdown
from open_llm_vtuber.llm_catalog import LLMModelCatalog
from open_llm_vtuber.service_context import ServiceContext


def _default_context():
    config = validate_config(read_yaml("config_templates/conf.ZH.default.yaml"))
    context = ServiceContext()
    context.config = config
    context.system_config = config.system_config
    context.character_config = config.character_config
    context.history_repository = object()
    context.llm_catalog = LLMModelCatalog(
        "config_templates/llm_models.default.yaml",
        tts_path="config_templates/tts_models.default.yaml",
        asr_path="config_templates/asr_models.default.yaml",
    )
    return context


class ConnectorBaseContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_character_override_and_prompt_replacement(self):
        default = _default_context()
        with patch.object(ServiceContext, "load_headless", new=AsyncMock()) as load:
            context = await session_factory.build_connector_base_context(
                default,
                character={
                    "conf_uid": "qq_bot_001",
                    "character_name": "小助手",
                    "persona_prompt": "你是校园助手。",
                },
                tool_prompts={"chat_platform_prompt": "chat_platform_prompt"},
            )

        config = load.await_args.args[0]
        self.assertEqual(config.character_config.conf_uid, "qq_bot_001")
        self.assertEqual(config.character_config.character_name, "小助手")
        self.assertEqual(config.character_config.persona_prompt, "你是校园助手。")
        self.assertEqual(
            config.system_config.tool_prompts,
            {"chat_platform_prompt": "chat_platform_prompt"},
        )
        # Untouched parts are inherited from the base character.
        self.assertEqual(
            config.character_config.agent_config,
            default.character_config.agent_config,
        )
        self.assertEqual(
            config.character_config.model_refs, default.character_config.model_refs
        )
        self.assertIs(context.history_repository, default.history_repository)
        self.assertIs(context.llm_catalog, default.llm_catalog)
        self.assertIsNone(context.user_id)
        # The web character is not modified.
        self.assertNotEqual(default.character_config.conf_uid, "qq_bot_001")

    async def test_default_prompts_drop_only_the_live2d_prompt(self):
        default = _default_context()
        with patch.object(ServiceContext, "load_headless", new=AsyncMock()) as load:
            await session_factory.build_connector_base_context(
                default, character={}, tool_prompts=None
            )
        prompts = load.await_args.args[0].system_config.tool_prompts
        expected = dict(default.system_config.tool_prompts)
        expected.pop("live2d_expression_prompt", None)
        self.assertEqual(prompts, expected)

    async def test_load_headless_creates_no_avatar_or_speech_engines(self):
        default = _default_context()
        with (
            patch.object(default.llm_catalog, "client") as client,
            patch.object(ServiceContext, "_init_mcp_components", new=AsyncMock()),
            patch.object(ServiceContext, "init_agent", new=AsyncMock()) as init_agent,
            patch.object(ServiceContext, "init_live2d") as init_live2d,
            patch.object(ServiceContext, "init_translate") as init_translate,
            patch.object(service_context_module.TTSFactory, "get_tts_engine") as tts,
            patch.object(service_context_module.ASRFactory, "get_asr_system") as asr,
        ):
            context = await session_factory.build_connector_base_context(
                default, character={}, tool_prompts=None
            )

        config = context.config
        init_live2d.assert_not_called()
        init_translate.assert_not_called()
        tts.assert_not_called()
        asr.assert_not_called()
        client.assert_called_once()
        llm_entry = client.call_args.args[0]
        self.assertEqual(llm_entry.id, config.character_config.model_refs.llm)
        init_agent.assert_awaited_once_with(
            config.character_config.agent_config,
            config.character_config.persona_prompt,
            llm_entry=llm_entry,
            bound_llm=(client.return_value, llm_entry.interrupt_method),
        )
        self.assertIsNone(context.live2d_model)
        self.assertIsNone(context.tts_engine)
        self.assertIsNone(context.asr_engine)
        self.assertIsNone(context.translate_engine)


class StripMarkdownTests(unittest.TestCase):
    def test_common_markup_becomes_plain_text(self):
        text = (
            "## 请假流程\n\n"
            "**第一步**：在 `i.cuc` 提交申请。\n"
            "* 辅导员审批\n"
            "> 注意时间\n"
            "---\n"
            "```text\n代码\n```\n"
            "详见 [官网](https://www.cuc.edu.cn)"
        )
        self.assertEqual(
            strip_markdown(text),
            "请假流程\n\n第一步：在 i.cuc 提交申请。\n- 辅导员审批\n注意时间\n代码\n"
            "详见 官网 https://www.cuc.edu.cn",
        )

    def test_single_asterisks_and_underscores_are_kept(self):
        self.assertEqual(
            strip_markdown("2*3*4 = 24，文件 a_b_c.txt"), "2*3*4 = 24，文件 a_b_c.txt"
        )


if __name__ == "__main__":
    unittest.main()
