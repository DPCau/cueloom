# 10 · 本地模型资产目录与模型工作台

> 新增于 2026-11-09 的项目会话，落地用户追加的 U-7 ~ U-10 目标。
> 本文只定义**设计**；工作台代码、注册表文件、API 路由与菜单实现留到 M0.6（§13）。
> 与既有文档的关系：数据面契约仍以 `03` 为准，运维形态以 `09` 为准；本文与 `09 §7`、「看板只读」条款冲突处，以本文 + `07` 新增 ADR 为准，旧条目标记修订原因，不改写历史结论。
>
> **2026-11-09 第二次修订（U-11~U-13，见 `12`）**：用户明确看板与工作台是同一个浏览器界面，**D-16 结清为方案 B（浏览器可写）**。本文 §4~§8 的目录布局、注册表、四态扫描、下载与删除护栏全部有效且不变；§9 的「方案 A 优先」与「先 A 后 B」建议已被 ADR-014 取代——模型管理统一走浏览器「模型」标签页，`ctl.sh` 菜单 10 降级为 CLI 兜底。§13 第 5 步并入 M0.7（`12 §14`）。

## 1. 新目标

| 编号 | 用户目标（2026-11-09 追加） | 落地方式 |
|---|---|---|
| U-7 | 模型目录与项目目录在一起，不放系统目录 | `<project_root>/models/` 作为唯一模型资产根；不读写 `~/.cache/huggingface` |
| U-8 | 软件自身识别该目录下已有模型（含手工放入的） | 启动时 + 按需扫描 `models/`，按必需文件与体积判定完整性，产出 manifest |
| U-9 | 一键下载、删除、查看的工作台 | `ctl.sh` 新增「模型工作台」子菜单；浏览器看板方案见 §9 |
| U-10 | 不改变既有交互习惯 | 仍是纯数字菜单、零复杂参数、零前端构建；不引入数据库 / 队列 / 鉴权中间件 |

**不变红线**：输出只有字幕文件；时间码不进 LLM；自有 OpenAI 兼容服务是唯一翻译后端；五阶段 JSONL 与 `cue.id` 稳定；`pipeline.py` 是唯一业务入口；密钥只从 `.env` / `local.yaml` 读取。

模型管理属于**控制面**，不是数据面：它的写操作只作用于 `models/`，不得触碰 `work/`、`out/`、`job.json`，也不得替代 `pipeline.run()`。

## 2. 冲突分析（这是本次变更的主要代价）

| 既有条款 | 冲突点 | 处理 |
|---|---|---|
| `09 §7`「模型权重同样放 named volume，本机项目目录因此不产生任何 Docker 运行产物」 | 与 U-7 直接相反 | **修订**：模型是用户主动下载的**资产**，不是 Docker 产物；U-6 约束的对象仍是镜像 / 容器 / 卷 / 构建缓存。compose 改为只挂载 `./models:/app/models`，镜像内依旧不含权重（`.dockerignore` 已排除 `models`） |
| `09 §4`「看板一期只读，不提供写操作」、`09 §5`「POST 留 M3」、`ADR-010` | 浏览器里做「下载 / 删除」按钮会引入写接口 | 原给出 A / B 两方案并登记 **D-16**；**2026-11-09 已结清为方案 B**（U-11 统一 Web 工作台，ADR-014/016），写接口按 `12 §11` 加回环 / CSRF / 路径护栏 |
| `09 §8`「`.gitignore` 忽略 `models/`」 | 整目录忽略会让目录说明文件也无法入库 | 改为 `models/*` + `!models/README.md`，保证目录骨架随仓库存在、权重绝不入库 |
| `configs/default.yaml` 的 `asr.model: large-v3` | 这是**模型尺寸名**，faster-whisper 会据此自动从 Hub 下载到系统缓存，正好违反 U-7 | 改为解析成本地目录路径（§10）；未安装到本地时明确报错 |
| `asr.py:get_backend()` 未装依赖时静默返回 `MockAsrBackend` | 用户以为在下/用真实模型，实际是假数据 | 借本次接线一并修复：本地模型缺失 → 明确错误或显式标注 `mock` 降级，写进 `StageResult.warnings` |
| `segment.py:get_align_backend()` 对任何配置都返回 `FallbackAligner`，但配置写着 `Qwen3-ForcedAligner-0.6B` | 看板显示值与实际后端不符 | 本次把 `align.backend` 诚实改为 `none`；真正实现强制对齐留 M2，不在本里程碑假装已支持 |

