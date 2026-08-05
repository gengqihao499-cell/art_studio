# Agent 代码与组合边界

## 运行顺序

```text
Memory Agent
  ↓
Intent Router ── chat ──→ Assistant Agent
  ↓ generate
Brief Agent
  ↓
Art Director（统一方向）
  ↓
Composition / Character / Color（并行；按需调用，未选中则记录跳过）
  ↓
Art Director Review（只审核）
  ↓
Curator（唯一组合点）
  ↓
Prompt Compiler
  ↓
Image Worker
  ↓
Assistant Agent
```

## 文件位置

| Agent | 文件 | 只负责 |
|---|---|---|
| Memory | `backend/app/agents/memory_agent.py` | 结构化长期记忆与上下文预算 |
| Intent Router | `backend/app/agents/intent_router.py` | chat/generate 路由与专业 Agent 选择 |
| Brief | `backend/app/agents/brief_agent.py` | 可验证约束和输出规格 |
| Art Director | `backend/app/agents/art_director.py` | 共享方向与独立审核 |
| Composition | `backend/app/agents/composition_agent.py` | 镜头、构图、空间层次 |
| Character | `backend/app/agents/character_agent.py` | 角色、服装、姿态、道具 |
| Color | `backend/app/agents/color_agent.py` | 色板、光照、材质色 |
| Curator | `backend/app/agents/curator_agent.py` | 选择并组合审核后的提案 |
| Prompt Compiler | `backend/app/agents/workflow_compiler.py` | 模型提示词和 A/B/C/D 变化 |
| Image Worker | `backend/app/agents/image_worker.py` | 调用图像 Provider 并本地归档 |
| Assistant | `backend/app/agents/assistant_agent.py` | 用户可见回复 |

编排与组合边界的显式注释位于 `backend/app/graph/art_design_graph.py`。所有文本 Agent 通过 `AgentRuntime` 调用 Provider；每次调用由 `AgentLogService` 写入 `agent_invocations` 和 JSONL。

## 日志字段

- 执行原因和状态（completed / skipped / failed）
- Agent、模型、attempt
- 脱敏后的输入/输出摘要
- 结构化输出
- latency、input tokens、output tokens
- error code / error message

日志不接受或存储 API Key。
