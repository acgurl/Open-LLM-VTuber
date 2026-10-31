import json
import unittest
from types import SimpleNamespace

from open_llm_vtuber.websocket_handler import WebSocketHandler


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


class FakeHistory:
    def __init__(self):
        self.created = []

    async def create_history(self, conf_uid):
        uid = f"new-{len(self.created) + 1}"
        self.created.append((conf_uid, uid))
        return uid


class FakeContext:
    def __init__(self, messages=None, missing=False):
        self.history = FakeHistory()
        self.character_config = SimpleNamespace(conf_uid="conf")
        self.messages = messages or []
        self.missing = missing
        self.loaded = []

    async def load_history(self, history_uid):
        if self.missing and history_uid == "old":
            raise ValueError("missing")
        self.loaded.append(history_uid)
        return self.messages


class HistoryReconnectTests(unittest.IsolatedAsyncioTestCase):
    def make_handler(self, context):
        handler = object.__new__(WebSocketHandler)
        handler.client_contexts = {"client": context}
        return handler

    async def test_missing_history_creates_replacement_after_empty_data(self):
        context = FakeContext(missing=True)
        handler = self.make_handler(context)
        websocket = FakeWebSocket()

        await handler._handle_fetch_history(websocket, "client", {"history_uid": "old"})

        self.assertEqual(
            [msg["type"] for msg in websocket.sent],
            [
                "history-data",
                "new-history-created",
            ],
        )
        self.assertEqual(websocket.sent[0]["messages"], [])
        self.assertEqual(websocket.sent[1]["history_uid"], "new-1")
        self.assertEqual(context.history.created, [("conf", "new-1")])
        self.assertEqual(context.loaded, ["new-1"])

    async def test_existing_history_loads_without_creating_another(self):
        messages = [
            {"role": "system", "content": "hidden"},
            {"role": "human", "content": "hello"},
        ]
        context = FakeContext(messages=messages)
        handler = self.make_handler(context)
        websocket = FakeWebSocket()

        await handler._handle_fetch_history(websocket, "client", {"history_uid": "old"})

        self.assertEqual([msg["type"] for msg in websocket.sent], ["history-data"])
        self.assertEqual(websocket.sent[0]["messages"], [messages[1]])
        self.assertEqual(context.history.created, [])


if __name__ == "__main__":
    unittest.main()