## 3. 技术核实结论（2026-11-09 查证，实施前需复核版本）

| 事实 | 来源 | 对设计的约束 |
|---|---|---|
| `WhisperModel.__init__` 含 `model_size_or_path`、`download_root`、`local_files_only`、`use_auth_token`；源码用 `os.path.isdir(model_size_or_path)` 判断，**是本地目录就直接用，不调用 `download_model`** | faster-whisper 官方 `transcribe.py` | **首选方案**：把 `models/asr/<id>/` 的绝对路径传给 `WhisperModel`，零联网、零系统缓存。不依赖任何 `HF_*` 环境变量 |
| `download_root` 实际映射到 `download_model(cache_dir=...)`，产物是 `models--<org>--<repo>/snapshots/<hash>/` 的 Hub 缓存布局 | 同上 | **不用**它做「项目内目录」：结构是缓存式嵌套目录，识别与删除都复杂，且仍受 Hub 缓存机制影响 |
| `snapshot_download(repo_id, local_dir=...)` 会按 repo 相对结构复制文件到指定目录，并在 `local_dir/.cache/huggingface/` 写元数据；文档明确说该机制「不如主缓存稳健」，且未承诺单文件断点续传 | huggingface_hub `file_download` 文档（页面标注 v2.4.0） | 下载必须先写 `models/.downloads/<id>.partial/`，完成后**原子 rename** 到目标目录，避免半成品被识别为 complete；`revision` 要 pin 到 commit hash |
| `huggingface_hub` 的 `HF_HOME` / `HF_HUB_CACHE` / `HF_HUB_OFFLINE` 等**在 import 时读取**，之后修改无效 | huggingface_hub 环境变量文档 | 不要在运行时用 `os.environ[...] = ...` 改缓存位置；采用显式本地路径方案可完全绕开此坑 |
| 本机已存在 `HF_ENDPOINT=https://hf-mirror.com`，`~/.cache/huggingface` 仅约 152 KB | 本机环境实测 | 下载源尊重用户既有镜像；项目另提供可选 `CUELOOM_HF_ENDPOINT`（须在任何 hub 库 import 之前由入口设置），不硬编码镜像地址 |
| 模型仓库体积（Hub tree API 实测）见 §5 | `https://huggingface.co/api/models/<repo>/tree/main?recursive=true` | 用于注册表 `min_bytes` 下限与看板显示预估大小；数值是 2026-11-09 快照 |

## 4. 目录布局

```
cueloom/
├── configs/
│   └── model-catalog.yaml          # 注册表（入库，M0.6 创建）
├── models/                         # U-7：唯一模型资产根，与项目在一起
│   ├── README.md                   # 例外放行、入库：说明用途与布局
│   ├── asr/
│   │   ├── faster-whisper-large-v3/    # 扁平模型目录，可直接作为 WhisperModel 路径
│   │   └── faster-whisper-small/       # 小模型，用于冒烟与 CI 之外的本地验证
│   ├── align/
│   │   └── Qwen3-ForcedAligner-0.6B/
│   ├── .downloads/                 # 下载暂存，*.partial 目录
│   ├── .trash/                     # 软删除回收区
│   └── manifest.json               # 扫描结果缓存，可再生、不入库
├── src/cueloom/models_catalog.py   # 注册表加载 + 扫描（M0.6）
├── src/cueloom/model_manager.py    # 下载 / 删除 / 校验（M0.6）
└── ctl.sh                          # 主菜单新增 10) 模型工作台（M0.6）
```

