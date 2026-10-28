# 多镜头独立估参与并行预标注（0.9.0）

0.12.0参数复用：默认两点直线。调试后点击“保存参数及验证记录”会同时复制参数快照；换镜头点击“粘贴到当前镜头”。也可将当前参数应用到本片段全部可见光镜头，包括未勾选镜头；各路参数副本独立。复制只在本窗口有效，跨次启动用JSON保存/加载。操作详情见[GUI.md](GUI.md)。


处理范围为一个明确选择的片段、该片段索引中实际存在的全部visible镜头（North16为front_01–08和back_01–08）。不跨片段混用配置，不把可见光亮度分割套用到infrared。相机抽帧模块仍独立运行，本功能读取已生成的结构化图片。

## 界面

1. 打开north16数据集，选择片段和visible，切换“16路总览 / 勾选导出”。4×4显示全部已登记可见光镜头的结果；首次进入自动预览，后续可点击“刷新全部预览”。
2. 点击“估参并预览全部”，各路独立估参并展示结果；右侧也有同一入口。保持默认地平线选项时，分别保留每镜头自己的基础线，未手调的镜头仍为未经确认的默认线。
3. 点击图像或“调试”进入单镜头页面。调整地平线、阈值、全冰/全水模式后运行当前图片预览，该路缩略图同步更新；返回总览可同时比较其他路。参数变化时旧预览明确标为待刷新，不自动当作当前结果。
4. 在每张卡片勾选要导出的镜头，支持全选/全不选；未勾选的镜头仍能预览和调试。勾选状态在当前窗口按数据集与片段分别记忆。
5. 点击“导出勾选镜头的标签”。默认使用各路已调试的参数，不重新估计。可主动勾选“生成前各镜头独立自动估参”，其估计可能替换亮度阈值；因此调试确认后推荐保持不勾选。
6. 并发数默认4，最高16，适用于估参、总览预览和批量生成。每个线程处理一个镜头，镜头内逐帧生成。选择性导出处理每个勾选镜头的整个片段，并非仅保存缩略图当前帧。
7. “停止任务”在正在计算的图片结束后检查取消，保留已经完成的标签；总览预览本身只读，不写标签或数据集目录。

预览帧按各路帧序号读取，短流使用最后一帧；卡片显示实际帧名。相同帧序号不保证时间同步。原图、叠加结果和彩色掩码可统一切换，点击卡片会打开同一预览帧。为了控制内存，仅保留当前数据集当前片段的预览缓存，切换片段重建；各镜头参数和勾选状态仍独立保留。

详见[GUI.md](GUI.md)。

## 全部镜头首 / 中 / 末验证

点击总览“验证首 / 中 / 末”或右侧“验证16路：开头 / 中间 / 末尾”。默认4线程分别处理各镜头的首帧、`len(images)//2`中帧、末帧，使用其当前独立配置，不修改阈值，不受导出勾选影响。16路正常片段共48张不同帧。仅有1–2张时按实际位置映射并去重计算，三个位置仍明确显示实际帧名。

弹出窗口可在4×4总览中切换开头/中间/末尾，或选“三帧并排（逐镜头）”滚动对比。同样支持原图、叠加和彩色掩码。每帧核验来源回执，保存图像和掩码哈希；内存只保留缩略图与回执，不保留48张原尺寸掩码，也不输出标签文件。单帧失败不阻塞其他帧，取消后显示完成子集与未处理位置。

这是人工检查工具，不是正式评测或审核。继续调参时对应镜头的结果标记为旧参数，需要重新验证。新默认地平线忽略半宽为1.00%，旧配置保留显式数值。

## 估计规则与适用范围

三个亮度阈值使用已有Otsu分组和分位数方法，各样本都从该镜头基础参数开始。必须有严格多数抽样图支持分组，且三个阈值各自跨帧极差不超过35灰度级，才取各阈值中位数；否则保留基础阈值并记录原因。阈值与统计来源写入逐镜头估计记录。少于3张时记录抽样不足。

主动估计地平线时，必须有严格多数候选通过已有单帧检查，控制点纵坐标跨帧差异不超过图高3.5%，才取中位候选。随后用最终的共同地平线重新估计冰水阈值，避免保留旧地平线却使用另一条候选线下的亮度。未通过则保留基础线。

上述阈值是当前方法版本的启发式一致性门槛，不是准确率、置信概率或标定结果。图像中的亮暗组不等于真实冰水；不会自动识别薄冰、other或全冰/全水。全冰/全水仍由操作者按镜头及适用片段明确指定。所有输出为draft/unreviewed，仍需人工修正。

