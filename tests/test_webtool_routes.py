import asyncio
import io
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from open_llm_vtuber.auth import AuthRedirectMiddleware, Identity
from open_llm_vtuber.routes import init_session_routes, init_webtool_routes
from open_llm_vtuber.service_context import ServiceContext
from open_llm_vtuber.websocket_handler import WebSocketHandler

from test_character_assets import make_auth


class FakeTTSEngine:
    def __init__(self) -> None:
        self.calls = []
        self.fail = False
        self.return_none = False

    async def async_generate_audio(self, text: str, file_name_no_ext: str):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("synthesis failed")
        if self.return_none:
            return None
        return f"audio/{file_name_no_ext}.wav"


class FakeContext:
    def __init__(self) -> None:
        self.tts_engine = FakeTTSEngine()
        self.asr_engine = None


class TTSWebSocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = FakeContext()
        app = FastAPI()
        app.include_router(init_webtool_routes(self.context))
        self.client = TestClient(app)

    def test_splits_sentences_and_streams_audio(self) -> None:
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "你好. Hello! 世界"})
            messages = [websocket.receive_json() for _ in range(4)]

        self.assertEqual(
            [message["status"] for message in messages],
            ["partial", "partial", "partial", "complete"],
        )
        self.assertEqual(
            [message["text"] for message in messages[:3]],
            ["你好.", "Hello!", "世界."],
        )
        self.assertTrue(
            all(message["audioPath"].startswith("audio/") for message in messages[:3])
        )
        self.assertEqual(
            self.context.tts_engine.calls,
            ["你好.", "Hello!", "世界."],
        )

    def test_rejects_text_over_character_limit(self) -> None:
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "a" * 2001})
            message = websocket.receive_json()

        self.assertEqual(
            message,
            {"status": "error", "message": "Text exceeds the 2000-character limit"},
        )
        self.assertEqual(self.context.tts_engine.calls, [])

    def test_rejects_text_over_sentence_limit(self) -> None:
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "Hello. " * 31})
            message = websocket.receive_json()

        self.assertEqual(message["status"], "error")
        self.assertIn("30-sentence limit", message["message"])
        self.assertEqual(self.context.tts_engine.calls, [])

    def test_reports_generation_failure_and_keeps_connection_open(self) -> None:
        self.context.tts_engine.fail = True
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "Hello."})
            error = websocket.receive_json()

            self.context.tts_engine.fail = False
            websocket.send_json({"text": "Hello."})
            partial = websocket.receive_json()
            complete = websocket.receive_json()

        self.assertEqual(
            error, {"status": "error", "message": "Failed to generate audio"}
        )
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(complete, {"status": "complete"})

    def test_reports_none_audio_as_generation_failure(self) -> None:
        self.context.tts_engine.return_none = True
        with self.client.websocket_connect("/tts-ws") as websocket:
            websocket.send_json({"text": "Hello."})
            error = websocket.receive_json()

            self.context.tts_engine.return_none = False
            websocket.send_json({"text": "Hello."})
            partial = websocket.receive_json()
            complete = websocket.receive_json()

        self.assertEqual(
            error, {"status": "error", "message": "Failed to generate audio"}
        )
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(complete, {"status": "complete"})


def _wav_files():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x40")
    return [("file", ("recording.wav", buffer.getvalue(), "audio/wav"))]


def _asr_engine(text):
    return SimpleNamespace(async_transcribe_np=AsyncMock(return_value=text))


