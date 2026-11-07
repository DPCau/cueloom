# CueLoom

把视频 / 音频转成**带翻译的字幕文件**（SRT / VTT / ASS）。
不做配音、不烧录、不合成视频；翻译由使用者自有的 LLM 服务完成。

> 仓库状态（2026-11-08）：`main` 分支已绑定远端 `https://github.com/DPCau/cueloom.git`，M0 文档已首次提交并推送（`2cadb7a`）；**尚无源码**；`.venv`（Python 3.12.10）已由 `uv` 创建。
> 规范路径：`~/MyProject/cueloom`（macOS 大小写不敏感，写 `~/Myproject/cueloom` 也指向同一目录）。

## 新会话必读

本仓库由 2026-11-07/08 的调研会话创建，那段会话的上下文会被删除。
所有调研结论、设计决策、命名核验与未决问题都已落盘到 `docs/`。
项目会话开工请按 `docs/README.md` 的阅读顺序执行，至少读 `00`、`02`、`03`、`08`。

## 硬约束（设计不得破坏）

1. 输出只有字幕文件：不烧录、不 mux、不生成视频、不下载视频。
2. 不做按角色配音 / TTS / 声音克隆 / 说话人分轨。
3. 时间码永不交给 LLM；LLM 只处理 `{id, text}`，按 id 回填。
4. 自有 LLM 服务是唯一翻译后端（OpenAI 兼容端点），不内置第三方翻译 API。
5. Python 环境用 `uv` 在项目目录管理（用户长期约定）。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/` | 全部设计文档，索引见 `docs/README.md` |
| `.agents/blackboard.md` | 多智能体协同黑板（追加写、已在 `.gitignore` 排除 git） |

## 命名

`CueLoom`（暂定，待用户最终确认）。`cue` 是字幕行业对「一条字幕」的标准称呼，`loom` 指把原文 / 译文 / 时间轴交织；名字刻意不含 video / dub / voice / burn，以免误导范围。命名核验数据见 `docs/07-decisions-and-risks.md`。

## 许可证

**未定**，见 `docs/07-decisions-and-risks.md` 待决项 D-01（建议 Apache-2.0，待确认后再放 `LICENSE` 文件）。
