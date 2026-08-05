import copy
import json
from pathlib import Path

from app.schemas.image_request import CandidateVariant, ImageGenerationRequest


ALLOWED_FIELDS = {
    "positive_prompt",
    "negative_prompt",
    "width",
    "height",
    "steps",
    "cfg",
    "seed",
    "batch_size",
    "base_model",
    "loras",
}

SYSTEM_FIELDS = {
    "project_id",
    "run_id",
    "backend",
    "sampler_name",
    "scheduler",
    "reference_images",
    "variants",
    "workflow_template",
    "parent_image_id",
    "source_turn_id",
    "version_number",
    "generation_mode",
}

REQUIRED_NODE_CLASSES = {
    "sampler_node": "KSampler",
    "checkpoint_node": "CheckpointLoaderSimple",
    "latent_node": "EmptyLatentImage",
    "positive_node": "CLIPTextEncode",
    "negative_node": "CLIPTextEncode",
    "save_node": "SaveImage",
    "lora_anchor_node": "LoraLoader",
}


class WorkflowTemplateError(ValueError):
    pass


class WorkflowTemplateCompiler:
    def __init__(self, template_path: Path) -> None:
        self.template_path = template_path
        raw = json.loads(template_path.read_text(encoding="utf-8"))
        try:
            self.metadata = raw.pop("_artflow")
            self.bindings = self.metadata["bindings"]
        except KeyError as exc:
            raise WorkflowTemplateError("template is missing _artflow bindings") from exc
        self.template = raw
        self._validate_template()

    @property
    def name(self) -> str:
        return str(self.metadata["name"])

    def compile(
        self,
        request: ImageGenerationRequest,
        variant: CandidateVariant,
        output_prefix: str,
        uploaded_references: list[dict] | None = None,
    ) -> dict:
        payload_fields = set(request.model_dump())
        disallowed = payload_fields - ALLOWED_FIELDS - SYSTEM_FIELDS
        if disallowed:
            raise WorkflowTemplateError(
                f"request contains non-whitelisted fields: {sorted(disallowed)}"
            )

        workflow = copy.deepcopy(self.template)
        sampler = workflow[self.bindings["sampler_node"]]["inputs"]
        checkpoint = workflow[self.bindings["checkpoint_node"]]["inputs"]
        latent = workflow[self.bindings["latent_node"]]["inputs"]
        positive = workflow[self.bindings["positive_node"]]["inputs"]
        negative = workflow[self.bindings["negative_node"]]["inputs"]
        save = workflow[self.bindings["save_node"]]["inputs"]

        checkpoint["ckpt_name"] = request.base_model
        sampler.update(
            {
                "seed": request.seed + variant.seed_offset,
                "steps": request.steps,
                "cfg": round(request.cfg + variant.cfg_delta, 2),
                "sampler_name": request.sampler_name,
                "scheduler": request.scheduler,
            }
        )
        latent.update(
            {
                "width": request.width,
                "height": request.height,
                "batch_size": request.batch_size,
            }
        )
        positive["text"] = f"{request.positive_prompt}, {variant.prompt_suffix}"
        negative["text"] = request.negative_prompt
        save["filename_prefix"] = output_prefix
        self._apply_loras(workflow, request)
        self._apply_reference(workflow, uploaded_references or [])
        self.validate_compiled(workflow)
        return workflow

    def _apply_loras(self, workflow: dict, request: ImageGenerationRequest) -> None:
        anchor_id = self.bindings["lora_anchor_node"]
        anchor = copy.deepcopy(workflow.pop(anchor_id))
        model_ref: list = [self.bindings["checkpoint_node"], 0]
        clip_ref: list = [self.bindings["checkpoint_node"], 1]
        for index, lora in enumerate(request.loras):
            node_id = str(int(anchor_id) + index)
            node = copy.deepcopy(anchor)
            node["inputs"].update(
                {
                    "lora_name": lora.filename,
                    "strength_model": lora.weight,
                    "strength_clip": lora.weight,
                    "model": model_ref,
                    "clip": clip_ref,
                }
            )
            workflow[node_id] = node
            model_ref = [node_id, 0]
            clip_ref = [node_id, 1]

        workflow[self.bindings["sampler_node"]]["inputs"]["model"] = model_ref
        workflow[self.bindings["positive_node"]]["inputs"]["clip"] = clip_ref
        workflow[self.bindings["negative_node"]]["inputs"]["clip"] = clip_ref

    def _apply_reference(self, workflow: dict, references: list[dict]) -> None:
        node_id = self.bindings.get("reference_image_node")
        if node_id and references:
            workflow[node_id]["inputs"]["image"] = references[0]["name"]

    def _validate_template(self) -> None:
        for binding, class_type in REQUIRED_NODE_CLASSES.items():
            node_id = self.bindings.get(binding)
            if not node_id or node_id not in self.template:
                raise WorkflowTemplateError(f"template binding {binding} is missing")
            if self.template[node_id].get("class_type") != class_type:
                raise WorkflowTemplateError(
                    f"template node {node_id} must be {class_type}"
                )

    @staticmethod
    def validate_compiled(workflow: dict) -> None:
        if not workflow:
            raise WorkflowTemplateError("compiled workflow is empty")
        for node_id, node in workflow.items():
            if not isinstance(node, dict) or "class_type" not in node or "inputs" not in node:
                raise WorkflowTemplateError(f"invalid ComfyUI node: {node_id}")
