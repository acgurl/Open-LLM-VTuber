import threading
import unittest
from unittest.mock import Mock, patch

from open_llm_vtuber.agent.stateless_llm import ollama_llm
from open_llm_vtuber.agent.stateless_llm.ollama_llm import OllamaLLM

BASE_URL = "http://localhost:11434/v1"


class OllamaLifecycleTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.multiple(
            ollama_llm,
            _models_to_unload=set(),
            _unload_hook_registered=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_constructor_does_not_wait_for_preload(self):
        release = threading.Event()
        preloading = threading.Event()

        def slow_post(*_args, **_kwargs):
            preloading.set()
            release.wait(5)
            return Mock()

        with (
            patch.object(ollama_llm.requests, "post", side_effect=slow_post) as post,
            patch.object(ollama_llm.atexit, "register"),
        ):
            OllamaLLM(model="m", base_url=BASE_URL)
            constructed_while_preloading = not release.is_set()
            self.assertTrue(preloading.wait(5))
            release.set()

        self.assertTrue(constructed_while_preloading)
        self.assertEqual(
            post.call_args.kwargs["json"], {"model": "m", "keep_alive": -1}
        )

    def test_exit_hook_is_registered_once_and_unloads_each_model(self):
        with (
            patch.object(OllamaLLM, "_preload"),
            patch.object(ollama_llm.requests, "post") as post,
            patch.object(ollama_llm.atexit, "register") as register,
        ):
            OllamaLLM(model="a", base_url=BASE_URL)
            OllamaLLM(model="a", base_url=BASE_URL)
            OllamaLLM(model="b", base_url=BASE_URL)

            register.assert_called_once_with(ollama_llm._unload_models_at_exit)
            ollama_llm._unload_models_at_exit()

        unloaded = sorted(call.kwargs["json"]["model"] for call in post.call_args_list)
        self.assertEqual(unloaded, ["a", "b"])
        for call in post.call_args_list:
            self.assertEqual(call.kwargs["json"]["keep_alive"], 0)

    def test_unload_at_exit_disabled_registers_nothing(self):
        with (
            patch.object(OllamaLLM, "_preload"),
            patch.object(ollama_llm.atexit, "register") as register,
        ):
            OllamaLLM(model="m", base_url=BASE_URL, unload_at_exit=False)

        register.assert_not_called()
        self.assertEqual(ollama_llm._models_to_unload, set())


if __name__ == "__main__":
    unittest.main()