规则：

- **一个模型一个目录**，目录名 = catalog 的 `id`，与 repo 名解耦。目录内是 `snapshot_download` 复制出的 repo 相对结构（这些 repo 的文件都在根层，因此实际是扁平的）。
- `models/` 下不存系统缓存式的 `models--xxx/snapshots/...` 结构；若扫描到该结构，识别为 `legacy` 并提示迁移，不自动加载。
- `.gitignore` 用 `models/*` + `!models/README.md`，配合原有的 `*.bin` / `*.safetensors` / `*.gguf` / `*.onnx` / `*.pt` 全局忽略，双保险。
- `.dockerignore` 保持排除 `models`：镜像不含任何权重，运行时靠挂载（§11）。
- 不扫描、不读取、不清理 `~/.cache/huggingface`，也不写 `HF_HOME`。

## 5. 模型注册表 `configs/model-catalog.yaml`

字段：`id` / `kind` / `repo_id` / `revision` / `license` / `required_files` / `min_bytes` / `runtime` / `status`。

| id | kind | repo_id | license | 主要文件 | 实测体积 | runtime | 状态 |
|---|---|---|---|---|---|---|---|
| `faster-whisper-large-v3` | asr | `Systran/faster-whisper-large-v3` | MIT | `model.bin` 3087.3 MB、`config.json`、`tokenizer.json` 2.5 MB、`vocabulary.json` 1.1 MB、`preprocessor_config.json` | ≈ 3.09 GB | `asr.backend=faster-whisper` | supported（默认） |
| `faster-whisper-small` | asr | `Systran/faster-whisper-small` | MIT | `model.bin` 483.5 MB、`tokenizer.json`、`vocabulary.txt` | ≈ 0.49 GB | 同上 | supported（冒烟 / 低配） |
| `Qwen3-ForcedAligner-0.6B` | align | `Qwen/Qwen3-ForcedAligner-0.6B` | Apache-2.0 | `model.safetensors` 1835.5 MB、`config.json`、`vocab.json` 2.8 MB、`merges.txt` 等 | ≈ 1.84 GB | `align.backend=qwen3-forced-aligner` | **planned**：M2 实现适配器前不加载 |
| `silero-vad` | vad | 随 faster-whisper 提供 | MIT | 由 faster_whisper 内置资产提供 | ≈ 2 MB | `asr.vad_filter` | built-in，不单独下载 |

约定：

- `revision` 必须 pin 到 commit hash，避免分支漂移导致「同一 id 内容不一致」；hash 在首次接入时查 Hub API 写入，之后不自动更新。
- `min_bytes` 取实测体积的一个保守下限（例如 0.9×），用于完整性探针，不做逐字节 sha256（对 3 GB 文件太慢）。
- `status: planned` 的模型允许下载与查看，但**不允许设为默认后端**，避免制造「装了就能用」的错觉。
- 注册表只登记项目认可的模型；用户手工放进 `models/` 的目录不在表内时识别为 `unmanaged`（§6），不自动加载。
- 许可证列只作展示，不替代发布前的许可审计（`07` R-02）。

## 6. 识别（scan）算法

扫描范围严格限定为 `<root>/models/asr/*` 与 `<root>/models/align/*`，不递归到系统目录。

每个候选目录产出一条记录：

```json
{
  "id": "faster-whisper-large-v3",
  "kind": "asr",
  "path": "models/asr/faster-whisper-large-v3",
  "size_bytes": 3092000000,
  "state": "complete",
  "managed": true,
  "license": "MIT",
  "is_default": true,
  "issues": []
}
```

`state` 四态：

| 状态 | 判据 | 允许的操作 |
|---|---|---|
| `complete` | `required_files` 全部存在；每个 ≥ 该文件的体积下限；权重文件非 LFS pointer（小于 1 KB 且内容含 `version https://git-lfs`） | 设为默认、删除、校验 |
| `partial` | 缺文件 / 权重文件明显偏小 / 目录内有 `.incomplete` 标记 | 续下载、删除、清理 |
| `unmanaged` | 目录名不在 catalog，但含可识别权重 | 查看、删除；**不自动加载**，需人工登记 |
| `legacy` | 检出 Hub 缓存式 `models--` 或 `snapshots/` 布局 | 提示迁移，不加载 |

