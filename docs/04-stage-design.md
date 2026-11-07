# 04 · 五阶段详细设计

> 参数默认值以 `configs/default.yaml`（见 `03 §4`）为准。所有阈值都是**初始建议**，须在 M2 用 `06` 的测试集校准后才成为验收标准。

## Stage 1 · 抽取与识别

**输入**：本地音视频文件。`输出`：`01_audio.wav`（可选）、`10_asr.jsonl`。

1. **抽轨**：优先 `faster_whisper.decode_audio()`（内部 PyAV，可直接读 mp4/mkv 音轨）→ 16 kHz 单声道 float32。此路径**不需要 FFmpeg**。
   - 若后端为 Qwen3-ASR / FunASR 且不能直接读视频，才调用 FFmpeg 抽一次 wav，产物放 `work/`。
   - 对纯音频输入（wav/mp3/m4a）直接重采样，不落地 wav 也可。
2. **VAD**：Silero VAD 过滤静音与音乐段，`min_silence_duration_ms=500`、`speech_pad_ms=400`。这是抑制幻觉最有效的一步。
3. **ASR 参数**（faster-whisper）：
   ```python
   model = WhisperModel("large-v3", device="cuda", compute_type="int8_float16")
   segments, info = model.transcribe(
       audio,
       vad_filter=True,
       vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=400),
       condition_on_previous_text=False,   # 阻断幻觉跨段传播
       beam_size=5,
   )
   ```
   - `condition_on_previous_text=False` 是硬要求，不可为了「上下文更连贯」打开。
   - 单纯调低 `no_speech_threshold` 基本无效：`avg_logprob` 会一票否决跳过；`hallucination_silence_threshold` 仅 `word_timestamps=True` 时生效。
4. **幻觉黑名单**：对 ASR 结果做正则/短语过滤（如 "thanks for watching"、平台水印口播），命中即丢弃该段并记 warning。黑名单放配置，可按素材定制。
5. **语言检测**：`info.language` 写入 `10_asr.jsonl`；若与 `--from` 冲突，以 `--from` 为准并记 warning。
6. **中文后端切换**：源语言为中文 / 中文方言 / 中英混说时，可切 Qwen3-ASR 或 FunASR（见 `01 §2`）。切换只换 `AsrBackend` 实现，不影响下游。
7. **可重跑**：`cueloom resume <job> --from asr` 会重新识别；若 `01_audio.wav` 已存在则复用。

## Stage 2 · 对齐与断句（核心自写）

**输入**：`10_asr.jsonl` + 音频。`输出`：`15_words.jsonl`、`20_cues.jsonl`。

### 2.1 强制对齐

- 首选 `Qwen3-ForcedAligner-0.6B`（Apache-2.0），备选 `WhisperX`（wav2vec2 音素对齐，BSD-2-Clause）。
- 输出词级 `Word(text, start, end, confidence)`；Whisper 原生段时间戳只作为兜底，不作最终时间码。
- 对齐失败的词（低 confidence）保留 ASR 段边界插值，并打 `flags=["align_low_conf"]` 供质检。
- 中文可按字/词粒度对齐；英文按词。标点不单独占时间。

### 2.2 语义断句

采用**规则优先、LLM 可选**的两级设计，保证 M1 无 LLM 也能跑通：

1. 以词级时间戳为原子单位，先按强边界候选切分：句末标点、停顿 > 300 ms、ASR 段边界。
2. 合并过短片段（< `min_duration_sec` 0.8 s）、拆分过长片段（> `max_duration_sec` 7 s）。
3. 应用阅读速度约束：
   - 中文 `CPS = 字符数 / 时长`，目标 12–17；英文按 15–20 字符/秒（或 2.5–3.5 词/秒）另行校准。
   - 单行 ≤ 14 个汉字 / 42 个拉丁字符，最多 2 行。
   - 超限则在候选边界中找「最接近目标字符数」的位置切分，并重新按词时间计算 cue 起止。
4. **禁止切分**：数字串、日期、缩写、术语表词条、代码标识符；正则识别后作为不可分割 token。
5. **行尾不留虚词**：中文「的/了/和/在/把」、英文 "the/a/of/to" 等结尾时，切分点前移一个词。
6. `cue.id` 按时间顺序从 0 递增，写入 `20_cues.jsonl` 后**全程不变**。
7. M2 可选 `llm_assist=true`：只把候选边界附近的纯文本送给 LLM 让它选切分点，返回仍是 word index 区间，**绝不返回时间码**。

### 2.3 断句阶段的红线

- 译文长度未知，断句只依据原文；不要为了「译文更短」预留时间。
- 不许让 LLM 直接生成 SRT 文本（会引入时间码幻觉）。
- 双语字幕共用一个 cue，不生成两套时间轴。

## Stage 3 · cue 级翻译编排（核心自写）

**输入**：`20_cues.jsonl` + 术语表。`输出`：`30_translated.jsonl`（回填 `Cue.target_text`）。

