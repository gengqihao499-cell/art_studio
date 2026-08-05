# ArtFlow Studio：ComfyUI 接入与完整运行指南

这份指南面向 Windows 本地运行。ArtFlow 负责需求理解、多 Agent 审评、Prompt/参数编译、结果归档；ComfyUI 只负责执行已经审核过的图像工作流。

## 1. 先用 Mock 跑通整套程序

解压 ArtFlow Studio 后：

1. 双击 `Setup-ArtFlow.cmd`。它会创建 `backend\.venv`、安装 Python 依赖，并创建默认的 `backend\.env`。
2. 双击 `Start-ArtFlow.cmd`。
3. 浏览器自动打开 `http://127.0.0.1:8000`。
4. 左侧填写不少于 8 个字符的需求，例如：

   ```text
   设计一名暗黑炼金术师首领，全身像，机械义肢环绕身体，冷色地下实验室，暖金炼金核心作为视觉焦点，用于动作游戏角色概念图。
   ```

5. 世界观可填写“衰败工业王国的地下炼金工坊”，比例选 `1:1`，数量选 `4`，点击“开始生成”。
6. 右侧会依次显示 Brief、Art Director、Composition、Character、Color、Curator、Workflow Compiler、Image Worker 的真实运行事件。
7. 中间出现 A/B/C/D 四张候选图后，点击任意候选完成选择，点击右上角下载按钮保存原图。

Mock 只替换最后的出图执行器；前面的 LangGraph、多 Agent 审评、SQLite、SSE、候选选择和下载流程都是真实运行的。

## 2. 安装并启动 ComfyUI

Windows 推荐使用官方 Portable 版本：下载后解压，NVIDIA 显卡双击 `run_nvidia_gpu.bat`，仅 CPU 时双击 `run_cpu.bat`。看到 `To see the GUI go to: http://127.0.0.1:8188` 才表示服务已启动；这个窗口不能关闭。

- 官方 Windows Portable 指南：https://docs.comfy.org/installation/comfyui_portable_windows
- 官方项目：https://github.com/comfy-org/comfyui
- 官方模型说明：https://docs.comfy.org/development/core-concepts/models

模型权重不会放进 ArtFlow 交付包，因为文件通常很大且有各自许可证。将模型放到：

```text
ComfyUI\models\checkpoints\你的模型.safetensors
ComfyUI\models\loras\你的LoRA.safetensors
```

当前内置模板使用 ComfyUI 核心节点 `CheckpointLoaderSimple + CLIPTextEncode + KSampler + VAEDecode`，适合能由 `Load Checkpoint` 直接加载的 SD/SDXL 类单文件 checkpoint。FLUX、SD3 等拆分 UNet/CLIP/VAE 的模型需要先在 ComfyUI 中制作并导出对应的自定义 API 工作流，不能直接套用内置模板。

建议先在 ComfyUI 页面中用同一模型手动成功生成一张图，再连接 ArtFlow。这样能先排除模型、显存和 ComfyUI 节点问题。

## 3. 配置 ArtFlow

用记事本打开 `backend\.env`，改成：

```dotenv
ARTFLOW_IMAGE_BACKEND=comfyui
ARTFLOW_BASE_MODEL=你的模型文件.safetensors
ARTFLOW_DEFAULT_LORA=

COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_TEMPLATE_PATH=
COMFYUI_TIMEOUT_SECONDS=300
COMFYUI_POLL_INTERVAL=0.5
COMFYUI_API_KEY=
```

规则：

- `ARTFLOW_BASE_MODEL` 必须与 ComfyUI 下拉框中显示的名字完全一致，包括子目录和扩展名。
- 没有 LoRA 就让 `ARTFLOW_DEFAULT_LORA=` 保持空值；使用时填写 ComfyUI 能识别的完整文件名。
- 本机标准 ComfyUI 不需要 API Key。
- 修改 `.env` 后必须重启 ArtFlow 后端。

