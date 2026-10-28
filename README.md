# North16 Protocol

海冰数据集的结构化管理、相机抽帧、可见光预标注和 Dataset 读取工具。Python 包名、导入名和命令均为 **`north16`**，当前版本 **0.11.0**，要求 **Python 3.10+**。

原始视频 → 初始化最终目录 → 独立标注工作区抽帧与标注 → 图片＋JSON 整包交付 → Dataset 读取与审核。

## 安装

建议先创建独立环境。Windows PowerShell 示例：

```powershell
git clone https://github.com/heu-gj/North16-Protocol.git
cd North16-Protocol
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install ".[gui]"
north16 --version
north16 doctor
```

也支持以下安装方式，按需要选择一种：

```powershell
# 基础 CLI，不安装界面、OpenCV 或 PyTorch
python -m pip install .

# 开发安装：修改源码后直接生效
python -m pip install -e ".[gui]"

# 从 GitHub 固定版本安装，无需手动克隆
python -m pip install "north16[gui] @ git+https://github.com/heu-gj/North16-Protocol.git@v0.11.0"

# 从 GitHub Releases 下载 wheel 后安装
python -m pip install ".\north16-0.11.0-py3-none-any.whl[gui]"
```

安装 wheel 后可在任意目录使用 `north16` 或 `python -m north16`，无需复制 `src/` 或配置 `PYTHONPATH`。从源码目录运行时也支持 `python cli.py ...`。这些安装方式不依赖 PyPI 发布。

| 安装选项 | 功能和额外依赖 |
| --- | --- |
| 基础安装 | 初始化、目录/数据包管理；NumPy、Pillow、PyYAML |
| `[annotation]` | 可见光预标注；OpenCV |
| `[gui]` | 标注与配准界面；PySide6、OpenCV |
| `[training]` | Dataset 读取；PyTorch |
| `[all]` | GUI、预标注、Dataset；PySide6、OpenCV、PyTorch |
| `[detection]` | 现有检测相关接口所需的 Ultralytics，不包含在 `[all]` 中 |
| `[dev]` | 构建及发布检查；build、twine |

视频抽帧另需安装 **FFmpeg / FFprobe** 并加入 PATH，也可通过抽帧命令的 `--ffmpeg`、`--ffprobe` 指定路径。X-AnyLabeling 是独立程序。PyTorch 的 CPU/CUDA 版本按训练环境选择。桌面 GUI 需要图形桌面环境。

## 从视频到标签

推荐使用独立 `annotation` 工作区。最终 `datasets` 初始化时不转图片、不创建 masks；图片与标签完成后一起导入。已有初始化好的 datasets 从第2步开始。

```powershell
# 1. 登记原视频并初始化最终目录（新目录）
north16 initialize --raw E:\data\raw --output E:\data\datasets
# 2. 创建标注工作区（新目录，不复制旧图片/标签）
north16 annotation initialize --dataset E:\data\datasets --output E:\data\annotation
# 3. 预检和抽帧；--interval 单位秒，省略则全量
north16 annotation extract --root E:\data\annotation --interval 5 --dry-run
north16 annotation extract --root E:\data\annotation --interval 5
# 4. 调参、验证并保存同镜头 masks/*.json
north16 annotation gui --root E:\data\annotation
# 5. 导出图片＋标签＋逐帧元信息（新目录）
north16 annotation export --root E:\data\annotation --output E:\data\delivery
# 6. 校验整包导入最终数据集
north16 import-package --root E:\data\datasets --package E:\data\delivery
```

界面选择 visible，在16路总览点击镜头独立调参，设置两点地平线（忽略半宽默认1.00%）、冰水混合/全冰/全水模式，估计并调整阈值，验证首/中/末，再勾选镜头并点击“保存勾选镜头的标签”。这些操作将 JSON 写入工作区同镜头 masks；不复制图片。

点击“导出图片＋标签整包”交付当前片段勾选的 visible 镜头；红外浏览时交付当前镜头。CLI 可用 `--sequences`、`--sensor`、`--cameras` 筛选，不筛选则交付全部完整镜头。包内包括选中镜头的所有图片（也包括未标注帧），报告单列未标注数量。旧 datasets 的外置标签包流程仍兼容。

## 数据目录和交付包

