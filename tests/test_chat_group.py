import json
import unittest

from open_llm_vtuber.chat_group import ChatGroupManager, handle_group_operation


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))


class GroupOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = ChatGroupManager()
        self.manager.client_group_map = {"owner": "", "guest": ""}
        self.owner_ws = FakeWebSocket()
        self.guest_ws = FakeWebSocket()
        self.connections = {"owner": self.owner_ws, "guest": self.guest_ws}
        self.updates = []

        async def send_group_update(websocket, client_uid):
            self.updates.append(client_uid)

        self.send_group_update = send_group_update

    async def run_operation(self, operation: str, target_uid: str = "guest"):
        await handle_group_operation(
            operation=operation,
            client_uid="owner",
            target_uid=target_uid,
            chat_group_manager=self.manager,
            client_connections=self.connections,
            send_group_update=self.send_group_update,
        )

    async def test_add_client_notifies_both_sides(self):
        await self.run_operation("add-client-to-group")

        self.assertEqual(
            sorted(self.manager.get_group_members("owner")), ["guest", "owner"]
        )
        self.assertEqual(self.owner_ws.sent[-1]["success"], True)
        self.assertIn("Successfully added guest", self.owner_ws.sent[-1]["message"])
        self.assertIn("invited", self.guest_ws.sent[-1]["message"])
        self.assertIn("guest", self.updates)

    async def test_remove_client_notifies_removed_member(self):
        await self.run_operation("add-client-to-group")
        await self.run_operation("remove-client-from-group")

        self.assertEqual(self.manager.get_group_members("owner"), [])
        self.assertIn("removed from the group", self.guest_ws.sent[-1]["message"])
        self.assertTrue(
            any(
                "Successfully removed guest" in message["message"]
                for message in self.owner_ws.sent
            )
        )

    async def test_unknown_target_reports_failure_to_initiator(self):
        await self.run_operation("add-client-to-group", target_uid="missing")

        self.assertEqual(self.owner_ws.sent[-1]["success"], False)


if __name__ == "__main__":
    unittest.main()
