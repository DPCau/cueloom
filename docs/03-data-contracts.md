# 03 · 数据契约与接口

> 本文件是实现的直接依据。字段名、类型、文件路径、CLI 参数在 M1 内保持稳定；变更需追加 ADR 并同步更新本文件。
> 所有代码/配置示例使用 ASCII 直引号。

## 1. 核心数据模型（Pydantic v2 风格）

```python
from pydantic import BaseModel, Field
from typing import Literal

class AsrSegment(BaseModel):
    seg: int
    start: float
    end: float
    text: str
    lang: str
    avg_logprob: float = 0.0

class Word(BaseModel):
    text: str
    start: float                 # 秒，保留 3 位小数
    end: float
    confidence: float = 1.0

class Cue(BaseModel):
    id: int                      # 从 0 开始，断句阶段生成后全程不变
    start: float
    end: float
    text: str                    # 源语言文本，不含时间码
    words: list[Word] = []       # 该 cue 覆盖的词（调试与断句用）
    target_text: str | None = None   # 译文，Stage 3 回填
    flags: list[str] = []        # 质检标记，如 "cps_high" / "term_miss"

class GlossaryEntry(BaseModel):
    src: str
    tgt: str
    case_sensitive: bool = False
    do_not_translate: bool = False   # 品牌名/代码保持原样

class Job(BaseModel):
    job_id: str
    input_path: str
    source_lang: str | None = None   # None = 自动检测
    target_lang: str
    bilingual: bool = True
    formats: list[Literal["srt", "vtt", "ass"]] = ["srt"]
    prompt_version: str = "v1"
    glossary_version: str = "v1"
    status: str = "created"
    stage: str | None = None
    created_at: str = ""

class StageResult(BaseModel):
    stage: str
    ok: bool
    count: int = 0
    duration_sec: float = 0.0
    warnings: list[str] = []

class QcIssue(BaseModel):
    cue_id: int
    code: str                    # 见 04 §4 规则表
    severity: Literal["info", "warn", "error"]
    detail: str
    auto_fixed: bool = False
```

铁律：
- `Cue.start/end` 只允许 Stage 2 写入；Stage 3/4 **禁止修改**（M1 用断言校验翻译前后时间码完全一致）。
- `Cue.id` 是回填、缓存、质检的唯一主键，不得重排。
- 时间统一为秒（float）；写 SRT 时才转成 `HH:MM:SS,mmm`。

## 2. JSONL 阶段产物 schema

每行为一个 JSON 对象，UTF-8，不带 BOM，键顺序固定便于 diff。以下是各文件的**单行样例**（实际文件不含注释、不含文件名行）：

`10_asr.jsonl`

```json
{"seg": 0, "start": 0.32, "end": 3.88, "text": "Welcome back to the channel", "lang": "en", "avg_logprob": -0.21}
```

`15_words.jsonl`

```json
{"seg": 0, "text": "Welcome", "start": 0.32, "end": 0.71, "confidence": 0.98}
```

`20_cues.jsonl`（`words` 为 `Word` 对象数组，与 `Cue.words` 一致）

```json
{"id": 0, "start": 0.32, "end": 3.88, "text": "Welcome back to the channel", "words": [{"text": "Welcome", "start": 0.32, "end": 0.71, "confidence": 0.98}], "flags": []}
```

`30_translated.jsonl`

```json
{"id": 0, "text": "欢迎回到本频道", "model": "my-llm", "prompt_version": "v1", "glossary_version": "v1", "cached": false, "tokens": 86}
```

`40_qc.jsonl`

```json
{"cue_id": 0, "code": "cps_high", "severity": "warn", "detail": "19.2 cps > 17", "auto_fixed": false}
```

`job.json` 为单个 JSON 对象（非 JSONL），包含 Job 模型全部字段与各 StageResult 列表。

## 3. LLM 请求 / 响应契约

### 3.1 请求 user payload

```json
{
  "task": "subtitle_translation",
  "source_lang": "en",
  "target_lang": "zh-CN",
  "context_before": ["上一批最后 3 条原文，仅供理解语境，不需翻译"],
  "context_after": ["下一批最前 3 条原文，仅供理解语境，不需翻译"],
  "glossary": [{"src": "Agent", "tgt": "智能体"}, {"src": "MCP", "tgt": "MCP", "do_not_translate": true}],
  "items": [{"id": 0, "text": "Welcome back to the channel"}, {"id": 1, "text": "Today we build an agent"}]
}
```

约束：
- **绝不发送 `start` / `end` / 时间码 / 音频 / 视频元数据**。
- `items` 建议 20–40 条或累计约 1200 token，取先到者；超长 cue 单独成批。
- `context_before/after` 各 3 条，仅作语境，`items` 中不包含它们。

### 3.2 响应 JSON Schema（严格校验）

```json
{
  "type": "object",
  "required": ["items"],
  "additionalProperties": false,
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "text"],
        "additionalProperties": false,
        "properties": {
          "id": {"type": "integer"},
          "text": {"type": "string", "minLength": 1}
        }
      }
    }
  }
}
```

校验流程：解析 JSON → Schema 校验 → `set(返回 id) == set(请求 id)` 且无重复 → 文本非空 → 译文长度比异常检查 → 语种抽检 → 术语命中检查。任一失败按 `04 §3` 重试。

### 3.3 缓存 key

```
key = sha256(model + "|" + prompt_version + "|" + glossary_version
             + "|" + source_lang + "|" + target_lang + "|" + cue.text)
```