## CLI

```powershell
cd E:\Dataset\north16\protocol

# 只估参并输出JSON汇总，不生成标签
.\.venv\Scripts\python.exe cli.py segmentation estimate --root E:\Dataset\north16\datasets --sequence 20260902_044232 --workers 4

# 测试：每镜头一张，另存新包
.\.venv\Scripts\python.exe cli.py segmentation batch --root E:\Dataset\north16\datasets --sequence 20260902_044232 --workers 4 --limit 1 --output E:\Dataset\north16\labels\parallel_test

# 完整片段：去掉limit，必须使用与测试分开的新包
.\.venv\Scripts\python.exe cli.py segmentation batch --root E:\Dataset\north16\datasets --sequence 20260902_044232 --workers 4 --output E:\Dataset\north16\labels\parallel_full
```

可用`--camera back_04`缩小范围。`--profiles <目录>`读取该目录下的`front_01.json`、`back_04.json`等独立基础配置；文件内容是原参数JSON。未提供配置的镜头有默认地平线未确认提示。`--no-estimate`跳过自动估参；`--auto-horizon`主动尝试地平线候选。

默认并发4路是为了控制内存、JSON多边形转换和磁盘写入压力，实际加速取决于机器与画面复杂度，不承诺16倍。并行分割每次OpenCV调用使用1个内部线程，避免16路各自再开4个线程；单镜头旧接口保留4个内部线程。包内分割调用统一协调OpenCV全局线程设置，在调用结束后恢复。不要在运行期间从外部代码另行修改OpenCV线程设置。

## 输出和冲突

```text
labels/<批次>/
  package.txt / files.txt / README.txt
  last_run.json                           最近一次任务汇总
  run_<任务编号>.json                      多镜头任务历史
  parameters/<片段>/visible/
    front_01_<任务编号>.json               可再次加载的参数
    front_01_<任务编号>.estimation.json    启用估参时的依据
    ...
  dataset/sequences/<片段>/visible/
    front_01/masks/f000000.json
    ...
    back_08/masks/f000000.json
```

自动估参生成的参数与来源也保存在各标签的north16字段。参数记录位于包外层，不混入Dataset标签目录。可以将整个dataset目录的内容合并到数据集根目录，或用`python cli.py import-package --root <数据集> --package <标签包>`校验合并。

GUI选择性批量导出若发现当前包已包含标签，会自动使用同一父目录的新批次，确保新包只包含本次选中的镜头；以前的包不删除。单张保存与CLI仍遵守原有同包追加/冲突规则。

同一个包的写入锁只允许一个生成任务。所有待输出标签先进行冲突预检，任一同名JSON存在就拒绝本次请求，不覆盖、不自动跳过。若在此前保存过单张或单路标签，请选择新的输出包后处理整片段；中断后也可选择新包重跑。某个镜头估参或来源校验失败会记录错误，其余镜头继续；只有协调线程在工作线程结束后刷新files.txt与last_run.json。

## Python接口与代码模块

```python
from north16.segmentation import SegmentationBuilder

builder = SegmentationBuilder(r"E:\Dataset\north16\datasets")
estimates = builder.estimate_cameras("20260902_044232", workers=4)
report = builder.generate_cameras(
    "20260902_044232", r"E:\Dataset\north16\labels\python_batch",
    workers=4, estimate=True, keep_horizon=True,
)
```

两个接口均支持`profiles={"back_04": profile, ...}`、`cameras=[...]`、`limit`、`cancel=threading.Event()`和`progress(done,total,name)`。生成进度按处理完的图片累计，回调在锁内调用；耗时回调会拖慢工作线程。`estimate_cameras`的progress按镜头累计。报告包含逐镜头状态、失败原因、成功标签、未处理数量与实际并发数。

- `segmentation/builder.py`：共享协议检查、输出包锁、单镜头JSON生成。
- `segmentation/batch.py`：多帧一致性估参、线程池、聚合进度与统一清单。
- `annotations/runtime.py`：协调OpenCV内部线程配置。
- `gui/window.py`：数据集镜头选择、独立参数回填、预览缓存和选择性导出。
- `gui/camera_overview.py`：4×4总览卡片、勾选和显示切换。
- `gui/overview_jobs.py`：只读并行预览、三帧验证与缩略图生成，不依赖Qt对象。
- `gui/sample_validation.py`：16路首/中/末验证布局、显示切换与过期提示。

协议ID、类别表、JSON目录和Dataset读取方式兼容0.6.0。
