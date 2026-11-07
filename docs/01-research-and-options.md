# 01 · 开源方案调研与路线选择

> 调研时间：2026-11-07 ~ 11-08。star 数、版本号、CER 等为 2026-10/11 公开资料快照，会变动。
> 来源性质：GitHub 仓库页优先；部分数据来自聚合站/技术博客/AI 生成站点，**正式选型前需以官方仓库和自有实测复核**。

## 1. 问题分解：六层流水线

「视频字幕生成 + 翻译」不是单个模型，而是六层：

| 层 | 职责 | 本项目是否需要 |
|---|---|---|
| 1 音频与 VAD | 抽轨、16k 单声道、切静音、（可选）人声分离 | 需要 |
| 2 ASR | 语音转文本 + 初版时间段 | 需要 |
| 3 强制对齐与断句 | 词级时间戳、按语义切 cue | 需要（核心） |
| 4 翻译 | 上下文感知、术语一致、反思润色 | 需要（核心，接自有 LLM） |
| 5 校对与质检 | 时间码、CPS、术语、覆盖率 | 需要（核心） |
| 6 输出 | SRT/VTT/ASS；烧录 / mux | **仅字幕文件，不要烧录与 mux** |

端到端开源项目通常还包含：yt-dlp 下载、TTS 配音、声音克隆、视频合成、字幕烧录、GUI —— 在 C-1/C-2 下全是负担。

## 2. 组件层可用开源件

| 环节 | 首选 | 备选 | 许可 / 要点 |
|---|---|---|---|
| 抽轨 / VAD | PyAV（faster-whisper 内置）、Silero VAD | FFmpeg（仅抽轨）、Demucs / MDX-Net | Silero MIT，约 2 MB，CPU 单线程每块 < 1 ms |
| ASR · 通用多语 | **faster-whisper**（MIT） | openai/whisper、whisper.cpp、WhisperX | CTranslate2 约 4× 加速、精度不变；whisper.cpp（MIT）覆盖 Metal / 端侧 / WASM |
| ASR · 中文优先 | **Qwen3-ASR-1.7B**（Apache-2.0）、**FunASR / SenseVoice** | FireRedASR、Paraformer、sherpa-onnx | FunASR 官方 184 条中文长音频自测 CER 7.81% vs Whisper large-v3 20.02%，且 CPU 更快（厂商自测，第三方复现有限） |
| 强制对齐 | **Qwen3-ForcedAligner-0.6B** | WhisperX（wav2vec2）、MFA、whisper-timestamped | Whisper 原生段时间戳约 1 s 漂移；对齐后可 < 100 ms。WhisperX BSD-2-Clause |
| 说话人分离 | pyannote.audio | FunASR CAM++、NeMo Sortformer | 一期不做；pyannote 为 gated 模型 + CC-BY-4.0，需 HF token |
| 翻译 | **LLM + 术语表**（自有服务 / Qwen3.x / Ollama） | MADLAD-400、Opus-MT、Argos、M2M100、ALMA | 传统 NMT 无上下文，字幕场景明显吃亏 |
| 字幕格式 | **pysubs2** | 自写 SRT/VTT 生成器、ffsubsync | 支持 SRT / VTT / ASS 等；ASS 可做双语样式 |
| 校对工具 | Subtitle Edit（GPL-2.0）、Aegisub（BSD） | 自写规则闸门 | 仅人工校对环节用，不进运行时依赖 |

## 3. 翻译模型许可证矩阵（商用前必查）

| 模型 / 服务 | 覆盖 | 许可 | 商用 |
|---|---|---|---|
| NLLB-200、Tower、Aya Expanse | 200 / 10 / 多语 | CC-BY-NC 4.0 | 禁止 |
| MADLAD-400 | 400+ 语言 | Apache-2.0 | 允许 |
| Opus-MT / Argos Translate | 1000+ 方向 | CC-BY 4.0 / MIT（Argos 双许可） | 允许（署名） |
| LibreTranslate（服务端） | 包装 Argos | AGPL-3.0 | 网络 copyleft，需评估 |
| TranslateGemma | Gemma 3 系 | Gemma 自定义条款 | 需逐条审 |
| Qwen3.x / ALMA | 通用 / 翻译专用 | Apache-2.0 / MIT | 允许 |

注意「仓库代码许可 ≠ 模型权重许可 ≠ API 服务条款」三层要分别确认。

## 4. 端到端开源项目对比

