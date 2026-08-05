import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.agents.intent_router import _fallback_route
from app.database import Database
from app.services.project_service import ProjectService


class ConversationFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        assets = Path(__file__).resolve().parents[1] / "assets" / "mock_candidates"
        self.database = Database(root / "artflow.db")
        self.database.initialize()
        self.service = ProjectService(self.database, assets, root / "storage" / "images", context_recent_messages=8, context_max_tokens=1000)
        self.service.ensure_default_project()

    def tearDown(self):
        self.temp.cleanup()

    def test_first_turn_is_four_then_two_and_keeps_parent(self):
        common = dict(
            project_id="project_default", world_context="", aspect_ratio="1:1", reference_images=[],
            style_profile={"style_bible": {}}, image_backend="mock", image_model="mock",
        )
        _, first_turn, first = self.service.create_conversation_turn(prompt="设计一个月下河流场景", **common)
        _, second_turn, second = self.service.create_conversation_turn(prompt="把月亮放大，其他不变", **common)
        self.assertEqual(first["image_count"], 4)
        self.assertEqual(second["image_count"], 2)
        self.assertNotEqual(first_turn, second_turn)
        self.assertEqual(second["parent_image"]["id"], "img_seed_a")

    def test_mock_router_selects_only_relevant_specialist(self):
        route = _fallback_route({"user_request": "把月亮放大，其他不变", "turn_sequence": 2})
        self.assertEqual(route["route"], "generate")
        self.assertEqual(route["specialists"], ["composition"])

    def test_compression_threshold_is_exposed_to_memory_agent(self):
        with self.database.connect() as connection:
            connection.execute("UPDATE messages SET token_estimate = 2000 WHERE session_id = 'session_default'")
        _, _, state = self.service.create_conversation_turn(
            project_id="project_default", prompt="继续保持当前方向并生成", world_context="", aspect_ratio="1:1",
            reference_images=[], style_profile={"style_bible": {}}, image_backend="mock", image_model="mock",
        )
        self.assertTrue(state["compress_context"])

    def test_conversations_are_listed_without_auto_greeting_and_can_be_deleted(self):
        created = self.service.create_project("月下河流场景")
        session_id = created["session"]["id"]
        project_id = created["project"]["id"]
        self.assertEqual(created["messages"], [])

        items = self.service.list_conversations()
        summary = next(item for item in items if item["session_id"] == session_id)
        self.assertEqual(summary["title"], "月下河流场景")
        self.assertEqual(summary["turn_count"], 0)

        deleted = self.service.delete_conversation(session_id)
        self.assertEqual(deleted["project_id"], project_id)
        self.assertFalse(any(item["session_id"] == session_id for item in self.service.list_conversations()))
        with self.assertRaises(KeyError):
            self.service.get_project(project_id)

    def test_static_storage_mount_does_not_require_preexisting_runtime_directory(self):
        """Release archives omit runtime storage; importing the app must still work."""

        from starlette.staticfiles import StaticFiles

        missing = Path(self.temp.name) / "storage-not-created-yet"
        self.assertFalse(missing.exists())
        with patch.object(Path, "is_dir", return_value=False):
            files = StaticFiles(directory=missing, check_dir=False)
        self.assertEqual(Path(files.directory), missing)


if __name__ == "__main__":
    unittest.main()
