import json
import time
import unittest
from datetime import datetime
from types import SimpleNamespace

from open_llm_vtuber.utils.timestamps import to_wire_timestamp, with_wire_timestamp
from open_llm_vtuber.websocket_handler import WebSocketHandler


class ToWireTimestampTests(unittest.TestCase):
    def test_naive_value_gets_server_local_offset(self):
        result = datetime.fromisoformat(to_wire_timestamp("2026-10-23 10:15:00"))
        self.assertIsNotNone(result.tzinfo)
        expected = datetime(2026, 10, 23, 10, 15).astimezone()
        self.assertEqual(result, expected)
        self.assertEqual(
            result.timestamp(), time.mktime((2026, 10, 23, 10, 15, 0, 0, 0, -1))
        )

    def test_iso_t_separator_and_fraction(self):
        result = to_wire_timestamp("2026-10-23T10:15:00.123456")
        self.assertTrue(result.startswith("2026-10-23T10:15:00"))
        self.assertIsNotNone(datetime.fromisoformat(result).tzinfo)

    def test_aware_values_keep_their_offset(self):
        self.assertEqual(
            to_wire_timestamp("2026-10-23T10:15:00+08:00"), "2026-10-23T10:15:00+08:00"
        )
        self.assertEqual(
            to_wire_timestamp("2026-10-23T10:15:00.5Z"), "2026-10-23T10:15:00+00:00"
        )

    def test_unparseable_values_pass_through(self):
        self.assertEqual(to_wire_timestamp("yesterday"), "yesterday")
        self.assertEqual(to_wire_timestamp(""), "")
        self.assertIsNone(to_wire_timestamp(None))

    def test_with_wire_timestamp_leaves_dicts_without_timestamp(self):
        message = {"role": "human", "content": "hi"}
        self.assertIs(with_wire_timestamp(message), message)


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


class FakeHistory:
    async def list_histories(self, conf_uid):
        return [
            {
                "uid": "h1",
                "timestamp": "2026-10-23 10:15:00",
                "latest_message": {"role": "ai", "timestamp": "2026-10-23 10:15:00"},
            },
            {"uid": "h2", "timestamp": "2026-10-23 09:00:00"},
        ]


class FakeContext:
    def __init__(self):
        self.history = FakeHistory()
        self.character_config = SimpleNamespace(conf_uid="conf")

    async def load_history(self, history_uid):
        return [{"role": "human", "content": "hi", "timestamp": "2026-10-23 10:15:00"}]

    async def get_history_tool_calls(self, history_uid):
        return [{"tool_id": "t1", "turn_index": 0, "timestamp": "2026-10-23 10:15:01"}]


class WireTimestampHandlerTests(unittest.IsolatedAsyncioTestCase):
    def make_handler(self):
        handler = object.__new__(WebSocketHandler)
        handler.client_contexts = {"client": FakeContext()}
        return handler

    async def test_history_list_timestamps_carry_offsets(self):
        websocket = FakeWebSocket()
        await self.make_handler()._handle_history_list_request(websocket, "client", {})
        first, second = websocket.sent[0]["histories"]
        for value in (
            first["timestamp"],
            first["latest_message"]["timestamp"],
            second["timestamp"],
        ):
            self.assertIsNotNone(datetime.fromisoformat(value).tzinfo)
        self.assertNotIn("latest_message", second)

    async def test_history_data_timestamps_carry_offsets(self):
        websocket = FakeWebSocket()
        await self.make_handler()._handle_fetch_history(
            websocket, "client", {"history_uid": "h1"}
        )
        data = websocket.sent[0]
        self.assertIsNotNone(
            datetime.fromisoformat(data["messages"][0]["timestamp"]).tzinfo
        )
        self.assertIsNotNone(
            datetime.fromisoformat(data["tool_calls"][0]["timestamp"]).tzinfo
        )


if __name__ == "__main__":
    unittest.main()
