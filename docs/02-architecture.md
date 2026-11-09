# 02 · 架构设计

## 1. 架构原则

| 编号 | 原则 | 落地方式 |
|---|---|---|
| P-1 | 薄编排层 | 只自写「断句 / 翻译编排 / 质检回填」；ASR、对齐、字幕格式、正则全部复用成熟库 |
| P-2 | 时间码不进 LLM | LLM 只接收 `{id, text}`，按 id 回填；双语 = 同一 cue 两行 |
| P-3 | 阶段落盘 | 每阶段输出 JSONL，支持断点续跑、单阶段重跑、A/B 对比与问题复现 |
| P-4 | cue.id 稳定 | 从断句阶段生成后全程不变，作为回填、缓存、质检的主键 |
| P-5 | 数据面与传输层解耦（2026-11-09 修订） | `pipeline.py` 不感知 HTTP / 菜单；服务层只做校验与序列化，写操作经 `control/` 命令层；浏览器工作台是默认操作面，CLI / Python API 仍可独立跑完整流程（ADR-014） |
| P-6 | 依赖最小化 | 优先 faster-whisper + PyAV 路径，力争**运行期零 FFmpeg 依赖**；前端框架 / 构建工具 / 队列 / 多租户一律不进一期。Web 工作台用 FastAPI 自带 `StaticFiles` 与原始流式 PUT，不新增 `python-multipart` 等依赖 |
| P-7 | 可替换后端 | ASR、对齐、LLM、字幕输出均定义 Protocol，配置切换，不写死厂商 |

## 2. 五阶段数据流

```mermaid
flowchart TD
    A[输入: 本地视频/音频] --> S1[01 抽取与识别<br/>PyAV 抽 16k 单声道<br/>VAD + faster-whisper / Qwen3-ASR]
    S1 -->|10_asr.jsonl| S2[02 对齐与断句<br/>强制对齐 → word[]<br/>语义分行 + CPS 约束]
    S2 -->|20_cues.jsonl| S3[03 cue 级翻译编排<br/>批量 + 术语表 + JSON Schema<br/>重试 / 缓存 / 反思轮]
    S3 <-->|仅 id + text| LLM[[你的 LLM 服务<br/>OpenAI 兼容端点]]
    S3 -->|30_translated.jsonl| S4[04 质检与回填<br/>时间码单调 / CPS / 术语<br/>数字 / cue 覆盖率]
    S4 -->|40_qc.jsonl| S5[05 纯字幕输出<br/>pysubs2 → SRT / VTT / ASS]
    S5 --> O[输出: 字幕文件<br/>out/&lt;job_id&gt;/*.srt]
```

标注「复用 / 自写」的边界：

| 阶段 | 自写 | 复用 |
|---|---|---|
| 01 抽取与识别 | 后端适配层、参数与幻觉抑制策略 | PyAV、faster-whisper / Qwen3-ASR、Silero VAD |
| 02 对齐与断句 | **cue 切分算法、CPS/行宽规则、cue.id 生成** | Qwen3-ForcedAligner / WhisperX |
| 03 翻译编排 | **批次切分、上下文窗口、术语注入、Schema 校验、重试、缓存、反思轮** | LLM HTTP 客户端（OpenAI SDK 或 httpx） |
| 04 质检回填 | **全部规则与自动修复策略** | 正则 / 语言检测库 |
| 05 输出 | 文件名与产物布局 | pysubs2 |

## 3. 目录结构（M1 目标形态）