1. **批次切分**：按 `batch_max_items=30` 或 `batch_max_tokens=1200` 先到者；单条超长 cue 单独成批。
2. **上下文窗口**：每批附带前后各 3 条原文（`context_before/after`），明确标注「仅供语境，不需翻译」，不计入 `items`。
3. **术语注入**：术语表随每批发送；`do_not_translate=true` 的词要求原样保留。
4. **Prompt 版本**：`prompt_version` 与 `glossary_version` 写进请求元数据与缓存 key（见 `05`）。
5. **结构化输出**：请求 `response_format` 为 JSON；若服务支持 JSON Schema 则直接传 `03 §3.2` 的 schema。
6. **回填**：按 `id` 写入 `target_text`；**不触碰 `start/end`**；回填后立刻断言时间码与 `20_cues.jsonl` 完全一致。
7. **失败处理**（按 cue 粒度）：
   - JSON 解析失败 / id 集合不匹配 / 空文本 → 整批降级为单条请求重试；
   - 仍失败 → 该 cue 指数退避重试 `max_retries=3`；
   - 耗尽 → 记 `LlmResponseError`，保留 `target_text=None`，不静默丢弃；质检阶段报 error。
8. **缓存**：单条 cue 粒度，命中直接复用，记录 `cached=true`。
9. **反思轮**（M2 才启用）：仅对长句、含数字/否定、术语未命中、低置信的 cue 触发第二轮自检；默认关闭以控成本。
10. **并发**：有界并发 `max_concurrency=4`，令牌桶限流按自有 LLM 服务的 RPM/TPM 配置；429/5xx 走退避。
11. **可重跑**：`--from translate` 只重跑未命中缓存的 cue。

## Stage 4 · 质检与回填

**输入**：`20_cues.jsonl` + `30_translated.jsonl`。`输出`：`40_qc.jsonl` + 回填后的 cue 集合。

| code | 检查 | severity | 自动修复 |
|---|---|---|---|
| `time_overlap` | 相邻 cue 时间重叠 | error | 否（回 Stage 2） |
| `time_nonmonotonic` | 时间码非递增 / 零时长 | error | 否 |
| `cue_missing` | 译文缺失或 id 集合不等 | error | 否（回 Stage 3） |
| `time_changed` | 翻译前后时间码不一致 | error | 否（架构违规，必须修 bug） |
| `cps_high` / `cps_low` | 超出 12–17 字/秒 | warn | 可尝试合并/拆分相邻 cue |
| `line_overflow` | 单行超长 / 超过 2 行 | warn | 插入换行 |
| `term_miss` | 术语表词条未按约定译出 | error | 否（人工/重翻） |
| `digit_mismatch` | 源文中数字在译文中丢失或改变 | error | 否 |
| `negation_risk` | 含否定词但译文未检出否定 | warn | 否 |
| `empty_text` | 原文或译文为空 | error | 否 |
| `lang_mismatch` | 译言语种疑似错误 | warn | 否 |
| `length_ratio` | 译文/原文长度比异常（<0.2 或 >3） | warn | 否 |
| `hallucination_suspect` | 命中幻觉黑名单 / 低 logprob | warn | 否 |

- `error` 级存在时退出码 5，但**仍写出字幕文件**并标记 `flags`，方便人工在 Subtitle Edit 里定位。
- 自动修复只做「换行、相邻 cue 合并」这类不改动时间码语义的操作，且必须在 `40_qc.jsonl` 记 `auto_fixed=true`。

## Stage 5 · 纯字幕输出

**输入**：质检后的 cue 集合。`输出`：`out/<job_id>/` 下的字幕文件。

1. 用 `pysubs2` 生成；毫秒换算由库负责，不手写时间格式化。
2. 三种产物：
   - `<base>.<src>.srt` 源语言；
   - `<base>.<tgt>.srt` 目标语言单语；
   - `<base>.<src>-<tgt>.srt` 双语，单 cue 内 `原文\n译文`（顺序由 `bilingual_order` 控制）。
3. `--format vtt|ass` 时同样三种产物；ASS 只设置最小样式（字体、字号、描边、对齐），不引入复杂特效。
4. **不烧录、不 mux、不输出视频/音频**，不调用 FFmpeg 的 `subtitles` 滤镜。
5. 输出后做一次自校验：文件可被 `pysubs2.load()` 读回，cue 数量与 `20_cues.jsonl` 一致，起止时间逐一相等。
6. 打印摘要：cue 数、总时长、error/warn 数、LLM token 用量、缓存命中率、耗时。

## 阶段级 A/B 钩子

每个 stage 支持 `--backend` 覆盖与独立产物目录，便于对同一份 `15_words.jsonl` 比较不同断句策略、对同一份 `20_cues.jsonl` 比较不同 prompt/模型，而不必重跑 ASR。实现时把「产物路径」与「stage 函数」解耦，避免把 `work/` 路径硬编码。
