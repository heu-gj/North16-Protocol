# Python CLI

0.14.0的initialize、camera/annotation extract、segmentation generate/batch/export及annotation export/import-package默认不计算或验证文件SHA，无需新增参数。--dry-run保留大小、来源身份、抽帧配置和磁盘容量检查。同名目标文件仍检查实际内容冲突。旧SHA记录只保留为历史信息。

在protocol目录使用`python cli.py <命令>`，与`python -m north16 <命令>`共用包内CLI，不重复实现业务逻辑。脚本根据自身位置读取src，不依赖终端当前目录。需要当前Python环境具备所用模块的依赖；本机已配置protocol/.venv。

```powershell
cd E:\Dataset\north16\protocol
.\.venv\Scripts\Activate.ps1
python cli.py --help
```

不激活环境也可以：

```powershell
.\.venv\Scripts\python.exe cli.py --help
```

## 初始化目录，不解码视频

```powershell
python cli.py initialize --raw E:\Dataset\north16\260902 --output E:\Dataset\north16\datasets_new
```

输出必须是新目录；初始化不生成图片、不创建masks。用`--segments`指定片段，不传则发现受支持布局下的片段。

## 推荐：独立标注工作区

以下命令均可将 `north16` 换成 `python cli.py` 或 `python -m north16`。初始化最终目录后，在工作区抽帧；最终目录仅在导入整包后获得图片与标签。

```powershell
north16 annotation initialize --dataset E:\data\datasets --output E:\data\annotation
north16 annotation extract --root E:\data\annotation --interval 5 --dry-run
north16 annotation extract --root E:\data\annotation --interval 5
north16 annotation gui --root E:\data\annotation
north16 annotation export --root E:\data\annotation --output E:\data\delivery
north16 import-package --root E:\data\datasets --package E:\data\delivery
```

`annotation initialize` 也接受 `--raw <原始根>`（与 `--dataset` 二选一），以及仅用于raw的 `--segments`。extract/export 均支持 `--sequences`、`--sensor visible|infrared`、`--cameras`；extract 的间隔、FFmpeg/FFprobe和dry-run与相机模块共用实现。

`segmentation generate/batch/estimate` 识别工作区角色。工作区 generate/batch 省略 `--output` 即就地保存JSON，显式指定时只允许工作区根目录。export 自动按工作区整包交付；普通datasets仍导出独立标签包。示例：

```powershell
north16 segmentation batch --root E:\data\annotation --sequence 20260902_044232 --workers 4 --profiles E:\data\profiles --no-estimate --limit 1
north16 annotation export --root E:\data\annotation --sensor visible --cameras back_04 --output E:\data\selected_delivery
```

已有标签拒绝重算覆盖。工作区全部选中图片（含未标注帧）随标签交付；停止/失败不发布半成品交付包，原工作区保留。命令帮助：`north16 annotation --help`。详细合同见 [ANNOTATION.md](ANNOTATION.md)。

## 兼容流程：相机抽帧与导出

```powershell
python cli.py camera extract --root E:\Dataset\north16\datasets_new
python cli.py camera extract --root E:\Dataset\north16\datasets_new --interval 5
python cli.py camera extract --root E:\Dataset\north16\datasets_new --interval 5 --dry-run
python cli.py camera extract --root E:\Dataset\north16\datasets_new --sensor visible --cameras back_04
python cli.py camera export --root E:\Dataset\north16\datasets_new --output E:\Dataset\north16\camera_export
```

全量和间隔抽帧二选一。`--interval` 单位秒、必须有限且大于0，可用0.5等小数；默认省略保存所有实际帧。按源PTS从首帧起选择，每次保留第一个与上次保留帧相差至少指定秒数的实际帧。不插帧、不保证各设备同步。图片名称和样本ID保留源解码帧序号（可能不连续）；meta记录原PTS/time_base、decoded_frame_index和saved_frame_index，info记录间隔与总解码/保存帧数。更改已有流的间隔会拒绝覆盖，应使用新初始化目录。历史build入口仍按原配置全量抽帧。

