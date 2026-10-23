import json
import httpx
from loguru import logger
from .translate_interface import TranslateInterface


class DeepLXTranslate(TranslateInterface):
    api_endpoint: str = "http://127.0.0.1:1188/v2/translate"
    target_lang: str = "JP"

    def __init__(self, api_endpoint: str, target_lang: str):
        self.api_endpoint = api_endpoint
        self.target_lang = target_lang

    # translate v2 endpoint from DeepLX
    def translate(self, text: str) -> str:
        response_text = None
        try:
            data = {"text": [text], "target_lang": self.target_lang}
            post_data = json.dumps(data)
            response_text = httpx.post(
                url=self.api_endpoint, data=post_data, timeout=10.0
            ).text
            res = json.loads(response_text)["translations"]
            res = " ".join([d["text"] for d in res])
        except Exception as e:
            logger.critical(f"Error translating text '{text}'. Error message: {e}")
            if response_text is not None:
                logger.critical(f"Response: {response_text}")
            raise e

        return res
