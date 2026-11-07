# 02 · 架构设计

## 1. 架构原则

| 编号 | 原则 | 落地方式 |
|---|---|---|
| P-1 | 薄编排层 | 只自写「断句 / 翻译编排 / 质检回填」；ASR、对齐、字幕格式、正则全部复用成熟库 |
| P-2 | 时间码不进 LLM | LLM 只接收 `{id, text}`，按 id 回填；双语 = 同一 cue 两行 |
| P-3 | 阶段落盘 | 每阶段输出 JSONL，支持断点续跑、单阶段重跑、A/B 对比与问题复现 |
| P-4 | cue.id 稳定 | 从断句阶段生成后全程不变，作为回填、缓存、质检的主键 |
| P-5 | CLI 优先 | `pipeline.py` 与传输层解耦；FastAPI 只包一层，不把业务逻辑写进路由 |
| P-6 | 依赖最小化 | 优先 faster-whisper + PyAV 路径，力争**运行期零 FFmpeg 依赖**；GUI / 队列 / 多租户一律不进一期 |
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
    cli.py                    # typer / argparse CLI
    server.py                 # M3 才实现：FastAPI 薄封装
  tests/
    fixtures/                 # 代表性音频 + 金标准 SRT（体积大的用 LFS/外链）
    unit/  integration/
  work/                       # 中间产物（gitignore）
  out/                        # 最终字幕（gitignore）
  models/                     # 模型权重（gitignore）
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
| M3 | `fastapi` / `uvicorn` | 服务化 | 一期不装 |
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
- M2/M3：FastAPI 只做 `POST /jobs` + `GET /jobs/{id}`，内部复用同一 `pipeline.run(job)`；不引入 Celery/Redis，除非出现真实并发压力（ADR-006）。
- 所有 I/O（模型加载、LLM 请求、文件写）都在显式函数中，便于 mock 测试。

## 8. 配置分层

优先级：CLI 参数 > 环境变量（`CUELOOM_*`）> `configs/local.yaml` > `configs/default.yaml` > 代码默认值。
密钥只允许来自环境变量或 `local.yaml`，禁止写进 `default.yaml` 与文档。示例见 `03`。

## 9. 明确不做的架构件

不引入插件系统、不引入工作流引擎、不引入数据库、不引入对象存储、不引入消息队列、不引入前端。
若未来要支持「已有 SRT 文件直接翻译」，应作为 `--input-srt` 的旁路入口，跳过 Stage 1/2，而不是改造成通用工作流。
