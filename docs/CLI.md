# Python CLI

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

## 相机抽帧与导出

```powershell
python cli.py camera extract --root E:\Dataset\north16\datasets_new
python cli.py camera extract --root E:\Dataset\north16\datasets_new --interval 5
python cli.py camera extract --root E:\Dataset\north16\datasets_new --sensor visible --cameras back_04
python cli.py camera export --root E:\Dataset\north16\datasets_new --output E:\Dataset\north16\camera_export
```

全量和间隔抽帧二选一。`--interval` 单位秒、必须有限且大于0，可用0.5等小数；默认省略保存所有实际帧。按源PTS从首帧起选择，每次保留第一个与上次保留帧相差至少指定秒数的实际帧。不插帧、不保证各设备同步。图片名称和样本ID保留源解码帧序号（可能不连续）；meta记录原PTS/time_base、decoded_frame_index和saved_frame_index，info记录间隔与总解码/保存帧数。更改已有流的间隔会拒绝覆盖，应使用新初始化目录。历史build入口仍按原配置全量抽帧。

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
