# 08 · 里程碑与项目会话开工清单

## 1. 里程碑总览

| 里程碑 | 目标 | 完成标志 | 状态 |
|---|---|---|---|
| M0 | 调研、选型、命名、仓库与文档 | 本套 `docs/` + git 初始化 + 黑板交接记录 | **已完成（2026-11-08）** |
| M0.5 | 项目框架、控制台与看板 | `pyproject.toml` + `.env.example` + `ctl.sh` + FastAPI 只读看板 + Docker 配置；冒烟后服务已关闭 | 进行中（2026-11-08） |
| M1 | 可跑 CLI 端到端 | 一段 30–60 s 音频 → 双语 SRT，五阶段 JSONL 齐全，可 resume | 待开始 |
| M2 | 质量对齐基线 | T1–T5 测试集 + VideoLingo 基线 + 回归脚本，指标达标 | 待开始 |
| M3 | 服务化 | FastAPI 薄封装（`/jobs`、`/jobs/{id}`），CLI 与 API 共用 pipeline | 待开始 |
| M4 | 可选增强 | 多目标语言、已有 SRT 旁路、ASS 样式、LLM 辅助断句、反思轮 | 待定 |

## 2. M0 已完成内容（本会话交付）

- 两轮调研：开源方案全景、许可证矩阵、端到端项目对比、路线 A/B/C 选择（`01`）。
- 架构与契约：五阶段架构、目录结构、数据模型、LLM JSON Schema、CLI 契约（`02` / `03`）。
- 阶段详设与 LLM 接入规范、质量体系、ADR、命名核验、风险与待决项（`04`–`07`）。
- 仓库：`~/MyProject/cueloom`，`git init -b main`，`.gitignore`（含黑板排除），根 README。
- 协同黑板：`~/MyProject/cueloom/.agents/blackboard.md`，已写入交接记录。
- **未做**：源码、依赖安装、LICENSE、CI。（首次 git commit 与远端推送已于 2026-11-08 完成，见 §7）

## 3. M1 任务拆解（项目会话第一目标）

按依赖顺序执行，每完成一项在 `.agents/blackboard.md` 单行追加进度：

1. 确认 D-07 项目名、D-01 许可证（若定 Apache-2.0 则补 `LICENSE` 与 README 许可声明）。
2. `uv init` / 手写 `pyproject.toml`，Python 3.11+，CLI 入口 `cueloom`；`uv add` 最小依赖（pydantic / PyYAML / pysubs2 / faster-whisper / typer）。
3. 实现 `models.py`（照 `03 §1`）、`config.py`（配置分层与环境变量）、`io/jsonl.py`。
4. 实现 `stages/asr.py` + `llm/client.py` 的最小连通性探测（先跑通 `--help` 与 LLM 探活）。
5. 实现 `stages/segment.py` 的规则断句（先用 ASR 段边界 + CPS 规则，对齐后端可后置为 `none` 兜底）。
6. 实现 `stages/translate.py`（批次、术语表、Schema 校验、按 cue 重试、缓存）。
7. 实现 `stages/qc.py`（先做 6 条硬门槛规则）与 `stages/emit.py`（SRT 单语 + 双语）。
8. 实现 `pipeline.py` 状态机与 `cli.py` 的 `run / resume / validate`。
9. 端到端验收：T1 素材 → 源语 SRT + 目标语 SRT + 双语 SRT；断言时间码不可变、cue 覆盖率 100%。

**M1 验收命令（示意）**：

```bash
uv sync
export CUELOOM_LLM_BASE_URL=... CUELOOM_LLM_API_KEY=... CUELOOM_LLM_MODEL=...
uv run cueloom run tests/fixtures/T1.wav --to zh-CN --bilingual --format srt --out ./out/demo
uv run cueloom validate out/demo/*.srt
pytest tests/unit tests/integration
```

## 4. M2 任务拆解

- 接入强制对齐后端（Qwen3-ForcedAligner / WhisperX），替换 M1 的段级兜底时间戳。
- 建 T1–T5 测试集与金标准 SRT；跑 VideoLingo 纯字幕基线并存 `tests/baseline/`。
- 补齐 `04 §4` 全部质检规则、`06` 指标脚本与 A/B 报告模板。
- 校准所有阈值并固化验收门槛；按 `01 §7` 复现幻觉抑制与中文 CER 数据，不采信榜单。
- 形成 `docs/10-eval-report.md`（首版评测报告；`09` 已用于控制面与部署设计），指标不达标则回到对应 stage 修。

## 5. M3 / M4（按需）

- M3：`server.py` FastAPI 薄封装、任务状态查询、产物下载；不引队列/数据库，除非出现真实并发压力。
- M4：`--input-srt` 旁路、多目标语言、ASS 样式表、LLM 辅助断句、反思轮、跨 job 缓存。

## 6. 项目会话开工清单（照做即可）

1. **读黑板**：`.agents/blackboard.md` 最后至少 10 行，了解 M0 结论。
2. **读文档**：`docs/README.md` → `00` → `02` → `03` → `08` → `09`（控制面 / 看板 / 部署）；实现某阶段时再读 `04` / `05`。
3. **确认待决项**：`07 §4` 的 D-07（名字）、D-01（许可证）、D-02（ASR 默认后端）、D-06（LLM 服务 RPM/TPM 与预算）。
4. **确认环境**：`uv --version`、Python 3.11+；检查 `git status`（首次提交已完成，`main` 已跟踪 `origin/main`；**注意 `.agents/blackboard.md` 已被 gitignore 排除**）。
5. **先写测试再写实现**：`tests/unit/test_segment.py` 与 `tests/integration/test_time_invariant.py` 是最能防止架构跑偏的两个。
6. **每个阶段完成/改核心接口/得出测试结论/遇阻塞**，按规范单行追加黑板：
   `- [Agent名称][YYYY-MM-DD HH:MM] 关键动作/产出/状态`
   只追加，不覆盖；黑板不进 git。
7. 首个可验证目标定为「T1 素材端到端产出双语 SRT」，不要一上来做服务化或调模型。

## 7. 交接备注（给没有本会话上下文的新会话）

- 本仓库由 2026-11-07/08 的调研会话创建，会话上下文将被删除；**所有结论已写入 `docs/`，不要靠猜**。
- 用户约束原话要点保存在 `00 §3`；不要擅自把配音、烧录、GUI「顺手加回来」。
- 用户跨项目约定：Python 环境默认用 `uv` 在项目目录管理；需要代理时可用本机 7897 端口。
- 规范路径 `~/MyProject/cueloom`（真实大小写为 `MyProject`）；macOS 大小写不敏感，`Myproject` 亦可。
- `.workbuddy/` 是项目数据目录，不是缓存，**不要删除**。
- git 状态：`main` 分支，首次提交 `2cadb7a` 已推送 `origin/main`；`.agents/blackboard.md` 已在 `.gitignore` 中排除，**禁止提交或推送黑板**。
- 外部数据（star / 版本 / CER / 许可证）为 2026-10/11 快照，实施前复核官方仓库与 model card。
- 2026-11-08 追加目标 U-1~U-6 见 `09`：**唯一入口是 `./ctl.sh` 菜单**，不要改回复杂参数启动；Docker 产物不得留本机；测试后必须关闭服务；每阶段结束提交推送一次。
