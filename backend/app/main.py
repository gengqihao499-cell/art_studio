import asyncio
import inspect
import json
import mimetypes
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.database import Database
from app.context import ContextEngine
from app.context.claude_memory import ClaudeMemoryStore
from app.graph import ArtDesignGraph
from app.image_backends import ComfyUIImageBackend, MockImageBackend, QwenImageBackend
from app.providers import MockChatProvider, QwenChatProvider
from app.schemas import CanvasSnapshotRequest, ClaudeMemoryUpdate, NewProjectRequest
from app.services import EventService, ProjectService, StyleService, WorkflowService
from app.services.agent_log_service import AgentLogService
from app.storage import (
    HashEmbeddingProvider,
    LocalBlobStore,
    LocalVectorStore,
    MilvusVectorStore,
    OSSBlobStore,
    QwenEmbeddingProvider,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIST_DIR = PROJECT_DIR / "frontend" / "dist"
load_dotenv(BACKEND_DIR / ".env")
# Tests and packaged deployments can point runtime data at an isolated folder.
# The source tree remains the default so existing desktop installations keep
# their conversations after upgrading.
configured_storage_dir = os.getenv("ARTFLOW_STORAGE_DIR", "").strip()
STORAGE_DIR = Path(configured_storage_dir or (BACKEND_DIR / "storage")).resolve()
IMAGES_DIR = STORAGE_DIR / "images"
UPLOADS_DIR = STORAGE_DIR / "uploads"
ASSETS_DIR = BACKEND_DIR / "assets" / "mock_candidates"
WORKFLOWS_DIR = STORAGE_DIR / "workflows"
LOGS_DIR = STORAGE_DIR / "logs"
ARTIFACTS_DIR = STORAGE_DIR / "artifacts"
MEMORY_DIR = STORAGE_DIR / "memory"
TEMPLATE_PATH = BACKEND_DIR / "workflows" / "templates" / "txt2img_core_v1.json"
DATABASE_PATH = STORAGE_DIR / "artflow.db"
CHECKPOINT_PATH = STORAGE_DIR / "langgraph-checkpoints.db"

IMAGE_BACKEND_NAME = os.getenv("ARTFLOW_IMAGE_BACKEND", "mock").strip().lower()
AGENT_BACKEND_NAME = os.getenv("ARTFLOW_AGENT_BACKEND", "mock").strip().lower()
DEFAULT_MODEL = os.getenv("ARTFLOW_BASE_MODEL", "z-image.safetensors")
DEFAULT_LORA = os.getenv("ARTFLOW_DEFAULT_LORA", "dark_alchemy_v1.safetensors")


def build_image_backend():
    if IMAGE_BACKEND_NAME == "qwen_image":
        return QwenImageBackend(
            api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
            workspace_id=os.getenv("DASHSCOPE_WORKSPACE_ID", "").strip(),
            api_host=os.getenv("DASHSCOPE_API_HOST", "").strip(),
            images_dir=IMAGES_DIR,
            storage_dir=STORAGE_DIR,
            model=os.getenv("QWEN_IMAGE_MODEL", "qwen-image-2.0"),
            timeout_seconds=float(os.getenv("QWEN_TIMEOUT_SECONDS", "180")),
            max_concurrency=int(os.getenv("QWEN_MAX_CONCURRENCY", "2")),
            prompt_extend=os.getenv("QWEN_PROMPT_EXTEND", "true").lower() == "true",
            watermark=os.getenv("QWEN_WATERMARK", "false").lower() == "true",
        )
    if IMAGE_BACKEND_NAME == "comfyui":
        configured_template = os.getenv("COMFYUI_TEMPLATE_PATH", "").strip()
        template_path = Path(configured_template) if configured_template else TEMPLATE_PATH
        return ComfyUIImageBackend(
            base_url=os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188"),
            images_dir=IMAGES_DIR,
            workflows_dir=WORKFLOWS_DIR,
            storage_dir=STORAGE_DIR,
            template_path=template_path,
            timeout_seconds=float(os.getenv("COMFYUI_TIMEOUT_SECONDS", "300")),
            poll_interval=float(os.getenv("COMFYUI_POLL_INTERVAL", "0.5")),
            api_key=os.getenv("COMFYUI_API_KEY", ""),
        )
    if IMAGE_BACKEND_NAME != "mock":
        raise RuntimeError("ARTFLOW_IMAGE_BACKEND must be 'mock', 'qwen_image', or 'comfyui'")
    return MockImageBackend(ASSETS_DIR, IMAGES_DIR)


def build_chat_provider():
    if AGENT_BACKEND_NAME == "qwen":
        return QwenChatProvider(
            api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
            workspace_id=os.getenv("DASHSCOPE_WORKSPACE_ID", "").strip(),
            api_host=os.getenv("DASHSCOPE_API_HOST", "").strip(),
            model=os.getenv("QWEN_CHAT_MODEL", "qwen-plus"),
            timeout_seconds=float(os.getenv("QWEN_TIMEOUT_SECONDS", "90")),
        )
    if AGENT_BACKEND_NAME != "mock":
        raise RuntimeError("ARTFLOW_AGENT_BACKEND must be 'mock' or 'qwen'")
    return MockChatProvider()


def build_blob_store():
    backend = os.getenv("ARTFLOW_BLOB_BACKEND", "local").strip().lower()
    if backend == "oss":
        return OSSBlobStore(
            endpoint=os.getenv("OSS_ENDPOINT", "").strip(),
            bucket=os.getenv("OSS_BUCKET", "").strip(),
            access_key_id=os.getenv("OSS_ACCESS_KEY_ID", "").strip(),
            access_key_secret=os.getenv("OSS_ACCESS_KEY_SECRET", "").strip(),
            prefix=os.getenv("OSS_PREFIX", "artflow").strip(),
        )
    if backend != "local":
        raise RuntimeError("ARTFLOW_BLOB_BACKEND must be 'local' or 'oss'")
    return LocalBlobStore(ARTIFACTS_DIR)


def build_embedding_provider():
    backend = os.getenv("ARTFLOW_EMBEDDING_BACKEND", "hash").strip().lower()
    dimension = int(os.getenv("ARTFLOW_EMBEDDING_DIMENSION", "768"))
    if backend == "qwen":
        return QwenEmbeddingProvider(
            api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
            workspace_id=os.getenv("DASHSCOPE_WORKSPACE_ID", "").strip(),
            api_host=os.getenv("DASHSCOPE_API_HOST", "").strip(),
            model=os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4"),
            dimension=dimension,
            timeout_seconds=float(os.getenv("QWEN_TIMEOUT_SECONDS", "90")),
        )
    if backend != "hash":
        raise RuntimeError("ARTFLOW_EMBEDDING_BACKEND must be 'hash' or 'qwen'")
    return HashEmbeddingProvider(dimension)


def build_vector_store(database: Database):
    backend = os.getenv("ARTFLOW_VECTOR_BACKEND", "local").strip().lower()
    if backend == "milvus":
        return MilvusVectorStore(
            uri=os.getenv("MILVUS_URI", "").strip(),
            token=os.getenv("MILVUS_TOKEN", "").strip(),
            collection=os.getenv("MILVUS_COLLECTION", "artflow_memories").strip(),
            dimension=int(os.getenv("ARTFLOW_EMBEDDING_DIMENSION", "768")),
        )
    if backend != "local":
        raise RuntimeError("ARTFLOW_VECTOR_BACKEND must be 'local' or 'milvus'")
    return LocalVectorStore(database)

database = Database(DATABASE_PATH)
image_backend = build_image_backend()
chat_provider = build_chat_provider()
blob_store = build_blob_store()
embedding_provider = build_embedding_provider()
vector_store = build_vector_store(database)
claude_memory_store = ClaudeMemoryStore(database, MEMORY_DIR, PROJECT_DIR / "CLAUDE.md")
context_engine = ContextEngine(
    database=database,
    claude_store=claude_memory_store,
    blob_store=blob_store,
    vector_store=vector_store,
    embedding_provider=embedding_provider,
    max_tokens=int(os.getenv("QWEN_CONTEXT_MAX_TOKENS", "12000")),
    auto_compact_ratio=float(os.getenv("ARTFLOW_AUTO_COMPACT_RATIO", "0.75")),
    artifact_inline_chars=int(os.getenv("ARTFLOW_ARTIFACT_INLINE_CHARS", "4000")),
    semantic_top_k=int(os.getenv("ARTFLOW_MEMORY_TOP_K", "6")),
)
project_service = ProjectService(
    database,
    ASSETS_DIR,
    IMAGES_DIR,
    context_recent_messages=int(os.getenv("QWEN_CONTEXT_RECENT_TURNS", "8")) * 2,
    context_max_tokens=int(os.getenv("QWEN_CONTEXT_MAX_TOKENS", "12000")),
    context_engine=context_engine,
)
style_service = StyleService(database, DEFAULT_MODEL, DEFAULT_LORA)
event_service = EventService(database)
agent_log_service = AgentLogService(database, LOGS_DIR, context_engine.offloader)
workflow_service = WorkflowService(project_service, event_service)
running_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    database.initialize()
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_PATH)) as checkpointer:
        workflow_service.set_graph(
            ArtDesignGraph(
                checkpointer,
                image_backend,
                chat_provider,
                agent_log_service,
                context_engine,
            ).compiled
        )
        yield
        for task in running_tasks:
            if not task.done():
                task.cancel()
        for resource in (chat_provider, image_backend):
            close = getattr(resource, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result
        close_embedding = getattr(embedding_provider, "close", None)
        if close_embedding:
            close_embedding()


app = FastAPI(
    title="ArtFlow Studio API",
    version="0.6.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# A freshly extracted package intentionally contains no runtime storage data.
# The lifespan creates the directory before requests are served; disabling the
# eager directory check prevents Starlette from failing during module import.
app.mount("/storage", StaticFiles(directory=STORAGE_DIR, check_dir=False), name="storage")


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "orchestrator": "langgraph",
        "image_backend": image_backend.name,
        "image_backend_health": await image_backend.health(),
        "agent_backend": chat_provider.name,
        "agent_model": chat_provider.model,
        "agent_backend_health": await chat_provider.health(),
        "database": "sqlite",
        "context_engine": context_engine.health(),
        "demo_mode": image_backend.name == "mock" or chat_provider.name == "mock",
    }


@app.get("/api/conversations")
def list_conversations() -> dict:
    return {"items": project_service.list_conversations()}


@app.post("/api/conversations")
def create_conversation(request: NewProjectRequest) -> dict:
    project = project_service.create_project(request.name)
    style_service.ensure_default(project["project"]["id"])
    return project_service.get_project(project["project"]["id"])


@app.delete("/api/conversations/{session_id}")
def delete_conversation(session_id: str) -> dict:
    try:
        return project_service.delete_conversation(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/projects/default")
def get_default_project() -> dict:
    return project_service.get_project()


@app.get("/api/projects/recent")
def get_recent_project() -> dict:
    return project_service.get_recent_project()


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    try:
        return project_service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.post("/api/projects")
def create_project(request: NewProjectRequest) -> dict:
    project = project_service.create_project(request.name)
    style_service.ensure_default(project["project"]["id"])
    return project_service.get_project(project["project"]["id"])


@app.get("/api/projects/{project_id}/styles")
def list_styles(project_id: str) -> dict:
    try:
        selected = style_service.get_selected(project_id)
        return {
            "selected_style_profile_id": selected["id"],
            "styles": style_service.list_for_project(project_id),
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@app.post("/api/projects/{project_id}/generate", status_code=202)
async def generate(
    project_id: str,
    prompt: str = Form(...),
    world_context: str = Form(""),
    aspect_ratio: str = Form("1:1"),
    image_count: int = Form(4),
    reference_images: list[UploadFile] = File(default=[]),
) -> dict:
    if len(prompt.strip()) < 8:
        raise HTTPException(status_code=422, detail="需求描述至少需要 8 个字符")
    del image_count  # The backend enforces 4 candidates on turn 1 and 2 thereafter.
    saved_references: list[str] = []
    for upload in reference_images[:5]:
        suffix = Path(upload.filename or "reference.png").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=415, detail="只支持 PNG、JPG 和 WebP 参考图")
        filename = f"ref_{uuid.uuid4().hex[:12]}{suffix}"
        destination = UPLOADS_DIR / filename
        with destination.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        saved_references.append(f"/storage/uploads/{filename}")

    try:
        current = project_service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    if not saved_references:
        saved_references = current["project"]["reference_images"]
    style_profile = style_service.get_selected(project_id)

    run_id, turn_id, initial_state = project_service.create_conversation_turn(
        project_id=project_id,
        prompt=prompt.strip(),
        world_context=world_context.strip(),
        aspect_ratio=aspect_ratio,
        reference_images=saved_references,
        style_profile=style_profile,
        image_backend=image_backend.name,
        image_model=getattr(image_backend, "model", DEFAULT_MODEL),
    )
    task = asyncio.create_task(workflow_service.execute(initial_state))
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)
    return {"run_id": run_id, "turn_id": turn_id, "status": "running"}


@app.post("/api/sessions/{session_id}/turns", status_code=202)
async def create_turn(
    session_id: str,
    message: str = Form(...),
    world_context: str = Form(""),
    aspect_ratio: str = Form("1:1"),
    reference_images: list[UploadFile] = File(default=[]),
) -> dict:
    with database.connect() as connection:
        session = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if len(message.strip()) < 2:
        raise HTTPException(status_code=422, detail="请输入至少 2 个字符")
    saved_references: list[str] = []
    for upload in reference_images[:5]:
        suffix = Path(upload.filename or "reference.png").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(status_code=415, detail="只支持 PNG、JPG 和 WebP 参考图")
        filename = f"ref_{uuid.uuid4().hex[:12]}{suffix}"
        destination = UPLOADS_DIR / filename
        with destination.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        saved_references.append(f"/storage/uploads/{filename}")
    project_id = str(session["project_id"])
    current = project_service.get_project(project_id)
    if not saved_references:
        saved_references = current["project"]["reference_images"]
    run_id, turn_id, initial_state = project_service.create_conversation_turn(
        project_id=project_id,
        prompt=message.strip(),
        world_context=world_context.strip() or current["project"]["world_context"],
        aspect_ratio=aspect_ratio,
        reference_images=saved_references,
        style_profile=style_service.get_selected(project_id),
        image_backend=image_backend.name,
        image_model=getattr(image_backend, "model", DEFAULT_MODEL),
    )
    task = asyncio.create_task(workflow_service.execute(initial_state))
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)
    return {"run_id": run_id, "turn_id": turn_id, "status": "running"}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    with database.connect() as connection:
        session = connection.execute("SELECT project_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return project_service.get_project(str(session["project_id"]))


@app.get("/api/projects/{project_id}/context")
def get_project_context(project_id: str) -> dict:
    try:
        payload = project_service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return payload["context_status"]


@app.put("/api/projects/{project_id}/context/claude")
def update_project_claude(project_id: str, request: ClaudeMemoryUpdate) -> dict:
    try:
        payload = project_service.get_project(project_id)
        return context_engine.replace_claude(
            project_id,
            str(payload["project"]["name"]),
            request.content,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/context/compaction/reset")
def reset_compaction_breaker(session_id: str) -> dict:
    try:
        return context_engine.reset_compaction_breaker(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@app.get("/api/turns/{turn_id}")
def get_turn(turn_id: str) -> dict:
    try:
        return project_service.get_turn(turn_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Turn not found") from exc


@app.get("/api/runs/{run_id}/agent-logs")
def get_agent_logs(run_id: str) -> dict:
    if event_service.run_status(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "items": agent_log_service.list_for_run(run_id)}


@app.post("/api/runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str) -> dict:
    try:
        project_id = project_service.prepare_retry(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task = asyncio.create_task(workflow_service.resume(run_id, project_id))
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)
    return {"run_id": run_id, "status": "running", "resumed_from_checkpoint": True}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        return project_service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@app.get("/api/runs/{run_id}/events")
async def stream_run_events(run_id: str, after: int = 0) -> StreamingResponse:
    if event_service.run_status(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream():
        sequence = max(0, after)
        while True:
            events = event_service.list_after(run_id, sequence)
            for event in events:
                sequence = int(event["sequence"])
                data = json.dumps(event, ensure_ascii=False)
                yield f"event: agent_event\ndata: {data}\n\n"
            status = event_service.run_status(run_id)
            if status in {"completed", "failed"}:
                data = json.dumps({"run_id": run_id, "status": status})
                yield f"event: run_{status}\ndata: {data}\n\n"
                break
            await asyncio.sleep(0.12)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/projects/{project_id}/canvas")
def save_canvas(project_id: str, snapshot: CanvasSnapshotRequest) -> dict:
    try:
        return project_service.save_canvas(project_id, snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Image not found") from exc


@app.get("/api/images/{image_id}/download")
def download_image(image_id: str) -> FileResponse:
    with database.connect() as connection:
        image = connection.execute(
            "SELECT * FROM generated_images WHERE id = ?", (image_id,)
        ).fetchone()
    if not image or not Path(image["file_path"]).exists():
        raise HTTPException(status_code=404, detail="Image not found")
    suffix = Path(image["file_path"]).suffix.lower() or ".png"
    filename = f"artflow-{image['label'].lower()}-{image_id}{suffix}"
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(image["file_path"], media_type=media_type, filename=filename)


@app.get("/api/images/{image_id}/metadata")
def image_metadata(image_id: str) -> dict:
    try:
        return project_service.get_image_metadata(image_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Image not found") from exc


# The packaged local build is served by FastAPI so users only need one process.
# API and storage routes are registered first and therefore keep precedence.
if FRONTEND_DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="frontend")
