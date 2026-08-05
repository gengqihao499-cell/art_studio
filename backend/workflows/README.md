# ComfyUI workflow templates

ArtFlow does not let an LLM generate arbitrary ComfyUI graphs. It loads a reviewed API-format template, modifies whitelisted inputs, validates every node, and archives the exact submitted JSON.

The bundled `templates/txt2img_core_v1.json` uses only core text-to-image nodes plus `LoraLoader`. Its `_artflow.bindings` block maps semantic inputs to stable node IDs and is removed before submission.

To use another workflow:

1. Export a working graph from ComfyUI with **Save (API Format)**.
2. Add an `_artflow` block matching the bundled template's bindings.
3. Keep the required node classes: checkpoint, sampler, latent, positive/negative text, LoRA anchor and save image.
4. Optionally set `reference_image_node` to a `LoadImage`-compatible node. Uploaded references will then be injected into that node; downstream IPAdapter/ControlNet wiring remains part of the reviewed template.
5. Set `COMFYUI_TEMPLATE_PATH` in `backend/.env`.

At runtime, submitted workflows are written to `backend/storage/workflows/{run_id}-{variant}.json`.
