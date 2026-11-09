# CueLoom

把视频 / 音频转成**带翻译的字幕文件**（SRT / VTT / ASS）。
不做配音、不烧录、不合成视频；翻译由使用者自有的 LLM 服务完成。

> 仓库状态（2026-11-09）：`main` 已绑定 `https://github.com/DPCau/cueloom.git` 并持续推送；M0 文档 + M0.5 控制台/只读看板 + M1 原型流水线（五阶段实现、双语 SRT 输出、20 项单测/集成测试通过）均已完成；**M0.6 模型资产设计（`docs/10`）与 M0.7 统一 Web 工作台设计（`docs/12`）已落盘，代码待开工**；`.venv`（Python 3.12.10）由 `uv` 管理。
> 规范路径：`~/MyProject/cueloom`（macOS 大小写不敏感，写 `~/Myproject/cueloom` 也指向同一目录）。

## 新会话必读

本仓库由 2026-11-07/08 的调研会话创建，那段会话的上下文会被删除。
所有调研结论、设计决策、命名核验与未决问题都已落盘到 `docs/`。
项目会话开工请按 `docs/README.md` 的阅读顺序执行，至少读 `00`、`02`、`03`、`08`。

## 快速开始

```bash
./ctl.sh          # 交互式菜单：1 启动 / 2 停止 / 3 状态 / 6 初始化环境
```

首次使用选 `6` 生成 `.env`，填入 `CUELOOM_LLM_BASE_URL` / `CUELOOM_LLM_API_KEY` / `CUELOOM_LLM_MODEL`；浏览器页面默认 http://127.0.0.1:8000 。服务测完请及时用菜单 `2` 关闭。部署与生命周期设计见 `docs/09-console-and-deploy.md`。
模型权重将放在项目内 `models/`（不放系统缓存），识别 / 下载 / 删除护栏见 `docs/10-model-workbench.md`。
**规划中的操作形态**（U-11~U-13，设计见 `docs/12-web-workbench.md`）：`ctl.sh` 只管服务启停，浏览器里的统一 Web 工作台承担工作流运行、配置修改、模型管理与 LLM API 管理。当前页面仍是 M0.5 的只读看板，上述写能力待 M0.7 实现。

## 硬约束（设计不得破坏）

1. 输出只有字幕文件：不烧录、不 mux、不生成视频、不下载视频。
2. 不做按角色配音 / TTS / 声音克隆 / 说话人分轨。
3. 时间码永不交给 LLM；LLM 只处理 `{id, text}`，按 id 回填。
4. 自有 LLM 服务是唯一翻译后端（OpenAI 兼容端点），不内置第三方翻译 API。
5. Python 环境用 `uv` 在项目目录管理（用户长期约定）。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/` | 全部设计文档，索引见 `docs/README.md`（模型资产 `docs/10`、统一 Web 工作台 `docs/12`） |
| `models/` | 项目内模型资产目录（U-7）；权重与运行产物全部 gitignore，只保留 `README.md`；查看 / 下载 / 删除待 M0.6 实现 |
| `inbox/` | 规划中的浏览器上传素材目录（U-12，gitignore，M0.7 生效） |
| `ctl.sh` | 服务生命周期入口：交互式菜单启停服务 / 查看状态 / 环境初始化 / Docker 模式，兼 CLI 兜底 |
| `src/cueloom/` | 五阶段流水线、FastAPI 服务与零构建浏览器页面（当前为只读看板） |
| `.env.example` | 环境变量模板（LLM API 等），复制为 `.env` 后填写，`.env` 不入库 |
| `Dockerfile` / `docker-compose.yml` | 部署配置；构建产物不落本机项目目录 |
| `.agents/blackboard.md` | 多智能体协同黑板（追加写、已在 `.gitignore` 排除 git） |

## 命名

`CueLoom`（暂定，待用户最终确认）。`cue` 是字幕行业对「一条字幕」的标准称呼，`loom` 指把原文 / 译文 / 时间轴交织；名字刻意不含 video / dub / voice / burn，以免误导范围。命名核验数据见 `docs/07-decisions-and-risks.md`。

## 许可证

**未定**，见 `docs/07-decisions-and-risks.md` 待决项 D-01（建议 Apache-2.0，待确认后再放 `LICENSE` 文件）。