`--dry-run`只读预检：核验原视频、探测视频信息，输出所选片段/模态/镜头、预计保存帧数、保守容量和磁盘剩余空间。不解码图片、不创建运行日志或锁。预算按宽×高×3×帧数×1.2计算，是RGB24未压缩估算，实际PNG可能显著更小；视频文件大小不能直接用于估算PNG。容量报错会列出预计GiB、剩余GiB和待抽帧路数；不提供无检查强制写满磁盘的开关。可先缩小片段/镜头范围或增加时间间隔。

## 分割标注与JSON导出

```powershell
python cli.py segmentation gui --root E:\Dataset\north16\datasets
python cli.py segmentation generate --root E:\Dataset\north16\datasets --sequence 20260902_044232 --camera back_04 --profile parameters.json --output E:\Dataset\north16\labels\batch_01 --limit 3
python cli.py segmentation export --root E:\Dataset\north16\datasets --output E:\Dataset\north16\labels_export
```

gui打开已有标注程序；generate按参数预标注，export收集已存在于数据集masks的JSON。结构化标签包保留`dataset/sequences/<片段>/<模态>/<镜头>/masks/*.json`，可以整包合并复制。

## 16路可见光分别估参、并行生成

默认处理指定片段中已抽帧的全部visible镜头，默认并发4路。`--limit`是每个镜头的帧数限制；省略则全部处理。先试跑时建议使用新标签包和`--limit 1`。

```powershell
python cli.py segmentation estimate --root E:\Dataset\north16\datasets --sequence 20260902_044232 --workers 4
python cli.py segmentation batch --root E:\Dataset\north16\datasets --sequence 20260902_044232 --workers 4 --output E:\Dataset\north16\labels\parallel_test --limit 1
```

`--profiles <目录>`从`<camera>.json`读取每镜头基础参数；没有提供的镜头从默认参数开始，并记录地平线未确认。`--no-estimate`直接使用这些参数；`--auto-horizon`主动尝试地平线候选，默认保留各镜头基础线。详见[MULTICAMERA.md](MULTICAMERA.md)。

## 合并数据包

```powershell
python cli.py import-package --root E:\Dataset\north16\datasets --package E:\Dataset\north16\labels\batch_01
```

## 帮助与环境检查

```powershell
python cli.py --version
python cli.py doctor
python cli.py initialize --help
python cli.py camera --help
python cli.py segmentation --help
python cli.py import-package --help
```

`initialize`才是新的纯目录初始化；历史`init`仍用于创建配置项目，`build`保留旧整体构建流程。各模块规则见[MODULES.md](MODULES.md)。Python API与Dataset类保持可用。


## 抽帧进度（0.13.0）

`north16 annotation extract` 与 `north16 camera extract` 默认显示命令行进度，无需额外参数：预检当前镜头、镜头序号/总路数、源视频解码帧数/预计总帧数、已选择输出帧数、图片校验与元信息生成进度、提交与复用状态。

```powershell
north16 annotation extract --root E:\data\annotation --interval 5
# 自动化脚本需要关闭进度时：
north16 annotation extract --root E:\data\annotation --interval 5 --no-progress
```

终端中使用原行刷新的进度条；重定向日志时使用节流后的分阶段记录。进度写入stderr，最终JSON报告仍写入stdout。`--dry-run`只预检、不显示抽帧进度。单视频百分比基于源解码帧数的估计值，不基于稀疏保存帧数；预计帧数不可用时显示计数。解码阶段最多显示99%，所有镜头校验、索引与提交成功后才显示整体100%。某镜头完成后显示其实际图片数。间隔抽帧也仍需解码源视频，进度中“已选输出”表示过滤器选中的帧，实际保存/校验数量以最终报告为准。失败不显示成功完成。

Python API可传 `CameraBuilder.extract(progress=callback)` 或 `AnnotationWorkspace.extract(progress=callback)`，callback接收阶段事件字典；不传时库调用保持安静。阶段包括preflight、stream_start、decode、verify、publish、stream_done、done、failed，镜头阶段包含sequence/sensor/camera及stream_index/streams；decode包含done/total/selected，verify包含done/total。
