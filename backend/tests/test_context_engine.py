import tempfile
import unittest
from pathlib import Path

from app.context import ContextEngine, LoopCircuitOpen, LoopGuard
from app.context.claude_memory import ClaudeMemoryStore
from app.database import Database
from app.storage import HashEmbeddingProvider, LocalBlobStore, LocalVectorStore


MEMORY = {
    "project_goal": "设计月下河谷",
    "locked_constraints": ["保持青色月光"],
    "style_decisions": ["写实游戏概念图"],
    "character_facts": [],
    "composition_facts": ["河流形成引导线"],
    "rejected_directions": ["拒绝暖色天空"],
    "active_image": {"id": "img_a"},
    "open_questions": [],
}


class ContextEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "artflow.db")
        self.database.initialize()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO projects
                (id, name, status, created_at, updated_at)
                VALUES ('project_test', '测试项目', 'ready', 'now', 'now')"""
            )
            connection.execute(
                """INSERT INTO sessions (id, project_id, title, created_at, updated_at)
                VALUES ('session_test', 'project_test', '测试', 'now', 'now')"""
            )
        self.claude = ClaudeMemoryStore(
            self.database,
            root / "memory",
            root / "GLOBAL_CLAUDE.md",
        )
        embedding = HashEmbeddingProvider(64)
        self.engine = ContextEngine(
            database=self.database,
            claude_store=self.claude,
            blob_store=LocalBlobStore(root / "artifacts"),
            vector_store=LocalVectorStore(self.database),
            embedding_provider=embedding,
            max_tokens=1000,
            artifact_inline_chars=500,
            semantic_top_k=3,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _packet(self, raw_tokens=800):
        return self.engine.prepare_packet(
            project_id="project_test",
            project_name="测试项目",
            session_id="session_test",
            run_id="run_test",
            turn_sequence=12,
            current_request="保持青色月光，调整河流构图",
            raw_messages=[
                {
                    "id": "old",
                    "role": "assistant",
                    "content": "远古工具输出" * 160,
                    "turn_id": "turn_old",
                    "turn_sequence": 1,
                },
                {
                    "id": "new",
                    "role": "user",
                    "content": "保持青色月光",
                    "turn_id": "turn_new",
                    "turn_sequence": 12,
                },
            ],
            raw_token_total=raw_tokens,
            memory=MEMORY,
            locked_constraints=MEMORY["locked_constraints"],
        )

    def test_five_layers_offload_and_role_projection(self):
        packet = self._packet()
        self.assertEqual(packet["messages"][0]["mode"], "snip")
        self.assertIsNotNone(packet["messages"][0]["artifact"])
        self.assertEqual(set(packet["layers"]), {
            "artifact_offload", "snip", "micro_compact", "context_collapse", "auto_compact"
        })
        projected = self.engine.project_for_agent(
            {"context_packet": packet, "memory": MEMORY, "user_request": "x"},
            "composition_agent",
        )
        self.assertIn("composition_facts", projected["memory"])
        self.assertNotIn("character_facts", projected["memory"])

    def test_agent_updates_only_managed_claude_block_and_indexes_memory(self):
        initial = self.claude.load("project_test", "测试项目")
        self.claude.replace(
            "project_test",
            "测试项目",
            initial["project_content"] + "\n用户手写：永远保留这一行。\n",
        )
        packet = self._packet(raw_tokens=900)
        state = {
            "project_id": "project_test",
            "project_name": "测试项目",
            "session_id": "session_test",
            "turn_id": "turn_test",
            "context_packet": packet,
        }
        updated = self.engine.memory_succeeded(state, MEMORY)
        self.assertIn("用户手写：永远保留这一行", updated["claude_md"])
        self.assertIn("保持青色月光", updated["claude_md"])
        status = self.engine.get_status("project_test", "session_test", "测试项目")
        self.assertEqual(status["compaction"]["snapshot_version"], 1)
        self.assertGreater(status["memory_item_count"], 0)

    def test_auto_compact_opens_after_three_failures_and_can_reset(self):
        state = {"project_id": "project_test", "session_id": "session_test"}
        for expected in (1, 2, 3):
            result = self.engine.memory_failed(state, RuntimeError("compact failed"))
            self.assertEqual(result["consecutive_failures"], expected)
        self.assertEqual(result["circuit_state"], "open")
        reset = self.engine.reset_compaction_breaker("session_test")
        self.assertEqual(reset["consecutive_failures"], 0)
        self.assertEqual(reset["circuit_state"], "closed")

    def test_loop_guard_opens_on_identical_progress(self):
        guard = LoopGuard(max_same_signature=3)
        guard.observe("agent", {"result": "same"})
        guard.observe("agent", {"result": "same"})
        with self.assertRaises(LoopCircuitOpen):
            guard.observe("agent", {"result": "same"})


if __name__ == "__main__":
    unittest.main()