```text
annotation/                            工作区：抽帧和标注
  info.txt / protocol.txt / classes.txt / sources.txt / samples.txt
  sequences/<sequence>/<visible|infrared>/<camera>/
    info.txt / frames.txt
    images/f000000.png
    meta/f000000.txt
    masks/f000000.json                  标注后才出现
  parameters/... / last_run.json / logs/...
delivery/                              图片＋标签交付包
  package.txt / files.txt / README.txt
  dataset/sequences/...                同样的images/meta/masks路径
datasets/                              最终目录
  ...                                  初始化时仅登记和占位
  sequences/.../images + meta + masks   整包导入后获得数据
```

JSON 关联 `../images/<frame>.png`，支持人工修正。生成结果是 draft/unreviewed，需审核后作为真值；保留人工修改，不覆盖已有不同内容的标签。类别 sky=0、water=1、ice=2、other=3，ignore=255。目录与交付合同见 [ANNOTATION.md](docs/ANNOTATION.md)，完整操作见 [WORKFLOW.md](docs/WORKFLOW.md)。

抽帧间隔按源PTS选择实际帧，保留原尺寸、源帧号与PTS/time_base，不插帧、不代表各设备已同步；已有完整流更换间隔会拒绝覆盖，请建立新工作区。现有目录发现适配 North16 采集布局，其他布局需适配。GrabCut 仅适配 visible；infrared 支持抽帧、浏览和像素查看。

容量预检累计所选待处理流的宽×高×3×预计帧数×1.2，是RGB24未压缩保守估计，PNG实际可能更小。压缩视频较小并不代表抽帧占用小。可缩小片段/模态/镜头或增加间隔。工作区、交付包、最终数据集复制后各占一份空间，不自动删除源数据。

## Dataset 读取

先安装 `[training]` 或 `[all]`：

```python
from north16.datasets import SegmentationDataset

dataset = SegmentationDataset(
    root=r"E:\data\datasets",
    split=None,
    sequences=["20260902_044232"],
    sensor="visible",
    labeled_only=True,
    allowed_label_statuses=["draft"],  # 仅用于试标检查
)
sample = dataset[0]  # image: float32[C,H,W]; mask: int64[H,W]
```

默认读取要求 reviewed/adjudicated/frozen 标签。`checked=true` 不自动代表正式审核，正式 split、时间同步认证和官方评测需要另行完成。

## 构建 wheel 和源码包

```powershell
python -m pip install ".[dev]"
python -m build
python -m twine check dist/*
```

产物为 `dist/north16-0.11.0-py3-none-any.whl` 和 `dist/north16-0.11.0.tar.gz`，包含 Python 模块、协议配置、TXT 模板和文档。原始视频、数据集、运行标签、虚拟环境和备份不打入包。

```powershell
python -m pip install ".[all]"
python -m unittest discover -s tests -v
```

GitHub Actions 提供 Windows 回归测试，以及 Ubuntu 上构建、检查和安装验证；推送 `v*` 标签时自动发布 wheel、源码包及 SHA256 到 GitHub Releases。

## 模块与文档

```text
src/north16/
  layout/          目录初始化与路径规范
  annotation/      独立图片/标注工作区与完整交付
  camera/          相机抽帧、索引与导出
  segmentation/    JSON 标签生成、维护与栅格化
  packages/        数据包清单和校验合并
  gui/             标注调参、16路总览和抽样检查
  annotations/     GrabCut、参数与历史接口
  datasets/        CameraDataset / SegmentationDataset
  registration/    visible / infrared 配准工作台
```

| 文档 | 内容 |
| --- | --- |
| [工作流](docs/WORKFLOW.md) | 原始视频到标签的操作顺序 |
| [标注工作区](docs/ANNOTATION.md) | 图片/标签布局、交付和兼容合同 |
| [模块与目录](docs/MODULES.md) | 结构化目录、导出包和 Dataset |
| [Python CLI](docs/CLI.md) | 命令和参数示例 |
| [界面](docs/GUI.md) | 两点地平线、调参和验证 |
| [多镜头](docs/MULTICAMERA.md) | 独立估参、并发及勾选导出 |
| [包安装与发布](docs/PACKAGE.md) | 安装、构建和版本发布 |
| [协议](docs/PROTOCOL.md) | 统一规则及质量要求 |
| [元信息](docs/METADATA.md) | TXT / TSV 元信息规范 |
| [变更记录](docs/CHANGELOG.md) | 版本变化 |

协议 ID 保持 `north16-seg-v0.1-draft`。雷达/SAR 专用处理、正式划分与官方评测尚未完整实现；文档中的设计规范与当前可执行能力分别说明。