缓存粒度为**单条 cue**，不是整批：批次边界变化也能命中。改 prompt / 术语表 / 模型即自动失效。

## 4. 配置示例 `configs/default.yaml`

```yaml
asr:
  backend: faster-whisper       # faster-whisper | qwen3-asr | funasr
  model: large-v3
  device: auto                  # auto | cuda | cpu
  compute_type: int8_float16
  vad_filter: true
  vad_min_silence_ms: 500
  vad_speech_pad_ms: 400
  condition_on_previous_text: false
  hallucination_blacklist: ["thanks for watching", "subscribe", "字幕由"]
align:
  backend: qwen3-forced-aligner # qwen3-forced-aligner | whisperx | none
  model: Qwen3-ForcedAligner-0.6B
segment:
  max_cps: 17                   # 中文 characters per second
  min_cps: 12
  max_chars_per_line: 14
  max_lines: 2
  min_duration_sec: 0.8
  max_duration_sec: 7.0
  llm_assist: false             # M1 用规则断句；M2 可选 LLM 辅助
llm:
  base_url: ""                  # 必填，建议由 CUELOOM_LLM_BASE_URL 提供
  model: ""
  api_key_env: CUELOOM_LLM_API_KEY
  timeout_sec: 60
  max_concurrency: 4
  max_retries: 3
  batch_max_items: 30
  batch_max_tokens: 1200
  context_window: 3
  reflection: false             # M2 再启用
  cache: true
output:
  formats: [srt]
  bilingual: true
  bilingual_order: source_first  # source_first | target_first
  max_cps_enforce: true
```

环境变量：`CUELOOM_LLM_BASE_URL`、`CUELOOM_LLM_API_KEY`、`CUELOOM_LLM_MODEL`、`CUELOOM_LOG_LEVEL`。

## 5. CLI 契约

```
cueloom run INPUT --to LANG [--from LANG] [--bilingual/--no-bilingual]
                  [--format srt|vtt|ass ...] [--out DIR]
                  [--glossary PATH] [--config PATH]
                  [--asr-backend NAME] [--llm-concurrency N]
                  [--verbose]
cueloom resume JOB_ID --from STAGE
cueloom qc JOB_ID                 # 只重跑质检
cueloom validate FILE            # 校验 JSONL / SRT schema
cueloom version
```

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `INPUT` | 是 | — | 本地音视频路径；M1 不接 URL |
| `--to` | 是 | — | 目标语言，ISO 639-1 或 `zh-CN` 形式 |
| `--from` | 否 | 自动检测 | 源语言 |
| `--bilingual` | 否 | true | 同一 cue 两行；`--no-bilingual` 只出译文 |
| `--format` | 否 | `srt` | 可重复指定多个 |
| `--out` | 否 | `out/` | 最终字幕目录 |
| `--glossary` | 否 | `configs/glossary.yaml` | 术语表 |
| `--from STAGE`（resume） | 是 | — | `asr / segment / translate / qc / emit` |

退出码：`0` 成功；`2` 参数或配置错误；`3` 上游阶段产物缺失/损坏；`4` LLM 不可用或重试耗尽；`5` 质检存在 error 级问题；`1` 其他未预期异常。

## 6. Python 接口签名（M1 建议）

```python
# stages/asr.py
def run(job: Job, cfg: Config) -> StageResult: ...
def transcribe(path: Path, cfg: Config) -> tuple[str, list[AsrSegment]]: ...

# stages/segment.py
def align(words_or_segments, audio: Path, cfg: Config) -> list[Word]: ...
def split_cues(words: list[Word], cfg: Config) -> list[Cue]: ...

# stages/translate.py
def translate_cues(cues: list[Cue], glossary: list[GlossaryEntry], cfg: Config) -> list[Cue]: ...
def build_batches(cues, cfg) -> list[Batch]: ...

# stages/qc.py
def check(cues: list[Cue], cfg: Config) -> list[QcIssue]: ...
def auto_fix(cues: list[Cue], issues: list[QcIssue]) -> list[Cue]: ...

# stages/emit.py
def emit(cues: list[Cue], job: Job, cfg: Config) -> list[Path]: ...

# pipeline.py
def run(job: Job, cfg: Config, from_stage: str | None = None) -> Job: ...
```

后端适配用 `typing.Protocol` 定义，配置切换实现：

```python
class AsrBackend(Protocol):
    def transcribe(self, audio: Path, cfg: Config) -> list[AsrSegment]: ...
class LlmClient(Protocol):
    def complete_json(self, system: str, payload: dict, schema: dict) -> dict: ...
```

## 7. 异常分类

| 类别 | 例子 | 处理 |
|---|---|---|
| ConfigError | 缺 `--to`、LLM base_url 为空 | 立即失败，退出码 2 |
| DependencyError | 模型未下载、权重 hash 不符 | 提示下载命令，退出码 3 |
| StageMissingError | resume 时上游 JSONL 缺失 | 退出码 3 |
| LlmResponseError | JSON 解析失败 / id 集合不匹配 | 按 cue 拆分重试，耗尽后退出码 4 |
| QcError | 时间码重叠、丢句、数字不一致 | 退出码 5，保留全部产物供排查 |
| TransientError | 网络超时、429 | 指数退避重试 |

日志与异常中禁止出现 API key、完整字幕正文（可打 cue.id 与长度）。
