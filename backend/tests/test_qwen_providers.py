import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from app.image_backends.qwen_image_backend import QwenImageBackend
from app.providers.qwen_chat_provider import QwenChatProvider
from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


class QwenProviderTests(unittest.TestCase):
    def test_chat_provider_parses_json_and_usage(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertNotIn("secret-key", request.content.decode("utf-8"))
            return httpx.Response(200, json={
                "id": "chat-test", "model": "qwen-plus",
                "choices": [{"message": {"content": '{"route":"generate"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            })

        async def run():
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            provider = QwenChatProvider(api_key="secret-key", workspace_id="workspace", client=client)
            value, result = await provider.complete_json(system_prompt="system", user_prompt="user", fallback={})
            await client.aclose()
            self.assertEqual(value["route"], "generate")
            self.assertEqual(result.input_tokens, 12)
            self.assertEqual(result.output_tokens, 4)

        asyncio.run(run())

    def test_image_provider_archives_remote_result(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "image.example":
                return httpx.Response(200, content=b"png-bytes", headers={"content-type": "image/png"})
            return httpx.Response(200, json={"output": {"choices": [{"message": {"content": [{"image": "https://image.example/out.png"}]}}]}}, headers={"x-request-id": "req-test"})

        async def run():
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                backend = QwenImageBackend(api_key="key", workspace_id="workspace", images_dir=root / "images", storage_dir=root, client=client)
                request = ImageGenerationRequest(
                    project_id="p", run_id="r", backend="qwen_image", base_model="qwen-image-2.0",
                    positive_prompt="game art", parent_image_id="parent", source_turn_id="turn", version_number=2,
                    variants=[CandidateVariant(key="constraint", label="A", title="A", variation="v", prompt_suffix="strict")],
                )
                images = await backend.generate(request)
                await client.aclose()
                self.assertEqual(len(images), 1)
                self.assertEqual(images[0].parent_image_id, "parent")
                self.assertEqual(images[0].source_turn_id, "turn")
                self.assertEqual(Path(images[0].file_path).read_bytes(), b"png-bytes")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