实现要点：

- 扫描结果写 `models/manifest.json`（原子写），同时提供 `force_rescan`；看板与菜单读同一份数据，避免两套口径。
- LFS pointer 检测是必须的：只判断「文件存在」会把未真正下载的 Git LFS 占位文件误判为完整模型。
- 路径一律 `Path.resolve()` 后校验仍位于 `<root>/models` 内，拒绝符号链接逃逸。
- 扫描只读、不联网、不加载权重，可在服务启动与菜单进入时无成本执行。

## 7. 下载（download）

```
选择模型 id
  → 校验 id 在 catalog 且 status != deprecated
  → 若目标已 complete：提示「已存在」，不覆盖
  → 在 models/.downloads/<id>.partial/ 内完成 snapshot_download
      repo_id, revision=<pinned>, local_dir=<partial>,
      allow_patterns=required_files + 小配置, max_workers=4
  → 二次校验必需文件与体积下限
  → 原子 rename 到 models/<kind>/<id>/
  → 刷新 manifest，打印 id / 体积 / 耗时 / 来源端点
```

护栏：

- **失败只清理 `.partial`**，绝不删除已有的完整模型目录。
- 进度：控制台直接看流式输出；若采用看板方案 B，则通过只读任务状态接口轮询（`§9`），不引入 WebSocket。
- 下载源：尊重 `HF_ENDPOINT`（本机已指向 `hf-mirror.com`），可选 `CUELOOM_HF_ENDPOINT` 由入口在 import 前设置；代理沿用用户既有的 7897 端口约定。
- **下载 ≠ 启用**：下载结束不改 `configs/default.yaml`，是否设为默认是菜单里的独立一步（§9）。
- 不在 CI / pytest 中下载；测试用 `<100 KB` 的假模型目录验证扫描与删除逻辑。
- `planned` 模型可以下载但显示「M2 才可用」，防止用户白等一次推理。

## 8. 删除（delete）安全护栏

模型权重可再生，但删除仍是破坏性操作，必须逐条落实：

1. **白名单**：允许的目标是 `models/asr/<id>` 或 `models/align/<id>`，且 `id` 匹配 `^[A-Za-z0-9._-]+$` 并存在于 catalog 或 manifest。
2. **路径校验**：`resolve()` 后必须是 `<root>/models` 的真子路径；拒绝 `..`、绝对路径、符号链接指向外部。
3. **先列后删**：打印完整路径、体积、是否当前默认后端，要求输入模型 id 二次确认；默认答案为否。
4. **软删除优先**：移动到 `models/.trash/<id>-<timestamp>/`，提供「清空回收站」单独入口；不提供一键 `rm -rf models/`。
5. **占用检查**：服务运行中且该模型是当前默认后端时拒绝删除，提示先停止服务或切换后端。
6. **禁止范围**：`models/README.md`、`configs/`、`work/`、`out/`、项目根、任何系统目录，一律不接受删除请求。
7. 操作结果写入控制台输出与 `manifest.json`，不写日志正文、不打印密钥。

> 说明：`models/` 属于项目工作区资产，不是桌面 / 下载 / 文稿等个人目录；即便如此仍按二次确认 + 软删除设计，因为 3 GB 权重重下成本高。

## 9. 工作台交互（历史两方案；D-16 已结清为方案 B）

> **2026-11-09 结论**：按 U-11~U-13 与 ADR-014，采用**方案 B**：模型管理在浏览器「模型」标签页完成，`GET /api/models` + 下载 / 删除 / 设为默认 / 校验写接口见 `12 §6`、`12 §10`。方案 A 的 `ctl.sh` 菜单 10 仍可在 M0.6 实现，作为无浏览器时的 CLI 兜底，两者共用同一 `model_manager` 与 manifest。以下保留两方案原文作取舍记录。

