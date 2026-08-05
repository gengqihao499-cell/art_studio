# 熔断、降级与恢复

ArtFlow 有两类独立熔断，目的都是“停止无意义重试，同时保留可恢复入口”。

## Auto-compact 熔断

- 统计范围：单个 `session_id`。
- 失败来源：摘要字段不完整、快照写入失败或 Memory Agent 的压缩提交失败。
- 第 1–2 次失败：记录错误，本轮生成继续。
- 连续第 3 次失败：`circuit_state=open`，后续不再自动请求 Auto-compact。
- 恢复：右侧 Context Memory 点击“重置压缩熔断”，调用 `POST /api/sessions/{session_id}/context/compaction/reset`。
- 任意一次成功快照会把失败次数清零并关闭熔断。

状态存放在 SQLite `context_compactions`，包含失败数、最后错误、尝试/成功时间、快照版本和最新层指标。

## LangGraph 循环熔断

`LoopGuard` 观察节点名和结构化更新的语义签名：

- 同一语义签名连续出现 3 次时停止。
- 单节点访问次数超过 4 次时停止。
- 工作流写入 `circuit_opened` 事件并把本轮标记为失败，避免无限循环和持续 API 计费。
- 用户可以从 LangGraph Checkpoint 使用既有“恢复”按钮重试。

## 远程组件降级

- Milvus/Embedding 检索失败：返回空检索结果并继续用 SQLite + `CLAUDE.md`。
- 向量写入失败：`memory_items.embedding_status=failed`，结构化记忆仍保留。
- OSS 写入失败：当前大结果无法建立引用，错误会进入运行日志；切回 `ARTFLOW_BLOB_BACKEND=local` 后重启即可。
- 图片或文本 Provider 失败：保持现有运行失败/Checkpoint 恢复机制，不自动切换到 Mock，避免用户误把示例图当真实生成结果。

## 排查顺序

1. 查看页面顶部错误条和 Agent 执行过程。
2. 打开右侧“运行日志”，记录错误码与 request ID。
3. 访问 `/api/health`，检查 Provider 和 Context Engine 后端状态。
4. 检查启动窗口打印的实际 `.env` 路径，确认改的是当前项目副本。
5. 远程存储故障时先切回本地三项配置，验证核心生成链路，再分别恢复 Embedding、Milvus、OSS。

不要通过删除 SQLite 或 `storage/memory` 来“修复”熔断；这会丢失本地历史。使用面板/API 重置即可。
