# ArtFlow Studio 长期工程记忆

本文件是所有 ArtFlow 对话共享的只读全局记忆，在各 Agent 读取用户消息之前加载。每个美术对话还会维护独立的 `backend/storage/memory/{project_id}/CLAUDE.md`。

## 产品边界

- 这是轻量、桌面端优先的多 Agent 游戏美术生成平台，重点是后端 Agent 编排、可追踪性和连续修改。
- 不加入移动端、团队权限、复杂资产管理或与核心创作链路无关的功能。
- 首轮生成 4 张候选，后续每轮基于选中父图生成 2 张。
- SQLite 中的原始消息、图片元数据和 Agent 日志是本地事实来源，压缩不得删除原始消息。

## Agent 边界

- Memory Agent 维护结构化长期记忆和项目级 `CLAUDE.md`。
- Intent Router 只决定本轮需要调用哪些专业 Agent。
- Brief Agent 提取硬约束、软约束和交付目标。
- Art Director 制定方向并审核一致性，不代替专业 Agent 输出细节。
- Composition、Character、Color Agent 分别处理构图、角色和色彩。
- Curator 是唯一允许组合专业方案的节点。
- Prompt Compiler 只把已审核方案编译为图像提示词。
- Image Worker 只负责调用图像后端和持久化结果。

## 上下文不变量

- 大结果先落 Blob Store，再把可寻址引用放入模型上下文。
- Snip、Micro-compact 和 Context Collapse 都是读时投影，不覆盖 SQLite 原文。
- Auto-compact 生成带版本的不可变快照；连续失败 3 次后打开熔断器，必须人工重置。
- 项目 `CLAUDE.md` 中只有 `ARTFLOW:AUTO-MEMORY` 标记之间的内容可由 Memory Agent 自动改写。
- 向量检索失败时应降级为 SQLite + `CLAUDE.md`，不得阻断生成主链路。

## 安全与可维护性

- API Key、Workspace ID、OSS Secret 和 Milvus Token 只放在 `backend/.env`，不得写入代码、日志、文档示例或前端。
- 默认安装必须保持本地可运行；OSS、Milvus 和 Qwen Embedding 都是可选适配器。
- 新增 Agent 或修改组合边界时同步更新 `docs/code-map.md` 和测试。
