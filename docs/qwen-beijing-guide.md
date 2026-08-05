# 千问北京区接入指南

ArtFlow 的文本 Agent 和图像生成是两个独立 Provider。推荐同时启用：`qwen-plus` 负责结构化 Agent 推理，`qwen-image-2.0` 负责首次生成和参考图编辑。

## 1. 准备凭证

在阿里云百炼北京地域取得：

- API Key
- Workspace ID

两者都只填写到本机 `backend/.env`。后端不会把 Key 写入 SQLite、JSONL 日志或浏览器响应。

## 2. 修改配置

先运行一次 `Setup-ArtFlow.cmd`，然后双击 `Configure-Qwen.cmd`。它会打开当前项目副本真正读取的 `backend/.env`，避免误改到另一份项目。设置：

```dotenv
ARTFLOW_AGENT_BACKEND=qwen
ARTFLOW_IMAGE_BACKEND=qwen_image
DASHSCOPE_API_KEY=替换为你的API Key
DASHSCOPE_WORKSPACE_ID=替换为你的Workspace ID
# 可选：如果控制台明确给了 API Host，也可填写主机地址（不要包含接口路径）
DASHSCOPE_API_HOST=
DASHSCOPE_REGION=cn-beijing
QWEN_CHAT_MODEL=qwen-plus
QWEN_IMAGE_MODEL=qwen-image-2.0
QWEN_PROMPT_EXTEND=true
QWEN_WATERMARK=false
QWEN_TIMEOUT_SECONDS=180
QWEN_MAX_CONCURRENCY=2
QWEN_CONTEXT_MAX_TOKENS=12000
QWEN_CONTEXT_RECENT_TURNS=8
```

北京区文本接口由后端调用：

```text
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions
```

北京区图像接口由后端调用：

```text
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
```

## 3. 重启并检查

关闭已有 ArtFlow 启动窗口，再双击 `Start-ArtFlow.cmd`。启动窗口首先会打印本次实际读取的 `.env` 完整路径。打开：

```text
http://127.0.0.1:8000/api/health
```

正常时应看到：

```json
{
  "agent_backend": "qwen",
  "agent_model": "qwen-plus",
  "image_backend": "qwen_image"
}
```

页面右上角不应再显示 `MOCK`，首页也不应再出现“不会调用千问 API”的黄色提示。如果仍显示，说明当前读取的 `.env` 仍是 Mock 配置；这时图片不会变化，千问也不会产生流量。

## 4. 完整跑一轮

1. 底部输入完整需求并发送。
2. 右侧按顺序出现 Memory、Intent Router、Brief、Art Director、专业 Agent、Curator、Prompt Compiler、Image Worker、Assistant。
3. 首轮四张结果出现后选择一张。
4. 输入“把月亮放大，其他内容保持不变”等局部修改。
5. Intent Router 只选择必要专业 Agent；下轮以选中图片为参考，生成两张新版本。
6. 在“运行日志”查看模型、耗时和 Token，在 “Context Memory” 查看压缩后的长期记忆。

Qwen 返回的临时图片 URL 会立即下载到 `backend/storage/images`，页面使用的是本地归档，不依赖远程 URL 的有效期。

## 常见问题

- 启动即提示缺少配置：确认 `.env` 中 Key 与 Workspace ID 均非空，变量名没有中文空格。
- HTTP 401/403：检查 Key、Workspace 权限和北京地域是否匹配。
- HTTP 429：降低 `QWEN_MAX_CONCURRENCY` 到 `1`，稍后再试。
- 图像超时：适当提高 `QWEN_TIMEOUT_SECONDS`，并在右侧日志记录 request ID。
- 暂时不想产生费用：把两个后端都改回 `mock`；对话、版本、日志和 UI 仍可完整测试。
