# models/ · 项目内模型资产目录

本目录是 CueLoom **唯一**的模型权重存放位置（U-7）。它和项目源码在一起，不是
`~/.cache/huggingface` 之类的系统缓存目录，因此可以直接查看、搬移、备份和删除。

## 状态

2026-11-09：目录骨架已建立，**尚无任何模型权重**。模型工作台（查看 / 下载 / 删除）
的设计见 [`docs/10-model-workbench.md`](../docs/10-model-workbench.md)，代码待 M0.6 实现。

## 预期布局

```
models/
├── README.md                        # 本文件，唯一入库的文件
├── asr/
│   ├── faster-whisper-large-v3/     # ≈ 3.09 GB，MIT，默认 ASR
│   └── faster-whisper-small/        # ≈ 0.49 GB，MIT，冒烟 / 低配
├── align/
│   └── Qwen3-ForcedAligner-0.6B/    # ≈ 1.84 GB，Apache-2.0，M2 才接入
├── .downloads/                      # 下载暂存，*.partial
├── .trash/                          # 软删除回收区
└── manifest.json                    # 扫描结果缓存，可再生
```

一个模型一个目录，目录内直接放权重与配置文件，可作为本地路径传给
`faster_whisper.WhisperModel(..., local_files_only=True)`，加载时完全不联网。

## 规则

- **除本文件外，目录内容一律不进 git**：`.gitignore` 用 `models/*` + `!models/README.md`，
  并有 `*.bin` / `*.safetensors` / `*.gguf` / `*.onnx` / `*.pt` 全局忽略做双保险。
  单个模型约 0.5–3 GB，误提交会造成不可逆的仓库膨胀（R-13）。
- **镜像不含权重**：`.dockerignore` 排除 `models`；容器运行时通过 `./models:/app/models`
  挂载（D-17 未拍板前为设计约定）。
- **手工放入的模型**会被识别为 `unmanaged`：可以查看与删除，但不会自动加载，
  需要先登记到 `configs/model-catalog.yaml`。
- 删除只能经由工作台，且必须二次确认；默认软删除到 `.trash/`，不提供一键清空 `models/`。
- 下载中断的半成品留在 `.downloads/` 并标为 `partial`，不会被当成可用模型。

## 许可

代码库许可与模型权重许可、API 服务条款是三件独立的事，见 `docs/01 §3`。
发布前需逐个核对 model card（R-02 / R-17）。
