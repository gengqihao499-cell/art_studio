# 远程存储接入指南

## 先理解三类数据

ArtFlow 不会把所有数据都塞进 Milvus：

- SQLite：对话、轮次、图片元数据、Agent 日志和状态，是本地事实来源。
- Blob Store：长文本/大 JSON 等 Artifact；默认本地，可切到阿里云 OSS。
- Vector Store：长期记忆的向量索引；默认 SQLite，可切到 Milvus/Zilliz Cloud。

推荐先只接 Milvus + Qwen Embedding，确认语义检索稳定后再把 Artifact 切到 OSS。

## 1. 安装可选依赖

先完成普通安装，再双击：

```text
Setup-Remote-Storage.cmd
```

它只安装 `oss2` 与 `pymilvus`，并打开实际使用的 `backend/.env`。普通本地模式不需要这些包。

## 2. 接入 Zilliz Cloud（托管 Milvus）

1. 在 Zilliz Cloud 创建 Free/Serverless 集群。
2. 在集群详情的 Connect 区复制 Public Endpoint。
3. 创建 API Key，或使用 `username:password` 形式的集群凭证。
4. 在 `backend/.env` 填写：

```dotenv
ARTFLOW_VECTOR_BACKEND=milvus
ARTFLOW_EMBEDDING_BACKEND=qwen
ARTFLOW_EMBEDDING_DIMENSION=768
MILVUS_URI=https://你的集群Endpoint
MILVUS_TOKEN=你的API Key
MILVUS_COLLECTION=artflow_memories
QWEN_EMBEDDING_MODEL=text-embedding-v4
```

官方说明中，`MilvusClient` 使用集群 Endpoint 作为 `uri`，Token 可以是 API Key 或 `username:password`。ArtFlow 首次写入时会自动创建 768 维、COSINE、AUTOINDEX 的集合：[Zilliz 连接说明](https://docs.zilliz.com/docs/connect-to-cluster)、[Python SDK](https://docs.zilliz.com/reference/python)。

注意：集合维度一旦创建不能随意改。若修改 `ARTFLOW_EMBEDDING_DIMENSION`，请同时使用一个新的 `MILVUS_COLLECTION` 名称。

## 3. 启用 Qwen Embedding

继续使用现有北京地域凭证：

```dotenv
DASHSCOPE_API_KEY=你的API Key
DASHSCOPE_WORKSPACE_ID=你的Workspace ID
DASHSCOPE_REGION=cn-beijing
ARTFLOW_EMBEDDING_BACKEND=qwen
QWEN_EMBEDDING_MODEL=text-embedding-v4
ARTFLOW_EMBEDDING_DIMENSION=768
```

`text-embedding-v4` 支持 768 维，北京地域 API 与 Workspace 绑定。维度必须与 Milvus 集合一致：[百炼 Embedding 官方说明](https://help.aliyun.com/en/model-studio/embedding)。

## 4. 可选：接入阿里云 OSS

1. 在北京地域创建私有 Bucket。
2. 创建 RAM 用户并只授予目标 Bucket 所需的读写权限，不使用主账号 AccessKey。
3. 获取 Bucket 的外网 Endpoint。
4. 在 `.env` 填写：

```dotenv
ARTFLOW_BLOB_BACKEND=oss
OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com
OSS_BUCKET=你的Bucket名称
OSS_ACCESS_KEY_ID=RAM用户AccessKeyId
OSS_ACCESS_KEY_SECRET=RAM用户AccessKeySecret
OSS_PREFIX=artflow
```

OSS SDK 要求 Endpoint 与 Bucket 地域对应；阿里云也建议使用 RAM 用户而不是主账号凭证：[OSS Python 初始化](https://help.aliyun.com/en/oss/initialization-2)、[创建 Bucket 与权限注意事项](https://help.aliyun.com/en/oss/developer-reference/create-buckets)。

Artifact 使用私有 `oss://bucket/key` URI，不要求 Bucket 公网可读，内容由后端凭证读取。

## 5. 验证

重启 `Start-ArtFlow.cmd`，然后打开：

```text
http://127.0.0.1:8000/api/health
```

预期 `context_engine` 类似：

```json
{
  "blob": {"available": true, "backend": "oss"},
  "vector": {"available": true, "backend": "milvus"},
  "embedding": {"available": true, "backend": "qwen", "dimension": 768}
}
```

再完成两轮对话，在右侧 Context Memory 检查：

- Vector 显示 `milvus`。
- Embedding 显示 `qwen`。
- “向量记忆”数量大于 0。
- 后续请求的检索数量逐渐出现大于 0 的结果。

## 6. 回退到本地

远程服务故障时先恢复以下配置并重启：

```dotenv
ARTFLOW_BLOB_BACKEND=local
ARTFLOW_VECTOR_BACKEND=local
ARTFLOW_EMBEDDING_BACKEND=hash
```

之前的 SQLite 原文不会丢失。远程 Milvus/OSS 中已写入的数据也不会被删除，只是不再被当前实例读取。
