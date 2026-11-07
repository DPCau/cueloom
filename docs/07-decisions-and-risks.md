# 07 · 决策记录（ADR）、命名核验与风险

## 1. ADR 索引

状态：`Accepted` 已定 / `Proposed` 建议待确认 / `Superseded` 被替代。变更决策时追加新 ADR，把旧条目标为 Superseded，不直接改写历史结论。

### ADR-001 · 自建薄编排层，而非整套部署开源 GUI 项目 — Accepted（2026-11-08）

- 背景：C-1 不配音、C-2 不烧录、C-3 自有 LLM。现成项目 60–80% 功能与依赖（TTS、yt-dlp、Streamlit、FFmpeg 烧录、全局 config）用不上；其 LLM 客户端是单任务同步调用，无法做并发/限流/按 cue 重试/缓存/成本归因。
- 决定：复用开源库（ASR、对齐、字幕格式）+ 自写约 1500–2500 行编排层；自写范围限定为断句、翻译编排、质检回填。
- 后果：换来可控性与可测试性；代价是要自己实现语义断句，并用 VideoLingo 作质量基线防退化。
- 推翻条件：若只是偶尔翻几段视频、不做服务化与二次集成，改用路线 A。

### ADR-002 · 范围严格限定为「只出字幕文件」 — Accepted（2026-11-08）

- 决定：不实现 TTS、配音、烧录、mux、yt-dlp、GUI、OCR、说话人分离、多租户。
- 后果：可去掉 FFmpeg 运行期依赖（faster-whisper + PyAV 路径）、去掉 CUDA/cuDNN 的部分约束、产物是纯文本便于 diff 与版本管理。

### ADR-003 · 时间码永不交给 LLM — Accepted（2026-11-08）

- 决定：LLM 只处理 `{id, text}`；`start/end` 仅由 Stage 2 写入；双语 = 同一 cue 两行。
- 后果：彻底消除 LLM 篡改时间码、生成伪 SRT 的风险；省 token；翻译前后时间码可做硬断言（见 `06`）。

### ADR-004 · 每阶段 JSONL 落盘 + cue.id 稳定 — Accepted（2026-11-08）

- 决定：五阶段产物落盘，支持 resume、单阶段 A/B、问题复现；cue.id 作为回填/缓存/质检主键。
- 后果：磁盘 I/O 与产物管理变复杂，但换来可调试性；这是自建相对 GUI 工具的核心收益之一。

### ADR-005 · ASR 双后端可切换，默认 faster-whisper — Accepted（2026-11-08，默认值待实测校准）

- 决定：`AsrBackend` Protocol；默认 faster-whisper（通用多语、内置 PyAV 解码），中文/方言场景可切 Qwen3-ASR 或 FunASR。对齐首选 Qwen3-ForcedAligner，备选 WhisperX。
- 后果：重型依赖放 extras，默认安装轻；需要在 T1/T2 测试集上实测后固定推荐默认值（见 D-02）。

### ADR-006 · CLI 优先，FastAPI 仅薄封装 — Accepted（2026-11-08）

- 决定：M1/M2 只做 CLI + Python API；M3 才加 FastAPI，且路由只调用 `pipeline.run(job)`。
- 后果：避免过早引入队列、数据库、鉴权；服务化成本后置但很低。

### ADR-007 · 项目命名 CueLoom — Proposed（待用户最终确认）

- 决定：仓库 / PyPI 包 / CLI / 镜像统一用 `cueloom`；中文副名可选「织幕」或「行间」。
- 依据：见 §2 命名核验；`cue` 是字幕标准术语，`loom` 表示原文/译文/时间轴交织，且不含 video/dub/voice/burn 等误导词、不绑定 SRT 单一格式。
- 后果：名字尚未被占用，但需尽快确认并注册；若用户改名，需全仓批量替换并更新本文档。

### ADR-008 · 开源许可证建议 Apache-2.0 — Proposed（待确认，D-01）

- 背景：项目会参考 Apache-2.0 的 VideoLingo / Qwen3-ASR 生态，但不复制其代码；若未来考虑商用集成，宽松许可更合适。
- 决定建议：Apache-2.0；若用户更看重极简，可用 MIT。GPL 不选（与自建目的冲突）。
- 后果：确认前**不要创建 LICENSE 文件**，也不要在 README 声称许可。

## 2. 命名核验数据（2026-11-08 实测）

核验方式：PyPI `https://pypi.org/pypi/<name>/json`（404 = 包名可用）；GitHub Search API `q=<name> in:name`（同名仓库数，近似值）。数据为当时的快照。

