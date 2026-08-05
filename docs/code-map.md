# ArtFlow Studio 代码大纲

这份大纲按“入口 → 编排 → Agent → 上下文 → 存储 → 前端”说明代码位置。阅读后端时建议从 `app/main.py` 开始，再进入 Graph 和各 Agent。

## 1. 启动与 API

- `backend/app/main.py`
  - 创建 FastAPI、SQLite、LangGraph Checkpointer。
  - 按 `.env` 选择 Mock / Qwen / ComfyUI 图片后端。
  - 组装 Context Engine 的 Blob、Vector、Embedding 适配器。
  - 提供对话、生成、事件、Agent 日志、图片、CLAUDE 记忆和熔断重置 API。
- `backend/app/database.py`
  - 所有 SQLite 表和兼容旧数据库的迁移入口。
  - 原始对话事实与上下文投影表彼此分离。

## 2. 多 Agent 编排

- `backend/app/graph/art_design_graph.py`
  - LangGraph 的节点、条件边和执行顺序。
  - 是“哪些 Agent 组合起来运行”的核心文件。
- `backend/app/services/workflow_service.py`
  - 启动/恢复 Graph、写 SSE 事件、执行循环熔断。
- `backend/app/services/project_service.py`
  - 创建对话轮次、拼接上下文输入、保存图片和版本关系。
- `backend/app/services/agent_log_service.py`
  - 记录每次 Agent 调用；超大结构化输出会先落 Blob Store。

## 3. 各 Agent 文件

`backend/app/agents/` 下每个文件顶部都注明职责、输入、输出和不负责事项：

- `memory_agent.py`：提取 8 类结构化记忆，维护项目 `CLAUDE.md`，触发 Auto-compact。
- `intent_router_agent.py`：识别生成/修改意图并选择必要的专业 Agent。
- `brief_agent.py`：把自然语言整理成硬约束、软约束和交付规格。
- `art_director_agent.py`：确立方向并审核专业输出的一致性。
- `composition_agent.py`：构图、景别、视线和层次。
- `character_agent.py`：角色轮廓、服装、道具、姿态和叙事特征。
- `color_agent.py`：主辅色、光源、材质分离和焦点。
- `curator_agent.py`：唯一允许组合专业提案的 Agent。
- `prompt_compiler_agent.py`：把审核后的方案编译为候选 Prompt。
- `image_worker_agent.py`：调用图片 Provider 并保存结果。
- `assistant_agent.py`：向用户解释本轮结果和下一步修改方式。
- `common.py`：统一 AgentRuntime、结构化调用、日志与按角色读取上下文。

## 4. 上下文与记忆

- `backend/app/context/context_engine.py`：五层管线总入口、状态、快照、向量索引与恢复。
- `budget_manager.py`：Token 估算和 Auto-compact 阈值。
- `claude_memory.py`：全局 + 项目级 `CLAUDE.md`，自动托管块和历史版本。
- `artifact_offloader.py`：Layer 1，大结果落磁盘/OSS并返回引用。
- `micro_compactor.py`：Layer 2/3，Snip 与时间衰减 Micro-compact。
- `context_projector.py`：Layer 4，按 Agent 职责做读时投影。
- `loop_guard.py`：LangGraph 语义循环熔断。

项目记忆文件位于：

```text
CLAUDE.md                                      # 全局，只读
backend/storage/memory/{project_id}/CLAUDE.md # 项目级，可自动维护
backend/storage/memory/{project_id}/history/  # 历史版本
```

## 5. 存储适配器

- `backend/app/storage/base.py`：BlobStore、VectorStore、EmbeddingProvider 协议。
- `local_blob_store.py`：本地大结果。
- `oss_blob_store.py`：阿里云 OSS 可选适配器。
- `local_vector_store.py`：SQLite 向量与余弦检索，默认模式。
- `milvus_vector_store.py`：Milvus/Zilliz Cloud 可选适配器。
- `embedding.py`：离线 Hash Embedding 和 Qwen `text-embedding-v4`。

## 6. 前端

- `frontend/src/App.tsx`：空白首页、多对话切换、生成事件和整体状态。
- `frontend/src/components/AgentInspector.tsx`：执行过程、Agent 输出、日志和五层 Context Memory。
- `frontend/src/services/api.ts`：所有 API 与 SSE 客户端。
- `frontend/src/types/artflow.ts`：前后端数据结构。
- `frontend/src/styles.css`：轻量桌面端布局。

## 7. 测试

- `backend/tests/test_context_engine.py`：五层投影、CLAUDE 托管块、向量记忆、快照、3 次失败熔断和 LoopGuard。
- 其他 `backend/tests/test_*.py`：Agent 路由、图像后端、Qwen Provider 和项目服务。
- 前端通过 `npm run lint` 与 `npm run build` 校验。
