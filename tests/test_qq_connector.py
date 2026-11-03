import asyncio
import json
import unittest

import httpx

from open_llm_vtuber.config_manager.connectors import QQConnectorConfig
from open_llm_vtuber.connectors.qq import (
    API_BASE,
    INTENT_BITS,
    OP_DISPATCH,
    OP_HELLO,
    OP_IDENTIFY,
    OP_RECONNECT,
    OP_RESUME,
    QQConnector,
    QQGatewayError,
    parse_event,
)


def _config(**overrides):
    values = {
        "id": "qq",
        "enabled": True,
        "app_id": "1024",
        "app_secret": "secret",
        "intents": ["public_guild_messages", "direct_message", "group_and_c2c"],
    }
    values.update(overrides)
    return QQConnectorConfig(**values)


class _Api:
    """httpx mock of the token endpoint and the bot REST API."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.token_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "bots.qq.com":
            self.token_calls += 1
            body = json.loads(request.content)
            assert body == {"appId": "1024", "clientSecret": "secret"}
            return httpx.Response(
                200, json={"access_token": "tok", "expires_in": "7200"}
            )
        if request.url.path == "/gateway":
            return httpx.Response(200, json={"url": "wss://gateway.example/websocket"})
        return httpx.Response(200, json={"id": "sent"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class _FakeSocket:
    def __init__(self, frames):
        self._frames = asyncio.Queue()
        for frame in frames:
            self._frames.put_nowait(frame)
        self.sent: list[dict] = []

    async def recv(self):
        frame = await self._frames.get()
        if isinstance(frame, Exception):
            raise frame
        return json.dumps(frame)

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class ParseEventTests(unittest.TestCase):
    def test_guild_at_message_strips_the_mention(self):
        message = parse_event(
            "qq",
            "AT_MESSAGE_CREATE",
            {
                "id": "m1",
                "channel_id": "c1",
                "guild_id": "g1",
                "content": "<@!123> 你好 ",
                "author": {"id": "u42", "username": "alice"},
                "member": {"nick": "小A"},
            },
        )
        self.assertEqual(message.chat_type, "guild")
        self.assertEqual(message.chat_id, "c1")
        self.assertEqual(message.sender_id, "u:u42")
        self.assertEqual(message.sender_name, "小A")
        self.assertEqual(message.text, "你好")
        self.assertEqual(message.reply_context, {"msg_id": "m1"})

    def test_direct_group_and_c2c_messages(self):
        direct = parse_event(
            "qq",
            "DIRECT_MESSAGE_CREATE",
            {"id": "m2", "guild_id": "dm-g", "content": "hi", "author": {"id": "u42"}},
        )
        self.assertEqual(
            (direct.chat_type, direct.chat_id, direct.sender_id),
            ("direct", "dm-g", "u:u42"),
        )

        group = parse_event(
            "qq",
            "GROUP_AT_MESSAGE_CREATE",
            {
                "id": "m3",
                "group_openid": "G",
                "content": " hi",
                "author": {"member_openid": "O"},
            },
        )
        self.assertEqual(
            (group.chat_type, group.chat_id, group.sender_id), ("group", "G", "o:O")
        )

        c2c = parse_event(
            "qq",
            "C2C_MESSAGE_CREATE",
            {"id": "m4", "content": "hi", "author": {"user_openid": "O"}},
        )
        self.assertEqual(
            (c2c.chat_type, c2c.chat_id, c2c.sender_id), ("c2c", "O", "o:O")
        )

    def test_bot_messages_and_unknown_events_are_ignored(self):
        self.assertIsNone(
            parse_event(
                "qq",
                "MESSAGE_CREATE",
                {"id": "m", "channel_id": "c", "author": {"id": "b", "bot": True}},
            )
        )
        self.assertIsNone(parse_event("qq", "GUILD_CREATE", {"id": "g"}))
        self.assertIsNone(
            parse_event("qq", "AT_MESSAGE_CREATE", {"id": "m", "author": {}})
        )


class QQRestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = _Api()
        self.connector = QQConnector(_config(), http_client=self.api.client())

    async def asyncTearDown(self):
        await self.connector.close()

    async def test_replies_use_the_right_endpoint_and_sequence(self):
        guild = parse_event(
            "qq",
            "AT_MESSAGE_CREATE",
            {"id": "m1", "channel_id": "c1", "content": "x", "author": {"id": "u"}},
        )
        group = parse_event(
            "qq",
            "GROUP_AT_MESSAGE_CREATE",
            {
                "id": "m2",
                "group_openid": "G",
                "content": "x",
                "author": {"member_openid": "O"},
            },
        )
        await self.connector.send_text(guild, "一", 0)
        await self.connector.send_text(group, "一", 0)
        await self.connector.send_text(group, "二", 1)

        posts = [
            request
            for request in self.api.requests
            if request.url.host != "bots.qq.com"
        ]
        self.assertEqual(
            [str(request.url) for request in posts],
            [
                f"{API_BASE}/channels/c1/messages",
                f"{API_BASE}/v2/groups/G/messages",
                f"{API_BASE}/v2/groups/G/messages",
            ],
        )
        self.assertEqual(posts[0].headers["Authorization"], "QQBot tok")
        self.assertEqual(
            json.loads(posts[0].content), {"content": "一", "msg_id": "m1"}
        )
        self.assertEqual([json.loads(p.content)["msg_seq"] for p in posts[1:]], [1, 2])
        # The access token is cached between calls.
        self.assertEqual(self.api.token_calls, 1)


class QQGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_identify_dispatch_then_resume_after_reconnect(self):
        api = _Api()
        sockets = [
            _FakeSocket(
                [
                    {"op": OP_HELLO, "d": {"heartbeat_interval": 60000}},
                    {"op": OP_DISPATCH, "t": "READY", "s": 1, "d": {"session_id": "S"}},
                    {
                        "op": OP_DISPATCH,
                        "t": "AT_MESSAGE_CREATE",
                        "s": 2,
                        "d": {
                            "id": "m1",
                            "channel_id": "c1",
                            "content": "<@!1> 你好",
                            "author": {"id": "u42"},
                        },
                    },
                    {"op": OP_RECONNECT},
                ]
            ),
            _FakeSocket(
                [
                    {"op": OP_HELLO, "d": {"heartbeat_interval": 60000}},
                    {"op": OP_DISPATCH, "t": "RESUMED", "s": 3, "d": {}},
                    QQGatewayError("closed"),
                ]
            ),
        ]
        urls = []

        def connect(url, **_kwargs):
            urls.append(url)
            return sockets[len(urls) - 1]

        connector = QQConnector(_config(), http_client=api.client(), connect=connect)
        received = []

        async def on_message(_connector, message):
            received.append(message)

        with self.assertRaises(QQGatewayError):
            await connector.run(on_message)
        identify = sockets[0].sent[0]
        self.assertEqual(identify["op"], OP_IDENTIFY)
        self.assertEqual(identify["d"]["token"], "QQBot tok")
        self.assertEqual(
            identify["d"]["intents"],
            INTENT_BITS["public_guild_messages"]
            | INTENT_BITS["direct_message"]
            | INTENT_BITS["group_and_c2c"],
        )
        self.assertEqual([m.text for m in received], ["你好"])

        with self.assertRaises(QQGatewayError):
            await connector.run(on_message)
        resume = sockets[1].sent[0]
        self.assertEqual(resume["op"], OP_RESUME)
        self.assertEqual(resume["d"]["session_id"], "S")
        self.assertEqual(resume["d"]["seq"], 2)
        self.assertEqual(urls, ["wss://gateway.example/websocket"] * 2)
        await connector.close()


if __name__ == "__main__":
    unittest.main()