```
cueloom/
  README.md
  .gitignore
  pyproject.toml              # uv 管理，Python 3.11+，CLI 入口 cueloom
  docs/                       # 本套文档
  configs/
    default.yaml              # 默认配置（可提交）
    prompts/
      translate.system.md     # 翻译 system prompt（带版本号）
      reflect.system.md       # 反思轮 system prompt
    glossary.example.yaml     # 术语表样例
    local.yaml                # 本地覆盖 + 密钥（gitignore）
  src/cueloom/
    __init__.py
    models.py                 # Word / Cue / Glossary / Job / StageResult / QcIssue
    config.py                 # 配置加载与校验（pydantic-settings 或 PyYAML）
    pipeline.py               # 五阶段编排 + 断点续跑 + 状态机
    stages/
      asr.py                  # Stage 1
      segment.py              # Stage 2（对齐 + 断句）
      translate.py            # Stage 3
      qc.py                   # Stage 4
      emit.py                 # Stage 5
    llm/
      client.py               # OpenAI 兼容客户端
      schema.py               # 请求/响应 JSON Schema
      cache.py                # 版本化缓存
      retry.py                # 按 cue 粒度重试与退避
    io/
      jsonl.py                # 阶段产物读写
      subtitle.py             # pysubs2 封装
    cli.py                    # typer / argparse CLI（兜底与自动化）
    server.py                 # FastAPI 路由层：校验 / 序列化，不含业务逻辑
    control/                  # 命令层（M0.7）：guards / config_service / job_service / model_service / llm_service / task_registry / audit
    web/
      index.html  app.js  style.css   # 零构建 Web 工作台（M0.7）
  inbox/                      # 浏览器上传素材（gitignore）
  tests/
    fixtures/                 # 代表性音频 + 金标准 SRT（体积大的用 LFS/外链）
    unit/  integration/
  work/                       # 中间产物（gitignore）
  out/                        # 最终字幕（gitignore）
  models/                     # 模型资产根（项目内，gitignore）；布局与工作台见 10
  .agents/blackboard.md       # 协同黑板（gitignore）
```

## 4. 依赖清单（建议，版本号在 M1 `uv add` 时确定）

| 类别 | 包 | 用途 | 备注 |
|---|---|---|---|
| 核心 | `faster-whisper` | ASR + 内置 PyAV 音频解码 | 免 FFmpeg 的关键 |
| 核心 | `pysubs2` | SRT/VTT/ASS 读写 | |
| 核心 | `pydantic` | 数据模型与 Schema 校验 | v2 |
| 核心 | `PyYAML` | 配置 | |
| 核心 | `typer` 或 `argparse` | CLI | 尽量少依赖，argparse 亦可 |
| LLM | `openai` 或 `httpx` | OpenAI 兼容端点 | 若服务不支持官方 SDK 特性，用 httpx 更可控 |
| 可选 | `qwen-asr` / `funasr` / `transformers` | 中文 ASR 后端 | 按需 extras，避免默认安装重型 torch 栈 |
| 可选 | `whisperx` | 对齐备选后端 | 依赖复杂，放 extras |
| 可选 | `langdetect` / `fasttext` | 语言检测、译文语种校验 | |
| 核心（由 M3 提前，见 §10） | `fastapi` / `uvicorn` | 服务层与零构建 Web 工作台 | 框架阶段即装；静态托管与 `FileResponse` 用 Starlette 自带能力 |
| 核心 | `python-dotenv` | 读 `.env` | 不引 pydantic-settings，保持轻量；工作台写 `.env` 用自写逐行 upsert（ADR-015） |
| 核心（M0.7 工作台） | **无新增第三方包** | 上传用 `request.stream()` + 原始 PUT，静态文件用 `StaticFiles` | 刻意不引 `python-multipart` / 前端构建依赖 |
| 模型工作台（M0.6 设计，未装） | `huggingface_hub` | 从 Hub 下载模型快照到项目内 `models/` | 仅下载时需要；流水线加载本地目录不依赖它，见 `10 §3` |
| 开发 | `pytest` / `ruff` | 测试与静态检查 | |

**依赖红线**：不引入 Streamlit / Gradio / PySide / yt-dlp / TTS 相关包 / FFmpeg 二进制依赖。

## 5. Job 状态机

```
created → extracting → asr_done → aligned → segmented → translated → qc_done → emitted → done
                                                                                    ↘ failed
任意阶段失败 → failed（保留全部已落盘阶段产物，可从失败阶段重跑）
```

- `job_id`：时间戳 + 输入文件名 hash 的前 8 位，保证同一输入重跑可复用缓存。
- 状态写入 `work/<job_id>/job.json`，每阶段完成即原子更新。
- 重跑命令：`cueloom resume <job_id> --from translate`，只重跑指定阶段及其后续。
- 重跑前置校验：上游阶段 JSONL 存在且 schema 通过校验。

## 6. 产物布局

```
work/<job_id>/
  job.json                  # Job 元数据与状态
  01_audio.wav              # 抽取的 16k 单声道（可再生）
  10_asr.jsonl              # 每段 ASR 结果（含语言、VAD 区间）
  15_words.jsonl            # 强制对齐后的词级时间戳
  20_cues.jsonl             # 断句后的 cue（含 id、start、end、text、words 区间）
  30_translated.jsonl       # 译文（id → text + 元数据）
  35_reflect.jsonl          # 反思轮修订（若启用）
  40_qc.jsonl               # 质检问题清单
  llm_cache/                # 版本化缓存（可选落盘）
out/<job_id>/
  <basename>.<src>.srt      # 源语言字幕
  <basename>.<tgt>.srt      # 目标语言单语字幕
  <basename>.<src>-<tgt>.srt # 双语字幕（同一 cue 两行）
```