class ASRWebToolTests(unittest.TestCase):
    def test_standalone_default_and_invalid_id(self):
        engine = _asr_engine("standalone")
        app = FastAPI()
        app.include_router(init_webtool_routes(SimpleNamespace(asr_engine=engine)))
        with TestClient(app) as client:
            response = client.post("/asr", files=_wav_files())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"text": "standalone"})
            response = client.post(
                "/asr", data={"client_uid": "unknown"}, files=_wav_files()
            )
            self.assertEqual(response.status_code, 404)
        engine.async_transcribe_np.assert_awaited_once()
        audio = engine.async_transcribe_np.await_args.args[0]
        self.assertEqual(audio.tolist(), [0.5])

    def test_session_engines_are_isolated_between_two_verified_owners(self):
        auth = make_auth()
        self.addCleanup(lambda: asyncio.run(auth.close()))
        app = FastAPI()
        app.add_middleware(AuthRedirectMiddleware, auth=auth)
        startup_default = _asr_engine("startup default")
        alice_character = _asr_engine("Alice's character")
        alice_selected = _asr_engine("Alice's selected ASR")
        bob_character = _asr_engine("Bob's character")
        app.include_router(
            init_session_routes(SimpleNamespace(asr_engine=startup_default), auth)
        )

        async def build_context(*args, identity, **kwargs):
            context = ServiceContext()
            context.user_id = identity.user_id
            context.character_config = SimpleNamespace(
                conf_name="Test",
                conf_uid="test",
                welcome_message="",
                starter_prompts=[],
            )
            if identity.user_id == "alice":
                context.asr_engine = alice_character
                context._selected_asr_engine = alice_selected
            else:
                context.asr_engine = bob_character
            return context

        def headers(owner):
            return {
                "cookie": f"{auth.config.session_cookie_name}="
                f"{auth.issue_session(Identity(owner))}"
            }

        def get_uid(websocket):
            for _ in range(3):
                msg = websocket.receive_json()
                if msg["type"] == "set-model-and-conf":
                    return msg["client_uid"]
            self.fail("No client_uid received from /client-ws")

        with (
            patch(
                "open_llm_vtuber.websocket_handler.build_session_context", build_context
            ),
            TestClient(app) as client,
        ):
            alice, bob = headers("alice"), headers("bob")
            with client.websocket_connect("/client-ws", headers=alice) as alice_ws:
                alice_uid = get_uid(alice_ws)
                with client.websocket_connect("/client-ws", headers=bob) as bob_ws:
                    bob_uid = get_uid(bob_ws)
                    for owner, uid, text in (
                        (alice, alice_uid, "Alice's selected ASR"),
                        (bob, bob_uid, "Bob's character"),
                    ):
                        response = client.post(
                            "/asr",
                            headers=owner,
                            data={"client_uid": uid},
                            files=_wav_files(),
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json(), {"text": text})

                    denied = {"error": "Unknown client"}
                    for owner, uid in (
                        (alice, bob_uid),
                        (bob, alice_uid),
                        (alice, "missing"),
                    ):
                        with self.subTest(uid=uid):
                            response = client.post(
                                "/asr",
                                headers=owner,
                                data={"client_uid": uid},
                                files=_wav_files(),
                            )
                            self.assertEqual(response.status_code, 404)
                            self.assertEqual(response.json(), denied)
                    for invalid in (
                        [("client_uid", (None, ""))],
                        [("client_uid", (None, alice_uid))] * 2,
                        [("client_uid", ("uid.txt", alice_uid))],
                    ):
                        response = client.post(
                            "/asr", headers=alice, files=_wav_files() + invalid
                        )
                        self.assertEqual(response.status_code, 404)
                        self.assertEqual(response.json(), denied)
                    response = client.post(
                        "/asr", data={"client_uid": alice_uid}, files=_wav_files()
                    )
                    self.assertEqual(response.status_code, 401)

                response = client.post(
                    "/asr",
                    headers=bob,
                    data={"client_uid": bob_uid},
                    files=_wav_files(),
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), denied)
            response = client.post("/asr", headers=alice, files=_wav_files())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"text": "startup default"})

        alice_selected.async_transcribe_np.assert_awaited_once()
        bob_character.async_transcribe_np.assert_awaited_once()
        alice_character.async_transcribe_np.assert_not_awaited()
        startup_default.async_transcribe_np.assert_awaited_once()


class ASRSessionSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_refreshes_only_while_idle_and_rechecks_after_await(self):
        handler = WebSocketHandler(ServiceContext())
        old_asr, new_asr = _asr_engine("old"), _asr_engine("new")
        turn = asyncio.get_running_loop().create_future()
        start_turn_during_sync = True
        context = SimpleNamespace(asr_engine=old_asr)

        async def refresh(*, can_apply):
            await asyncio.sleep(0)
            if start_turn_during_sync:
                handler.current_conversation_tasks["client"] = turn
            if can_apply():
                context.asr_engine = new_asr

        context.sync_asr_choice = AsyncMock(side_effect=refresh)
        handler.client_connections["client"] = object()
        handler.client_users["client"] = "alice"
        handler.client_contexts["client"] = context

        self.assertIsNone(await handler.resolve_asr_context("client", "bob"))
        context.sync_asr_choice.assert_not_awaited()
        self.assertIs(await handler.resolve_asr_context("client", "alice"), context)
        self.assertIs(context.asr_engine, old_asr)
        context.sync_asr_choice.assert_awaited_once()
        self.assertIs(await handler.resolve_asr_context("client", "alice"), context)
        context.sync_asr_choice.assert_awaited_once()

        group = handler.chat_group_manager
        group.client_group_map["peer"] = ""
        self.assertTrue(group.add_client_to_group("client", "peer")[0])
        group_turn = asyncio.get_running_loop().create_future()
        handler.current_conversation_tasks["group_client"] = group_turn
        turn.set_result(None)
        self.assertIs(await handler.resolve_asr_context("client", "alice"), context)
        self.assertIs(context.asr_engine, old_asr)
        context.sync_asr_choice.assert_awaited_once()

        group_turn.set_result(None)
        start_turn_during_sync = False
        self.assertIs(await handler.resolve_asr_context("client", "alice"), context)
        self.assertIs(context.asr_engine, new_asr)


if __name__ == "__main__":
    unittest.main()
