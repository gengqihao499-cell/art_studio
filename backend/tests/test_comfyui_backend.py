import json
import tempfile
import unittest
from pathlib import Path

import httpx

from app.image_backends.comfyui_backend import ComfyUIImageBackend
from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


BACKEND_DIR = Path(__file__).resolve().parents[1]


class ComfyUIBackendContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_core_api_contract_and_workflow_archive(self) -> None:
        submitted_workflows: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/system_stats":
                return httpx.Response(200, json={"system": {"os": "test"}})
            if request.url.path == "/prompt":
                payload = json.loads(request.content)
                submitted_workflows.append(payload["prompt"])
                return httpx.Response(200, json={"prompt_id": payload["prompt_id"]})
            if request.url.path.startswith("/history/"):
                prompt_id = request.url.path.rsplit("/", 1)[-1]
                return httpx.Response(
                    200,
                    json={
                        prompt_id: {
                            "outputs": {
                                "9": {
                                    "images": [
                                        {
                                            "filename": "result.png",
                                            "subfolder": "",
                                            "type": "output",
                                        }
                                    ]
                                }
                            }
                        }
                    },
                )
            if request.url.path == "/view":
                return httpx.Response(200, content=b"\x89PNG\r\n\x1a\ncontract-test")
            return httpx.Response(404)

        variants = [
            CandidateVariant(
                key=key,
                label=label,
                title=f"Candidate {label}",
                variation=key,
                prompt_suffix=f"{key} emphasis",
                seed_offset=index,
            )
            for index, (key, label) in enumerate(
                (("constraint", "A"), ("composition", "B"), ("silhouette", "C"))
            )
        ]
        request = ImageGenerationRequest(
            project_id="project_test",
            run_id="run_test",
            backend="comfyui",
            base_model="test-model.safetensors",
            positive_prompt="game character concept",
            width=512,
            height=512,
            steps=12,
            cfg=4,
            seed=42,
            variants=variants,
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            backend = ComfyUIImageBackend(
                base_url="http://comfy.test",
                images_dir=root / "images",
                workflows_dir=root / "workflows",
                storage_dir=root,
                template_path=BACKEND_DIR / "workflows" / "templates" / "txt2img_core_v1.json",
                transport=httpx.MockTransport(handler),
            )

            self.assertTrue((await backend.health())["available"])
            results = await backend.generate(request)

            self.assertEqual(len(results), 3)
            self.assertEqual(len(submitted_workflows), 3)
            self.assertTrue(all(result.backend == "comfyui" for result in results))
            self.assertTrue(all(Path(result.file_path).is_file() for result in results))
            self.assertEqual(len(list((root / "workflows").glob("*.json"))), 3)
            self.assertEqual(
                {workflow["4"]["inputs"]["ckpt_name"] for workflow in submitted_workflows},
                {"test-model.safetensors"},
            )


if __name__ == "__main__":
    unittest.main()
