# ArtFlow Studio 0.6.0

轻量、桌面端优先的多 Agent 游戏美术对话生成平台。重点放在后端 Agent 编排、连续修改、可追踪日志与长期上下文，不包含移动端、团队权限或复杂资产管理。

## 本版完成内容

- 真实多 Agent 链路：Memory → Intent Router → Brief → Art Director → Composition / Character / Color → Review → Curator → Prompt Compiler → Image Worker → Assistant。
- 多对话本地管理：新建、选择、删除；每次打开停留在“我们从哪里开始？”空白页，不自动打开历史会话。
- 首轮 4 张候选，后续基于选中父图每轮 2 张；保留父图、轮次、版本与生成元数据。
- Qwen 北京地域：文本 Agent 使用 `qwen-plus`，图片使用 `qwen-image-2.0`，不依赖 ComfyUI。
- 类 Claude Code 的分层记忆：全局与项目级 `CLAUDE.md`、五层上下文压缩、语义记忆检索和 3 次失败熔断。
- 完整 Agent 日志：调用原因、模型、输入/输出摘要、结构化结果、耗时、Token、重试和错误。
- 本地默认无付费调用；OSS、Milvus/Zilliz Cloud 与 Qwen Embedding 是可选远程适配器。

## 快速启动

1. 双击 `Setup-ArtFlow.cmd`。
2. 双击 `Start-ArtFlow.cmd`。
3. 浏览器打开 `http://127.0.0.1:8000`。
4. 输入不少于 8 个字符的美术需求并发送。
5. 在右侧查看 Agent 执行、结构化输出、运行日志和 Context Memory。

交付包已包含编译后的前端，普通使用不需要安装 Node.js。首次安装默认使用 Mock Agent + Mock Image，可无 API 费用跑通整条链路。

## 启用千问

双击 `Configure-Qwen.cmd`，在它打开的 `backend/.env` 中填写：

```dotenv
ARTFLOW_AGENT_BACKEND=qwen
ARTFLOW_IMAGE_BACKEND=qwen_image
DASHSCOPE_API_KEY=你的API Key
DASHSCOPE_WORKSPACE_ID=你的Workspace ID
DASHSCOPE_REGION=cn-beijing
QWEN_CHAT_MODEL=qwen-plus
QWEN_IMAGE_MODEL=qwen-image-2.0
```

保存后重启 `Start-ArtFlow.cmd`。API Key 只能保存在 `backend/.env`，不要写入前端或提交到版本库。详见 [千问北京地域接入](docs/qwen-beijing-guide.md)。

## 记忆与远程存储

默认配置使用 SQLite、本地文件 Blob Store 和离线 Hash Embedding；无需新增服务。需要远程记忆时，先双击 `Setup-Remote-Storage.cmd`，再按 [远程存储接入指南](docs/remote-storage-guide.md) 配置 OSS、Milvus/Zilliz Cloud 和 Qwen Embedding。

Milvus 只保存用于检索的向量与精简文本，不代替 SQLite；大结果和文件由本地目录或 OSS 保存。远程服务不可用时，检索会降级，原始对话仍保留在 SQLite。

## 文档入口

- [代码大纲与 Agent 地图](docs/code-map.md)
- [五层上下文与记忆架构](docs/context-memory-architecture.md)
- [远程存储接入指南](docs/remote-storage-guide.md)
- [熔断、降级与恢复](docs/failure-and-circuit-breaker.md)
- [原 Agent 职责地图](docs/agent-map.md)

## 开发测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm run lint
npm run build
```

后端运行数据默认在 `backend/storage`。测试或多实例运行可以设置 `ARTFLOW_STORAGE_DIR` 指向独立目录。
