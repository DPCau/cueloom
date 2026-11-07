# 05 · 自有 LLM 服务接入规范

> 前提（C-3）：用户自行提供 LLM 服务。本项目只实现一个客户端契约，不托管模型、不集成第三方翻译 API、不把本地小模型作为默认路径。

## 1. 服务契约（最低要求）

| 项 | 要求 |
|---|---|
| 接口 | OpenAI 兼容 `POST {base_url}/v1/chat/completions` |
| 鉴权 | `Authorization: Bearer $CUELOOM_LLM_API_KEY` |
| 请求 | `model`、`messages`、`temperature`、`response_format`；可选 `max_tokens` |
| 能力 | 能稳定返回**结构化 JSON**（`response_format={"type":"json_object"}`，或支持 JSON Schema 更好） |
| 超时 | 单次 ≤ `timeout_sec`（默认 60 s） |
| 并发 | 至少支持 `max_concurrency=4`；RPM/TPM 上限由用户告知后写入配置 |
| 稳定性 | 429 / 5xx 可重试；返回体的 `choices[0].message.content` 为纯 JSON 字符串 |

**若服务不支持结构化输出**：降级为「system prompt 内嵌格式约束 + 严格解析（剥离 ```json 围栏）+ Schema 校验」，并把 `llm.strict_json=false` 记入配置；**不允许**用正则从自由文本里猜译文。

## 2. 配置项

| 配置 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| `llm.base_url` | `CUELOOM_LLM_BASE_URL` | 空（必填） | 不以 `/v1/chat/completions` 结尾，客户端自行拼接 |
| `llm.api_key_env` | `CUELOOM_LLM_API_KEY` | — | 只存环境变量名，不存值 |
| `llm.model` | `CUELOOM_LLM_MODEL` | 空（必填） | 写进缓存 key |
| `llm.timeout_sec` | — | 60 | |
| `llm.max_concurrency` | — | 4 | 有界并发 |
| `llm.max_retries` | — | 3 | 按 cue 粒度 |
| `llm.qpm` / `tpm` | — | 待用户提供 | 令牌桶限流 |
| `llm.reflection` | — | false | M2 启用 |

启动时做一次轻量连通性探测（一个 2 条 cue 的最小请求），失败立即报 ConfigError，不要跑完 ASR 才失败。

## 3. Prompt 模板

### 3.1 System prompt（`configs/prompts/translate.system.md`，`prompt_version=v1`）

```
你是专业影视字幕翻译。把 items 中每条源语言字幕译成目标语言。

硬性要求：
1. 只输出 JSON：{"items":[{"id":<整数>,"text":"<译文>"}]}，不要解释、不要 Markdown 围栏。
2. id 必须与输入完全一致，条数相同，不增不删不改序，不翻译 id。
3. 每条译文对应一条字幕：口语化、简洁、适合屏幕阅读，不要扩写、不要加注释。
4. 术语表中的词条必须按给定译法；do_not_translate 为 true 的词原样保留。
5. 数字、单位、专有名词、代码标识符、否定含义必须准确保留。
6. 保留原文语气与称呼，不要把疑问句改成陈述句。
7. context_before / context_after 只用于理解语境，不要翻译它们，也不要输出它们。
8. 不要输出任何时间码或时间信息。
```

### 3.2 User payload

见 `03 §3.1`。用 `json.dumps(..., ensure_ascii=False)`，避免中文被转义成 `\uXXXX` 浪费 token。

### 3.3 反思轮 prompt（M2，`reflect.system.md`）

```
检查下列原文/译文对，只在发现术语不一致、数字错误、否定丢失、明显漏译时给出修订。
输出 JSON：{"items":[{"id":<整数>,"text":"<修订后译文>"}]}；无需修订的条目也要原样输出。
不要改写风格，不要扩写，不要输出时间码。
```

## 4. 响应校验流水线

```
HTTP 200
  → 取 content
  → json.loads（失败：剥围栏再试一次；仍失败 → 按 cue 拆分重试）
  → JSON Schema 校验（additionalProperties=false）
  → id 集合与请求完全一致、无重复
  → text 非空、非纯标点
  → 长度比检查（译文/原文字符数，中文按 <0.2 或 >3 告警）
  → 数字集合比对（源文中的数字应出现在译文中）
  → 术语命中检查
  → 语种抽检（可选，仅对 warn）
  → 回填 Cue.target_text
```

任一硬失败按以下顺序降级，不许静默跳过：
`整批重试` → `拆成单条请求` → `指数退避重试 3 次` → `标记 cue 失败，质检报 error`。

## 5. 重试与幂等

- 退避：`1s / 2s / 4s` + 抖动；429 尊重 `Retry-After`。
- 请求幂等：同一 `(prompt_version, glossary_version, cue.text)` 重复请求结果只写一次，后写不覆盖已成功的 `target_text`。
- `temperature=0`（或用户服务允许的最小值），保证可复现。
- 单 cue 失败不影响整批其他 cue 的回填。

## 6. 缓存

- 粒度：单条 cue（不是整批）。
- key：`sha256(model|prompt_version|glossary_version|src_lang|tgt_lang|cue.text)`，见 `03 §3.3`。
- 存储：M1 用 `work/<job_id>/llm_cache/*.json`；跨 job 复用可放 `work/cache/`（需显式开启）。
- 记录字段：`text`、`model`、`tokens`、`created_at`；不记录 API key 与完整请求。
- 指标：命中率写进运行摘要；命中率是成本控制的核心观测项。

## 7. 成本与用量

- 每批记录 `usage.prompt_tokens / completion_tokens`（若服务不返回，按字符数估算并标注 `estimated=true`）。
- 单次运行摘要输出：总 token、缓存节省的 token、平均每条 cue token、总耗时。
- 估算公式（用于预算，非计费）：`总输入 ≈ Σ(批次 system + payload) + Σ(未命中缓存的 cue)`；反思轮按受影响 cue 数另计。
- 成本控制开关：关闭反思轮、增大批次、提高缓存复用、对低风险 cue 跳过二次校验。

## 8. 降级路径

| 故障 | 降级 |
|---|---|
| LLM 服务不可达 | 明确失败（退出码 4），**不回退到第三方翻译 API**；保留全部阶段产物，支持 `--from translate` 续跑 |
| 结构化输出不稳 | `strict_json=false` + 严格解析兜底，记录 warn |
| 服务限流 | 降并发至 1、拉长退避 |
| 部分 cue 失败 | 保留源语字幕与已成功译文，双语文件中缺失处标记 `flags`，质检报 error |
| 用户要求零成本 | 允许把 `base_url` 指向自建 Ollama / vLLM（仍是同一个契约），不改代码 |

## 9. 安全与隐私

- 请求体只含 `id` 与字幕文本、术语表、语言标签；**不含时间码、文件名、路径、音频、用户标识**。
- 日志不打印完整字幕正文与 API key；DEBUG 只打 cue.id、字符数、token 数。
- `configs/local.yaml` 与 `.env` 已 gitignore；密钥不写进文档、代码、JSONL、缓存。
- 若素材敏感，可在配置中启用 `llm.redact=true` 对术语表中的人名做占位替换（M2 可选）。

## 10. 质量评测接口

- 人工抽样：每批随机 10 条，按「准确性 / 术语 / 简洁度 / 口语化」4 项 1–5 分打分，记录到 `06` 的评测表。
- 可选自动指标：COMET / LLM-as-judge（用同一服务或另一模型），仅作趋势参考，**不替代人工**。
- 每次改 prompt / 模型 / 术语表都要跑一次固定测试集回归，并在 `06` 记录版本号与结果。