然后在 ArtFlow 根目录运行连接检查：

```powershell
.\Test-ComfyUI.ps1
```

脚本会检查 8188 服务、Checkpoint 名称和 LoRA 名称。只有看到“ComfyUI 接入检查全部通过”后再启动 ArtFlow：

```powershell
.\Start-ArtFlow.ps1
```

页面候选区顶部应显示 `COMFYUI`；如果显示灰色离线状态，先检查 ComfyUI 的 8188 服务。

## 4. 一次真实生成会发生什么

```text
用户输入
  → Brief Agent 提取硬约束
  → Art Director 审核
  → 构图 / 角色 / 色彩 Agent 并行提案
  → Curator 组合方案并记录风险
  → Workflow Compiler 生成四组受控变化
  → ComfyUI Adapter 写入 checkpoint、prompt、seed、CFG、尺寸
  → POST /prompt 提交到 ComfyUI
  → 轮询 /history/{prompt_id}
  → GET /view 下载成图到 backend/storage/images
  → 页面显示候选，SQLite 保存元数据
```

四张候选分别强调：约束忠实、动态构图、清晰剪影和色彩氛围。ComfyUI 会按自己的队列执行；显存较小时等待时间会更长，但不需要同时加载四份模型。

每次提交给 ComfyUI 的最终 JSON 会保存在：

```text
backend\storage\workflows\{run_id}-{variant}.json
```

生成图片保存在 `backend\storage\images`，上传的参考图保存在 `backend\storage\uploads`，项目与 Agent 事件保存在 SQLite。

## 5. 参考图的重要限制

内置 `txt2img_core_v1` 是纯文生图模板，`reference_image_node` 当前为空。上传参考图会被 ArtFlow 保存并上传到 ComfyUI，但不会参与像素或特征条件控制。

如需 IPAdapter、ControlNet 或图生图：

1. 在 ComfyUI 中搭好并成功运行工作流。
2. 使用 **Save (API Format)** 导出 API JSON。
3. 按 `backend\workflows\README.md` 加入 `_artflow.bindings`。
4. 将 `reference_image_node` 指向一个 `LoadImage` 节点。
5. 在 `.env` 中将 `COMFYUI_TEMPLATE_PATH` 设为该 JSON 的绝对路径。

ArtFlow 只会修改白名单字段，不让 Agent 任意拼接未知节点。这是为了让生产工作流可审核、可复现。

## 6. 常见错误

### 8000 端口错误（WinError 10013 / 10048）

```powershell
netstat -ano | findstr :8000
Stop-Process -Id 这里填写PID -Force
```

本地交付启动脚本不使用 `--reload`，可减少 Uvicorn 父子进程残留。正常停止时在运行窗口按 `Ctrl+C`。

### ComfyUI 连接失败

- 浏览器直接打开 `http://127.0.0.1:8188`，确认页面可访问。
- 确认 ComfyUI 的命令行窗口仍在运行。
- 本机接入保持 `COMFYUI_BASE_URL=http://127.0.0.1:8188`，无需增加 `--listen`。

### `ckpt_name` 或 `lora_name` 不存在

运行 `.\Test-ComfyUI.ps1` 查看 ComfyUI 实际识别到的名称，再原样复制到 `.env`。移动模型文件后重启 ComfyUI。

### 显存不足

先在 ComfyUI 中降低分辨率或选更小模型。ArtFlow 当前支持 `1:1`（1024×1024）、`4:3`（1152×864）和 `3:4`（864×1152）；如所用模型无法承受这些尺寸，应先修改 `backend\app\agents\workflow_compiler.py` 中的尺寸映射。

### Agent 成功但 Image Worker 失败

修复 ComfyUI 或模型问题后，页面右侧点击“恢复任务”。系统会从最后一个 LangGraph checkpoint 继续，不重复执行前置 Agent。
