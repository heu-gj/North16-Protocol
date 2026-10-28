# Python 包安装与发布

分发名、导入名、命令均为 `north16`，当前版本 0.11.0，Python >=3.10。仓库名为 North16-Protocol。包版本与 benchmark 协议版本分别管理。

0.11.0 推荐通过 `north16 annotation initialize/extract/gui/export` 管理独立工作区，界面直接保存同镜头masks/*.json，再将图片＋标签整包导入datasets。详见 [WORKFLOW.md](WORKFLOW.md)。升级不会自动迁移旧数据、移动图片或覆盖人工标签。

## 安装

在仓库根目录运行：

```powershell
python -m pip install .
python -m pip install ".[gui]"
python -m pip install -e ".[gui]"
```

以上分别为基础安装、标注界面安装、开发安装，按需求选择一种。Dataset 另需 `[training]`，`[all]` 包含 GUI / OpenCV / PyTorch，`[detection]` 单独安装 Ultralytics。

无需克隆的固定版本安装：

```powershell
python -m pip install "north16[gui] @ git+https://github.com/heu-gj/North16-Protocol.git@v0.11.0"
```

从 [GitHub Releases](https://github.com/heu-gj/North16-Protocol/releases) 下载 wheel 后：

```powershell
python -m pip install ".\north16-0.11.0-py3-none-any.whl[gui]"
north16 --version
north16 doctor
north16 segmentation gui --root E:\data\datasets
```

`python -m north16` 与 `north16` 等价；源码仓库额外支持 `python cli.py`。标准安装无需 PYTHONPATH，不依赖本机 E 盘路径。示例路径应替换为实际路径。FFmpeg / FFprobe 和 X-AnyLabeling 为外部工具；pip 不安装它们。离线安装需提前准备所选依赖。

安装到自己的 Python 环境后，可在任意工作目录运行 CLI。Windows 便捷启动器默认寻找仓库的 `.venv`，也可指定解释器；通用启动推荐使用 `north16 segmentation gui --root ...`。

## 构建

```powershell
python -m pip install ".[dev]"
python -m build
python -m twine check dist/*
```

`python -m build` 默认先生成 sdist，再从 sdist 构建 wheel，便于检验源码包是否包含完整资源。`setup.py` 仅负责在构建时收集唯一维护源 `configs/`、`templates/`、`docs/`。wheel 通过 `importlib.resources` 读取内置资源。

```text
dist/
  north16-0.11.0-py3-none-any.whl
  north16-0.11.0.tar.gz
```

包内包含协议配置、模板、文档及文档示意图；不包含原始视频、数据集、标签输出、缓存、虚拟环境、备份或权重。`py3-none-any` 表示包自身为纯 Python；OpenCV、Qt、PyTorch 依赖仍需对应平台支持。

## 测试

```powershell
python -m pip install ".[all]"
python -m unittest discover -s tests -v
```

桌面测试使用 offscreen 平台，可不显示真实窗口。抽帧测试需要 FFmpeg / FFprobe。GitHub Actions 的 Windows 任务安装 CPU PyTorch、GUI 依赖并运行回归；Ubuntu 任务检查构建、wheel / sdist 安装、命令和内置资源。

## 发布到 GitHub

更新 `pyproject.toml`、`src/north16/__init__.py`、安装示例及变更记录中的版本后，先运行测试和构建检查。然后提交代码，推送对应版本标签，例如：

```powershell
git tag -a v0.11.0 -m "North16 0.11.0"
git push origin main
git push origin v0.11.0
```

`.github/workflows/release.yml` 先执行测试及安装验证，通过后才创建 GitHub Release 并上传 wheel、sdist 和 `SHA256SUMS.txt`。版本标签必须匹配 Python 包版本。源码不提交 dist 构建目录；安装包从 Releases 下载。

当前发布方式为 GitHub 源码 / VCS 安装和 Release wheel，不需要 PyPI 账号或 PyPI 发布。