### 方案 A · 控制台操作 + 看板只读（一期推荐）

`ctl.sh` 主菜单新增 `10) 模型工作台`，子菜单纯数字：

```
 1) 查看已装模型      列出 id / 类型 / 状态 / 体积 / 许可 / 是否默认 / 路径
 2) 下载模型          列出 catalog 中未安装的，选数字即下载
 3) 删除模型          列出可删项，输入 id 二次确认，软删除到 .trash
 4) 校验完整性        对已装模型重跑 §6 判据
 5) 设为默认后端      改写 configs/local.yaml（不碰 default.yaml）
 6) 清空回收站        再次确认后永久删除 .trash 内容
 0) 返回
```

看板新增「模型」卡片，只做 `GET /api/models` 展示，无按钮、无写接口。

- 优点：`ADR-010`「看板只读」完全不破；无需 POST、无需鉴权演进；确认交互天然由菜单承担；下载进度直接可见。
- 代价：必须开终端才能下载 / 删除，「浏览器工作台」不完整。

### 方案 B · 浏览器完整工作台

在 A 之上新增写接口（仍只监听 `127.0.0.1`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/models` | 模型列表（含 manifest 状态） |
| POST | `/api/models/{id}/download` | 启动下载，返回 `task_id` |
| DELETE | `/api/models/{id}` | 软删除；请求体必须回传 id 做二次确认 |
| GET | `/api/models/tasks/{task_id}` | 下载进度、阶段、错误类别 |

- 优点：真正的一键工作台，看板与 `ctl.sh` 共用同一 `model_manager`。
- 代价：必须把 `ADR-010` 从「只读看板」放宽为「控制面局部可写」；需要任务状态表（放内存即可，不引数据库）、按钮二次确认弹层、并发下载互斥；不引账号体系，但按 ADR-016 补回环强制 / Origin-CSRF / 可选令牌（D-11 已结清，公网暴露继续禁止）。
- 硬约束：写接口只能调用 `model_manager`，**不得**触碰 `pipeline` / `job.json` / `out/`；`ADR-006` 的「服务层不写业务逻辑」精神保留。

> 两方案共用 §4~§8 的目录、注册表、扫描与护栏，差别只在入口。原建议「先交付 A，D-16 确认后再叠加 B」已被 U-11 推翻：用户要求看板与工作台合一，因此直接走 B；护栏（§8 七条）与回环约束（ADR-016）在 B 下**一条都不能省**。

## 10. 与流水线的接线

| 位置 | 现状（2026-11-09） | 本里程碑改为 |
|---|---|---|
| `configs/default.yaml` `asr.model` | `large-v3`（尺寸名 → Hub 自动下载到系统缓存） | 改为 `faster-whisper-large-v3`（catalog id）；由 `resolve_model_path()` 映射为 `<root>/models/asr/<id>` 绝对路径 |
| `asr.py:FasterWhisperBackend` | `WhisperModel(model_name, ...)` | `WhisperModel(str(local_dir), local_files_only=True, ...)`；目录不存在或状态非 `complete` → 抛明确错误，列出可用模型与菜单 10 提示 |
| `asr.py:get_backend()` | 依赖缺失静默返回 `MockAsrBackend` | 保留 mock 但必须在 `StageResult.warnings` 写 `asr_mock_fallback`；非测试模式默认改为报错 |
| `configs/default.yaml` `align.backend` | `qwen3-forced-aligner`（显示值，实际恒为 `FallbackAligner`） | 改为 `none`；`align.model` 留在 catalog 中不作为运行配置，消除「配置 ≠ 实现」 |
| `pipeline` / `job.json` | 不记录模型来源 | 记录 `asr_model_id`、`asr_model_path`、`align_backend`，保证结果可复现 |
| `cueloom doctor` / 菜单 3 | 只看服务与 LLM | 增加「已装模型 N 个，默认 ASR 模型是否就绪」，仍不加载权重 |

Mock 后端保留给 CI 与离线演示：设置 `asr.backend: mock` 才使用，不再作为隐式兜底。

## 11. Docker 部署修订（`09 §7` 的替代条款）

- `docker-compose.yml`：把 `cueloom-models:/app/models` 改为 `./models:/app/models`（只挂模型目录，不挂整个项目目录）。容器内 `/app/models` 因此就是本机同一批权重，满足 U-7。
- 镜像仍不含权重：`.dockerignore` 的 `models` 保留；`work/` / `out/` 继续用 named volume，不落本机项目目录。
- **语义澄清**：U-6 禁止的是「Docker 产物（镜像、容器、构建缓存、卷）落在本机工作区」；`models/` 是用户主动下载的资产，不属此类。但容器内执行下载会写回本机 `models/`，菜单 7 必须明确提示。
- 若用户选择「完全不挂本机」，保留 named volume 作为备选，登记为 **D-17**；两种模式不能同时启用。
- 未确认 D-12 前仍不执行 `docker build` / `compose up`。

## 12. 风险与待决

| 编号 | 风险 / 待决 | 建议 |
|---|---|---|
| R-13 | 3 GB 权重误入 git（`.gitignore` 写错或 `git add -f`） | `models/*` 忽略 + 提交前 `git status` 检查；CI 加单文件体积闸门 |
| R-14 | `snapshot_download(local_dir)` 无单文件断点续传、中断留半成品 | partial 目录 + 原子 rename；失败只清 partial；状态标 `partial` |
| R-15 | LFS pointer 被误判为完整权重，运行时报晦涩错误 | 扫描阶段做 pointer 检测 + 体积下限 |
| R-16 | 删除路径穿越 / 误删项目文件 | §8 七条护栏；测试必须覆盖 `..`、绝对路径、符号链接 |
| R-17 | 模型权重许可证与代码许可不一致 | 注册表展示 license，发布前按 `01 §3` 审计；不因下载功能放宽 |
| R-18 | 浏览器写接口在 `0.0.0.0` 下无鉴权被滥用 | 已由 `12 §11` / ADR-016 收紧：非回环 + 启用写接口即 fail-fast，另加 Origin/CSRF 与可选令牌 |
| D-15 | 模型目录是否随仓库创建占位说明 | 是，`models/README.md` 入库 |
| D-16 | 工作台采用方案 A 还是 B | **已结清（2026-11-09）：B（浏览器可写）**，见 `12 §1` / ADR-014 |
| D-17 | Docker 是 bind mount `./models` 还是继续 named volume | 建议 bind mount（U-7 优先） |
| D-18 | 是否支持用户自定义模型 / 私有 repo 与 HF token | 一期不支持；`unmanaged` 只查看与删除 |

## 13. 实施清单（M0.6，尚未开工）

1. 建 `configs/model-catalog.yaml`（§5 数据）+ `models/README.md` + `.gitignore` 调整（§4）；提交推送一次。
2. 实现 `models_catalog.py`（注册表加载、扫描、四态判定）与 `model_manager.py`（下载、软删除、校验）；单测覆盖 LFS pointer、路径穿越、partial 清理；提交推送一次。
3. `ctl.sh` 菜单 10 + `cueloom models list|download|delete|verify|use-default` 的 Python API；提交推送一次。
4. 接线 §10：`asr.py` 本地路径 + 去掉静默降级、`default.yaml` 改 `align.backend: none`、`job.json` 记录模型来源；跑通 20 项既有测试 + 新增测试；提交推送一次。
5. 浏览器「模型」标签页与写接口（D-16=B 已定），并入 `12 §14` 的 M0.7 第 4~5 步；本地冒烟后**立即关闭服务**，核验端口释放、无 Docker 产物；提交推送一次。

全程不下载 3 GB 真实模型做测试（用小型假模型目录），不启动 Docker，不改动 LLM 契约。
