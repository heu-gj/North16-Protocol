# North16 Protocol

海冰数据集的结构化管理、相机抽帧、可见光预标注和 Dataset 读取工具。Python 包名、导入名和命令均为 **`north16`**，当前版本 **0.10.0**，要求 **Python 3.10+**。

原始视频 → 初始化结构化目录 → 相机抽帧 → 调参预览 → 首/中/末检查 → 导出 JSON 标签包 → 合并数据集 → 人工修正与审核。

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
python -m pip install "north16[gui] @ git+https://github.com/heu-gj/North16-Protocol.git@v0.10.0"

# 从 GitHub Releases 下载 wheel 后安装
python -m pip install ".\north16-0.10.0-py3-none-any.whl[gui]"
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

以下是 Windows 路径示例；换成自己的输入、输出路径即可。初始化输出须为新目录。

```powershell
# 1. 只登记视频并初始化目录，不解码、不创建 masks
north16 initialize --raw E:\data\raw --output E:\data\datasets

# 2. 相机模块抽帧，保留原尺寸、逐帧 PTS 和来源信息
north16 camera extract --root E:\data\datasets

# 可选：每隔至少5秒保留一个实际帧；与上面的全量方式二选一
north16 camera extract --root E:\data\datasets --interval 5

# 3. 在界面中选择片段、visible 镜头并调参
north16 segmentation gui --root E:\data\datasets
```

界面操作：

1. 进入“16路总览 / 勾选导出”，点击某个镜头进行独立调试。
2. 可选“两点直线”地平线，拖动左右端点调整高度和倾斜；也支持多点折线。忽略半宽默认图高的 1.00%。
3. 人工选择冰水混合、全冰或全水模式；默认保留当前地平线，自动估计亮度阈值，再修调预览。各镜头参数独立。
4. 点击“验证16路：开头 / 中间 / 末尾”，用 4×4 总览或逐镜头三帧并排检查。不生成标签、不重新估参。
5. 勾选要导出的镜头，点击“导出勾选镜头的标签”。调参完成后保持“生成前各镜头独立自动估参”不勾选，使用当前参数处理当前片段所选镜头的全部帧。
6. 点击“打开最近输出目录”查看标签包。默认位于数据集相邻的 `labels/<批次>/`；也可选择输出位置。其他片段分别检查、导出。

现有自动目录发现适配 North16 采集布局；其他原始布局需要增加适配器。当前 GrabCut 预标注仅适配 **visible**，**infrared** 支持抽帧、浏览与像素查看。各设备时间戳登记不代表完成同步认证。

`--interval` 单位为秒，接受正小数；省略则保存全部可解码帧。按源PTS从首帧开始，相邻保留帧至少间隔指定秒数，实际间隔取决于视频中可用帧；不生成补帧。文件名保留源解码帧号，如 `f000000.png`、`f000005.png`；元信息保留PTS、time_base、源帧号和保存序号。各路独立取样，不代表时间对齐。对已有完整流更改间隔会报冲突，请初始化另一个数据集目录。

## 数据目录和导出包

初始化不抽帧、不创建 `masks/`；抽帧后得到：

```text
datasets/
  info.txt / protocol.txt / classes.txt
  sources.txt / samples.txt
  sequences/<sequence>/
    info.txt
    visible/<camera>/
      info.txt / frames.txt
      images/f000000.png
      meta/f000000.txt
    infrared/<camera>/
      ...
  sync/info.txt
```

界面导出的标签包：

```text
labels/<batch>/
  package.txt / files.txt / README.txt / last_run.json
  parameters/<sequence>/visible/<camera>_<run>.json
  dataset/sequences/<sequence>/visible/<camera>/
    masks/f000000.json
```

标签文件统一放在 **`masks/*.json`**；标签包不重复携带原图。可整包校验导入：

```powershell
north16 import-package --root E:\data\datasets --package E:\data\labels\batch_01
```

也可将包内 `dataset/` 的内容整体合并到数据集根目录，无需逐个复制 masks。校验导入会拒绝内容不同的同名文件，保护已有标注。

合并后，JSON 的 `../images/<frame>.png` 关联原图，可用 X-AnyLabeling 修正。类别为 `sky=0`、`water=1`、`ice=2`、`other=3`，不确定区域 `ignore=255`。算法输出为 **draft/unreviewed**，需人工修正与审核后作为 benchmark 真值。

## Dataset 读取

先安装 `[training]` 或 `[all]`：

```python
from north16.datasets import SegmentationDataset

dataset = SegmentationDataset(
    root=r"E:\data\datasets",
    split=None,
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

产物为 `dist/north16-0.10.0-py3-none-any.whl` 和 `dist/north16-0.10.0.tar.gz`，包含 Python 模块、协议配置、TXT 模板和文档。原始视频、数据集、运行标签、虚拟环境和备份不打入包。

```powershell
python -m pip install ".[all]"
python -m unittest discover -s tests -v
```

GitHub Actions 提供 Windows 回归测试，以及 Ubuntu 上构建、检查和安装验证；推送 `v*` 标签时自动发布 wheel、源码包及 SHA256 到 GitHub Releases。

## 模块与文档

```text
src/north16/
  layout/          目录初始化与路径规范
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
| [模块与目录](docs/MODULES.md) | 结构化目录、导出包和 Dataset |
| [Python CLI](docs/CLI.md) | 命令和参数示例 |
| [界面](docs/GUI.md) | 两点地平线、调参和验证 |
| [多镜头](docs/MULTICAMERA.md) | 独立估参、并发及勾选导出 |
| [包安装与发布](docs/PACKAGE.md) | 安装、构建和版本发布 |
| [协议](docs/PROTOCOL.md) | 统一规则及质量要求 |
| [元信息](docs/METADATA.md) | TXT / TSV 元信息规范 |
| [变更记录](docs/CHANGELOG.md) | 版本变化 |

协议 ID 保持 `north16-seg-v0.1-draft`。雷达/SAR 专用处理、正式划分与官方评测尚未完整实现；文档中的设计规范与当前可执行能力分别说明。