| 项目 | 协议 | 规模 / 活跃 | 长处 | 主要代价 |
|---|---|---|---|---|
| pyVideoTrans | GPL-3.0 | ~19.6k，v4.18（2026-11-06） | GUI/CLI/WebUI/Docker，30+ 渠道，分角色配音、F5-TTS 克隆、逐阶段校对 | GPL 传染；CUDA 12.8 + cuDNN；配音与烧录全是本项目不需要的重量 |
| VideoLingo | Apache-2.0 | ~18.9k，v3.1.x（2026-09-30 最后 push） | Qwen3-ASR + ForcedAligner、术语表、翻译→反思→润色、单行/双语字幕；有 `--api` 本地 HTTP 接口与 batch 模式（`dubbing=0` 关配音） | Streamlit 单机形态、全局 config.yaml、LLM 调用单任务同步；FFmpeg 7 共享库挑剔；依赖旧版 torch（扫描报告 2 个 critical 公告） |
| VideoCaptioner | GPL-3.0 | ~13–16k | 免费通道零配置、LLM 断句与批量校正、反思翻译 | GPL；高级能力依赖云 LLM |
| SmartSub（妙幕） | MIT | ~5.8k，v3.7 | 8 类本地 ASR + 20 种翻译服务 + 校对台 + 本地 TTS/克隆 + 烧录，零 API Key 全离线 | 桌面 Electron 形态，无服务端 |
| SubsAI | GPL-3.0 | 较小 | WebUI/CLI/Python 包，多种 Whisper 后端 + dl-translate + 对齐 + 烧录 | Python 3.10/3.11 限定；默认 NLLB 不可商用；维护偏慢 |
| OpenCreator（原 KrillinAI） | Apache-2.0 | ~13.9k | Go 编写、Docker 友好 | 已转型创作者工作台，视频翻译只占十分之一，旧教程失效 |
| Subtitle Edit / Aegisub | GPL-2.0 / BSD | 长期活跃 | 波形校对、200+ 格式、OCR 硬字幕、翻译插件、ASS 样式 | 是编辑器，不是流水线 |
| SoniTranslate / YouDub / Voice-Pro / Linly-Dubbing / open-dubbing | Apache-2.0 / GPL | 0.4k–13.3k | 配音与说话人控制向 | Voice-Pro README 标开发暂停；Linly-Dubbing 停在 2025-03 |

主要仓库：
`github.com/Huanshere/VideoLingo`、`github.com/jianchang512/pyvideotrans`、`github.com/buxuku/SmartSub`、`github.com/WEIFENG2333/VideoCaptioner`、`github.com/SubtitleEdit/subtitleedit`。

## 5. 关键工程发现（直接写进 `04` 的参数依据）

1. **幻觉抑制**：`vad_filter=True` + `condition_on_previous_text=False` + `speech_pad_ms=400`；有 2000 条样本实测从 183 条幻觉降到 22 条，再加短语黑名单降到 4 条。单靠调低 `no_speech_threshold` 几乎无效（`avg_logprob` 会一票否决跳过）；`hallucination_silence_threshold` 只在 `word_timestamps=True` 时生效。
2. **时间戳漂移**：Whisper 段时间戳是解码 token 的近似值，长视频必然漂。二阶段强制对齐或改用自带词级时间戳的模型（Parakeet TDT / Qwen3-ASR + Aligner）。
3. **断句**：词级时间戳 → 语义分组 → 阅读速度约束 → 不拆数字、不留行尾虚词。**只把纯文本送给 LLM，时间码留在本地**。
4. **术语**：ASR 侧 hotwords / initial_prompt + 译侧术语表 + 输出侧正则兜底，三层叠加 ROI 最高。
5. **质检闸门**：CER/WER、幻觉率、时间码单调/重叠/零时长、CPS、术语一致率、数字与否定保留、100% cue 覆盖。
6. **许可**：GPL 项目（pyVideoTrans / VideoCaptioner / SubsAI / Subtitle Edit）不适合作为闭源产品基础；Apache-2.0（VideoLingo / Qwen3-ASR）可安全参考。

## 6. 三条路线与选择

| 路线 | 首版可用 | 契合约束 | 可控性 | 结论 |
|---|---|---|---|---|
| A 直接部署现成开源项目 | 半天 | 中 | 低 | 仅作为**质量基线对照组**（VideoLingo 纯字幕模式 + 同一 LLM 端点） |
| B Fork-and-slim（fork VideoLingo 做减法） | 2–3 天 | 高 | 中 | 备选；核心逻辑与 Streamlit、路径约定、config.yaml 强耦合，剥离成本接近重写编排层 |
| **C 自建薄编排层** | 3–5 天出可跑 CLI | 最高 | 高 | **采用**：复用库 + 自写约 1500–2500 行编排 |

选择 C 的决定性理由：

- C-1/C-2 去掉了现成项目 60–80% 的功能，剩下的部分（Streamlit、TTS、yt-dlp、FFmpeg 烧录、全局配置）全是负担。
- C-3 自有 LLM 意味着需要控制并发、限流、按 cue 重试、JSON Schema 校验、prompt 版本、缓存与成本归因；现成项目的 LLM 客户端是单任务同步调用，这层无法复用。
- 现成项目最值钱的「语义断句 + 术语表 + 反思翻译」恰好是最该自己掌握、也最需要可测试的部分。

**推翻条件**：如果只是偶尔翻几段视频、不做服务化与二次集成，应改用路线 A，不必自建。当前用户意图（自有 LLM 服务、只要字幕文件、另开项目会话做工程）明确落在 C。

## 7. 数据可信度提醒

- star 数与版本号为快照，来自仓库页或二手汇总，需复核。
- FunASR / Qwen3-ASR 的中文 CER 多为厂商自测，第三方复现有限；**禁止把榜单数字当作验收结论**，见 `06`。
- 幻觉抑制的 183→22→4 数据来自技术文章实测，需在自建测试集上复现后方可写进验收门槛。
- 部分对比站点为 AI 生成内容聚合，License 字段曾出现互相矛盾（例如把 VideoLingo 写成 MIT），以官方 LICENSE 文件为准。
