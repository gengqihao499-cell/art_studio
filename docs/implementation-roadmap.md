# 实施路线

## 第一阶段：可用最小平台（已实现）

- 输入文字需求、世界观和 1–5 张参考图。
- 一次生成 3–4 张候选图并自动进入画布。
- 候选图可选择、单图下载。
- 项目、输入、Agent 事件、图片元数据、选择状态保存到 SQLite。
- 图片和上传文件保存到本地 storage 目录。

## 第二阶段：多 Agent 审评工作流（已实现）

- 引入 Brief Agent 与结构化约束 schema。
- Composition / Character / Color 三条分支通过 LangGraph fan-out 并行执行。
- Art Director 仅评审，不重写专业 Agent 输出。
- 只重试未通过分支，最多三次；超限后带风险说明继续 Curator。
- 统一 SSE 事件格式，刷新后恢复完整结构化时间线。
- LangGraph checkpoint 与业务数据分别持久化到 SQLite。
- 保持桌面端轻量工作台，不扩展移动端和非核心管理功能。

## 第三阶段：ComfyUI 与风格系统（已实现）

- Workflow Compiler 只输出模型无关请求和允许修改的模板字段。
- ComfyUI Adapter 写入人工维护、通过 schema 校验的工作流模板。
- 四张候选图分别体现约束、构图、剪影和色彩的受控变化。
- 保存 prompt、模型、seed、LoRA、完整 workflow JSON 和 checkpoint。
- 参考图上传到 ComfyUI，并允许经审核模板绑定到 IPAdapter / ControlNet 节点。
- 图像后端失败时从最后 checkpoint 恢复，只重试生成阶段。
- 默认继续提供 Mock 后端，保证没有 GPU 服务时仍可开发和演示。
