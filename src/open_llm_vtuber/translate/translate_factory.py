from collections.abc import Callable

from .deeplx import DeepLXTranslate
from .tencent import TencentTranslate
from .translate_interface import TranslateInterface


def _build_deeplx(config: dict) -> TranslateInterface:
    return DeepLXTranslate(
        api_endpoint=config.get("deeplx_api_endpoint"),
        target_lang=config.get("deeplx_target_lang"),
    )


def _build_tencent(config: dict) -> TranslateInterface:
    return TencentTranslate(
        secret_id=config.get("secret_id"),
        secret_key=config.get("secret_key"),
        region=config.get("region"),
        source_lang=config.get("source_lang"),
        target_lang=config.get("target_lang"),
    )


_TRANSLATOR_BUILDERS: dict[str, Callable[[dict], TranslateInterface]] = {
    "deeplx": _build_deeplx,
    "tencent": _build_tencent,
}


class TranslateFactory:
    @staticmethod
    def get_translator(
        translate_provider: str, translate_provider_config: dict
    ) -> TranslateInterface:
        provider = translate_provider.lower()
        try:
            builder = _TRANSLATOR_BUILDERS[provider]
        except KeyError:
            raise ValueError(f"Unsupported translate provider: {provider}") from None
        return builder(translate_provider_config)