## 7. 传输层与并发模型

- M1：单进程 CLI，LLM 调用使用有界并发（默认 4，可配 `--llm-concurrency`），ASR 单任务。
- M0.7 起（2026-11-09 修订）：FastAPI 提供读写接口，`POST /api/jobs` 在后台线程复用 `pipeline.run(job, cfg_snapshot)`，**单飞**（同时只跑一个任务）；进度从 `work/<job_id>/job.json` 轮询，产物用 `FileResponse` 下载；不引入 Celery/Redis/数据库（ADR-006/014）。多任务排队留 D-24。
- 所有 I/O（模型加载、LLM 请求、文件写）都在显式函数中，便于 mock 测试。

## 8. 配置分层

优先级：CLI 参数 > 环境变量（`CUELOOM_*`）> `configs/local.yaml` > `configs/default.yaml` > 代码默认值。
密钥只允许来自环境变量或 `local.yaml`，禁止写进 `default.yaml` 与文档。示例见 `03`。

## 9. 明确不做的架构件

不引入插件系统、不引入工作流引擎、不引入数据库、不引入对象存储、不引入消息队列；**不引入前端框架、构建工具、CDN 与账号体系**（2026-11-09 精确化：允许 FastAPI 托管的零构建原生静态工作台，见 `12 §5`）。
若未来要支持「已有 SRT 文件直接翻译」，应作为 `--input-srt` 的旁路入口，跳过 Stage 1/2，而不是改造成通用工作流。

## 10. 控制面、看板与部署（2026-11-08 增补，见 `09`）

用户追加 U-1 ~ U-6 后，架构在**不改变数据面**的前提下增加控制面与观测面：

| 层 | 新增组件 | 与既有架构的关系 |
|---|---|---|
| 生命周期层 | `ctl.sh` 交互式菜单（2026-11-09 修订） | 只管进程 / 部署 / 环境初始化与 CLI 兜底；不再是默认业务操作面（ADR-014） |
| 交互 / 服务层 | `web/*` + `server.py` + `control/` | 零构建 Web 工作台读写一体；命令层承接配置 / job / 模型 / LLM 写操作；不引数据库 / 队列 / 前端构建（ADR-014/015/016） |
| 配置面 | `.env.example` / `.env` / `configs/default.yaml` / `configs/local.yaml` | 沿用 §8 配置分层；`default.yaml` 只读，工作台写 `.env` 与 `local.yaml`，密钥仅本机存在 |
| 部署面 | `Dockerfile` / `docker-compose.yml` / `.dockerignore` | named volume 承载 work/out/models，不 bind mount 项目目录 |

增量目录（其余见 §3）：

```
cueloom/
  ctl.sh                      # U-1 服务生命周期入口（M0.7 起兼 CLI 兜底）
  .env.example                # U-3 模板，可提交
  .env                        # 本地密钥，gitignore
  Dockerfile  docker-compose.yml  .dockerignore
  configs/
    default.yaml
    prompts/translate.system.md
    prompts/reflect.system.md
    glossary.example.yaml
  src/cueloom/
    server.py                 # /api/* 路由层（M0.5 只读；M0.7 起读写）
    control/                  # M0.7 命令层（ADR-014/015/016）
    web/index.html            # U-2 零构建页面；M0.7 起拆 3 个静态文件、6 个标签页
  inbox/                      # M0.7 浏览器上传素材（gitignore）
  work/ctl/                   # server.pid / server.log / audit.log / web.token（gitignore）
```

> **2026-11-09 修订（U-11~U-13）**：上表的「观测面只读」已被 `12 §4` 取代；四层改为生命周期层 / 交互与服务层 / 命令层 / 数据面。完整写接口、配置热更新与安全边界见 `12`。

依赖调整：`fastapi` / `uvicorn` 从「M3 才装」提前到核心（服务框架需要），`python-dotenv` 用于读 `.env`；ASR 重型依赖仍放 extras，默认安装保持轻量。ADR-006 的「CLI 优先、FastAPI 只薄封装」精神保留，仅时间点提前。
