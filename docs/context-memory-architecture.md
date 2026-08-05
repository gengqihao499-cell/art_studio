# 五层上下文与记忆架构

## 设计原则

压缩只改变“本轮给模型看什么”，不删除 SQLite 中的原始消息。`CLAUDE.md`、不可变快照和向量索引是长期记忆的不同视图，任何一个远程组件失效都不应破坏生成主链路。

```text
用户消息 + SQLite 原文 + 当前画布
          ↓
全局 CLAUDE.md → 项目 CLAUDE.md
          ↓
Layer 1 Artifact Offload（大结果变引用）
          ↓
Layer 2 Snip（远古低相关内容仅保留预览/引用）
          ↓
Layer 3 Micro-compact（时间衰减 + 相关性 + 锁定约束）
          ↓
Layer 4 Context Collapse（按 Agent 职责读时投影）
          ↓
Layer 5 Auto-compact（版本化全量摘要）
          ↓
目标 Agent
```

## Layer 1：大结果落存储

当消息或 Agent 结构化结果超过 `ARTFLOW_ARTIFACT_INLINE_CHARS`（默认 4000 字符）时：

1. 计算 SHA-256，形成可去重的 Artifact ID。
2. 内容写入本地 `storage/artifacts` 或 OSS。
3. SQLite `context_artifacts` 只保存 URI、预览、Hash、大小和来源。
4. 模型上下文只携带预览和可寻址引用。

## Layer 2：Snip

远古消息若与当前请求相关性低、未命中锁定约束，且已有 Artifact，则只保留约 420 字的预览和 Artifact 引用。原文仍在 SQLite/Blob Store。

## Layer 3：Micro-compact

- 最近 2 轮：完整保留。
- 第 3–8 轮：最多约 520 字的微型投影。
- 更早内容：按当前请求词项重叠、时间衰减和锁定约束计算相关分。
- 时间衰减半衰期默认 6 轮；锁定约束获得额外权重，不会因为“年代久远”轻易消失。

## Layer 4：Context Collapse

同一份事实在读取时按 Agent 角色投影：

- Composition：目标、锁定约束、构图事实、父图。
- Character：目标、锁定约束、角色事实、父图。
- Color：目标、锁定约束、风格决定、父图。
- Prompt Compiler：目标、约束、风格、角色、构图和父图。
- 未配置专属字段的 Agent 读取完整结构化 Memory。

这样不会复制或改写事实，只减少每个 Agent 无关的输入。

## Layer 5：Auto-compact

满足任一条件时请求全量摘要：

- 原始对话 Token 估算超过 `QWEN_CONTEXT_MAX_TOKENS × ARTFLOW_AUTO_COMPACT_RATIO`。
- 达到预算管理器设定的周期检查点。

Memory Agent 成功后会：

1. 校验 8 个长期记忆字段。
2. 更新项目 `CLAUDE.md` 自动托管块。
3. 写入 `memory_snapshots` 不可变版本。
4. 将可检索事实写入 `memory_items` 和本地/Milvus 向量库。

Auto-compact 连续失败 3 次后熔断，不再自动重试。右侧 Context Memory 面板可人工重置。

## CLAUDE.md 加载顺序

1. 仓库根目录 `CLAUDE.md`：产品边界、Agent 边界、安全规则；运行时只读。
2. `backend/storage/memory/{project_id}/CLAUDE.md`：当前美术对话的长期记忆。
3. 当前 System Prompt。
4. 本轮按角色投影的用户上下文。

项目文件只有以下标记之间允许 Memory Agent 改写：

```html
<!-- ARTFLOW:AUTO-MEMORY:BEGIN -->
...
<!-- ARTFLOW:AUTO-MEMORY:END -->
```

用户写在标记外的长期备注会保留。每次修改前的版本归档到 `history/`。

## 数据表

- `messages`：完整原始消息，事实来源。
- `conversation_memory`：当前工作摘要。
- `context_artifacts`：大结果的地址与校验信息。
- `memory_snapshots`：Auto-compact 不可变版本。
- `context_compactions`：预算、失败次数、熔断状态和最新层指标。
- `project_context_files`：项目 CLAUDE 文件版本与 Hash。
- `memory_items`：可检索的语义记忆清单。
- `memory_vectors`：本地模式的向量数据；远程模式写入 Milvus。