| 候选 | 含义 | PyPI | GitHub 同名 | 结论 |
|---|---|---|---|---|
| **cueloom** | cue + 织机 | 404 可用 | **0** | **首推** |
| cuesmith | 字幕匠人 | 404 可用 | 2 | 备选 |
| captionwright | Playwright 式构词 | 404 可用 | 0 | 14 字符偏长，易误认浏览器工具 |
| srtcraft | SRT 工艺 | 404 可用 | 0 | 绑定单一格式，排除 |
| linecue | 字幕行 | 404 可用 | 0 | 语义偏弱 |
| linguacue | 语言 + cue | 404 可用 | 5 | 最直白，辨识度一般 |
| dualine | 双语双行 | 404 可用 | 3 | 只覆盖双语，偏窄 |
| cuebridge | 语言之桥 | 404 可用 | 9 | 偏平庸 |
| subweave | 双语编织 | 404 可用 | 7 | 形象，weave 类重名多 |
| subtide | 字幕潮汐 | 404 可用 | 7 | 语义弱 |
| cuecraft | 字幕工艺 | 404 可用 | 16 | 重名偏多，排除 |
| cueforge | 字幕锻造 | 404 可用 | 20 | 重名偏多，排除 |
| subloom | 织机 | 404 可用 | 10 | 重名偏多，排除 |
| cueline | 字幕行 | 404 可用 | 30 | 重名偏多，排除 |
| cuelog | 字幕日志 | 404 可用 | 46 | 排除 |
| transline | 跨语言 | 404 可用 | 102 | 排除 |
| **cuewright** | 语义最贴切 | **200 已占用** | 2 | **禁用** |
| subline | 字幕行 | 200 已占用 | 212 | 禁用 |
| interline | 逐行对照翻译 | 200 已占用 | 323 | 禁用 |

关键发现：PyPI 上已有 `cuewright 0.2.2`，简介为 *"Transcribe speech, translate it, and produce verified subtitles."* —— 与本项目完全同赛道，故不能用。

命名一致性要求：仓库 `cueloom/cueloom`、PyPI `cueloom`、CLI `cueloom`、镜像 `cueloom:latest`、环境变量前缀 `CUELOOM_`、配置节 `cueloom`。

> 核验局限：GitHub `in:name` 是近似搜索，不覆盖组织名、npm、域名与商标；正式发布前需另查域名与商标。

## 3. 风险登记

| ID | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R-01 | 上游开源项目停更/改名（KrillinAI→OpenCreator、Voice-Pro 暂停、Linly-Dubbing 停滞） | 参考实现失效 | 只依赖底层库（faster-whisper / pysubs2 / Qwen3-ASR），不依赖端到端项目 |
| R-02 | 模型权重许可证与代码许可不一致 | 商用合规 | 逐个核对 model card；`01 §3` 矩阵；发布前做许可审计 |
| R-03 | LLM 服务不支持严格 JSON Schema | 翻译阶段不稳 | `05 §1` 降级路径 + 按 cue 拆分重试 |
| R-04 | 中文 ASR 榜单数字不可靠（厂商自测） | 选型错误 | 用 T1/T2 自有测试集 A/B，不采信榜单 |
| R-05 | 强制对齐模型对中文/混说覆盖不足 | 时间码漂移 | 备选 WhisperX / MFA；低置信词打 `align_low_conf` 并抽检 |
| R-06 | 术语表维护成本随素材增长 | 译文不一致 | 术语表版本化 + 质检 `term_miss` 硬门槛 |
| R-07 | 长视频内存与耗时 | 大任务失败 | 按 ASR 段流式处理，JSONL 逐行写，不把整片读进内存 |
| R-08 | LLM token 成本失控 | 预算超支 | 单 cue 缓存、反思轮默认关闭、批次与上下文窗口有上限、运行摘要记录用量 |
| R-09 | 翻译质量无客观真值 | 回归不可判定 | 固定测试集 + 人工抽样评分 + 基线对照（`06`） |
| R-10 | 项目名 / 许可证未确认就开工 | 返工 | 开工第一步先确认 D-01 / D-07，见 `08` |

## 4. 待决项（项目会话开工先确认）

| 编号 | 待决问题 | 建议 | 影响面 |
|---|---|---|---|
| D-01 | 开源许可证 | Apache-2.0（或 MIT） | LICENSE、README、依赖合规 |
| D-02 | 默认 ASR 后端与模型 | faster-whisper large-v3；中文场景 T2 实测后再定 | Stage 1、依赖 |
| D-03 | 是否需要说话人标签 | 一期不需要（C-1 只排除配音，未要求 diarization） | 若需要则新增 stage |
| D-04 | 是否支持已有 SRT 直接翻译 | 建议 M2 加 `--input-srt` 旁路，跳过 Stage 1/2 | CLI、pipeline |
| D-05 | 反思轮是否默认开启 | 默认关闭，M2 评测后决定 | 成本与质量 |
| D-06 | 单视频 token 预算上限 | 待用户提供 LLM 服务 RPM/TPM 与计费模型 | 限流、批次 |
| D-07 | 项目名最终确认 | CueLoom | 全仓命名，越早越好 |
| D-08 | 是否需要多目标语言一次输出 | 一期单目标语言 | 输出契约、CLI |
| D-09 | 双语行序（原文在上还是译文在上） | 默认 `source_first`，可配 | 输出 |
| D-10 | FastAPI 服务化的时机 | M3，出现批量/集成需求时 | 架构 |

解决待决项时：把结论写回本表并注明日期与决策人，重大选择追加 ADR。
