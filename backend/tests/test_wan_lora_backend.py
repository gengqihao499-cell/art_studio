"""万相 2.7 LoRA 异步图像后端测试。

所有 HTTP 请求都使用 MockTransport，不会访问阿里云，也不会产生费用。
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.image_backends.wan_lora_backend import WanLoraImageBackend
from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


class WanLoraBackendTests(unittest.TestCase):
    def test_async_task_is_polled_and_result_is_archived(self):
        """验证触发词、参考图、异步轮询和本地归档组成完整调用链。"""

        captured_payloads: list[dict] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "image.example":
                return httpx.Response(200, content=b"wan-png-bytes", headers={"content-type": "image/png"})
            if request.method == "POST":
                self.assertEqual(request.headers["x-dashscope-async"], "enable")
                captured_payloads.append(json.loads(request.content.decode("utf-8")))
                return httpx.Response(
                    200,
                    json={"request_id": "submit-request", "output": {"task_id": "task-1", "task_status": "PENDING"}},
                )
            if request.url.path == "/api/v1/tasks/task-1":
                return httpx.Response(
                    200,
                    json={
                        "request_id": "result-request",
                        "output": {
                            "task_id": "task-1",
                            "task_status": "SUCCEEDED",
                            "choices": [{"message": {"content": [{"image": "https://image.example/result.png"}]}}],
                        },
                    },
                )
            return httpx.Response(404)

        async def run():
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                reference = root / "parent.png"
                reference.write_bytes(b"reference-bytes")
                client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                backend = WanLoraImageBackend(
                    api_key="secret-key",
                    model="wan2.7-image-artflow-test",
                    trigger_word="t64px9",
                    images_dir=root / "images",
                    storage_dir=root,
                    poll_interval_seconds=0.05,
                    client=client,
                )
                request = ImageGenerationRequest(
                    project_id="project",
                    run_id="run",
                    backend="wan_lora",
                    base_model="wan2.7-image-artflow-test",
                    positive_prompt="原创横版像素森林场景",
                    negative_prompt="人物，文字，水印",
                    width=1280,
                    height=720,
                    seed=123,
                    reference_images=[str(reference)],
                    generation_mode="edit",
                    parent_image_id="parent",
                    source_turn_id="turn",
                    version_number=2,
                    variants=[
                        CandidateVariant(
                            key="constraint",
                            label="A",
                            title="约束核心",
                            variation="约束忠实",
                            prompt_suffix="严格执行当前修改",
                        )
                    ],
                )
                images = await backend.generate(request)
                await client.aclose()

                self.assertEqual(len(images), 1)
                self.assertEqual(Path(images[0].file_path).read_bytes(), b"wan-png-bytes")
                self.assertEqual(images[0].backend, "wan_lora")
                self.assertEqual(images[0].prompt_id, "task-1")
                self.assertEqual(images[0].parent_image_id, "parent")

        asyncio.run(run())

        payload = captured_payloads[0]
        self.assertEqual(payload["model"], "wan2.7-image-artflow-test")
        self.assertEqual(payload["parameters"]["size"], "1280*720")
        self.assertEqual(payload["parameters"]["seed"], 123)
        self.assertNotIn("negative_prompt", payload["parameters"])
        content = payload["input"]["messages"][0]["content"]
        self.assertTrue(content[0]["image"].startswith("data:image/png;base64,"))
        self.assertTrue(content[-1]["text"].startswith("t64px9,"))
        self.assertIn("画面中不得出现：人物，文字，水印", content[-1]["text"])


if __name__ == "__main__":
    unittest.main()
