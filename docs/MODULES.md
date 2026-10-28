# 0.11.0：独立标注模块

新增 `annotation/` 管理独立工作区、抽帧和图片＋标签交付；`AnnotationBuilder` 复用 segmentation 就地保存JSON，GUI按工作区角色路由。相机模块维护images/meta/frames；分割模块维护masks；packages负责完整性与冲突校验。初始化不解码、不创建masks。当前推荐目录与模块职责见 [ANNOTATION.md](ANNOTATION.md)，步骤见 [WORKFLOW.md](WORKFLOW.md)。下文为仍兼容的历史数据集内抽帧/外置标签包流程。

# North16 0.9.0：初始化、相机、分割

所有示例也可用`python cli.py <命令>`运行，见[Python CLI](CLI.md)。本机解释器为protocol/.venv/Scripts/python.exe；包内命令与Python脚本共用实现。

日期：2026-10-27。新工作流为初始化 → 独立抽帧 → 调参标注 → 导出JSON标签包 → 整体合并 → Dataset读取。

## 1. 结构化目录初始化

```powershell
north16 initialize --raw E:\Dataset\north16\260902 --output E:\Dataset\north16\datasets_new
```

输出必须是新目录，不能覆盖现有datasets。默认发现原始根下符合`YYYY_MM_DD_HH_MM_SS_data`的片段；也可用`--segments <片段1> <片段2>`指定范围。当前适配器支持既有north16采集布局，其他布局需增加适配器，不声称任意视频布局都能自动识别。

初始化只读取文件身份、大小、SHA256和目录信息，既不调用FFmpeg/ffprobe，也不复制原始视频、不生成图片或标签。大目录计算校验值仍需要时间。原视频绝对路径写入sources.txt，后续抽帧时需可访问；移动原视频后应更新来源登记并重新核验，不能盲目改source_id。

```text
datasets_new/
  info.txt / protocol.txt / classes.txt
  sources.txt                           原始资产登记
  samples.txt                           初始化时仅表头；相机汇总缓存
  sequences/<片段>/
    info.txt
    visible/<镜头>/
      info.txt                          decode_status=pending
      images/                           空目录
      meta/                             空目录
    infrared/<镜头>/
      info.txt
      images/
      meta/
  sync/info.txt                         未认证同步
  logs/initialization.txt
```

不创建masks、detections或标注工程。其他传感器仅登记原始资产，本版不处理冰雷达、导航雷达或SAR。

## 2. 相机模块

```powershell
north16 camera extract --root E:\Dataset\north16\datasets_new
north16 camera extract --root E:\Dataset\north16\datasets_new --interval 5
north16 camera extract --root E:\Dataset\north16\datasets_new --sensor visible --cameras back_04
```

可另指定`--sequences`、`--ffmpeg`、`--ffprobe`。默认保留所有实际可解码帧；也可用`--interval <秒>`按源PTS稀疏抽帧，保留首帧，随后每次选与上一保留帧相差至少指定秒数的第一个实际帧。支持正小数，不插帧、不增强、不推定认证UTC。保留原生尺寸、源解码帧号、PTS和time_base，稀疏文件名可不连续。源视频仍需解码，主要节省PNG存储和后续标注成本。原始数据校验、磁盘预算和流身份检查通过后才解码。每流先在临时目录完成，保留初始化占位信息后提交；完整流支持相同参数校验后复用，更改间隔会报冲突，中断产生的partial目录保留用于诊断。

稀疏流info记录frame_selection=minimum_pts_interval、sampling_interval_s、source_decoded_frame_count和saved_frame_count；兼容字段decoded_frame_count仍代表保存观测数。meta的decoded_frame_index为源解码帧号，新增saved_frame_index为本次保存序号。原始PTS缺失或倒退时拒绝提交稀疏流。相机包、分割JSON、GUI和Dataset按frames索引读取稀疏图像；不依赖连续文件名。各镜头独立选择，不能据此认证同步。历史build入口全量行为不变。

```text
visible/back_04/
  images/f000000.png
  meta/f000000.txt
  frames.txt
  info.txt
```

抽帧完成仍无masks。相机数据可整包交付给由同一来源身份初始化的另一目录：

```powershell
north16 camera export --root <已抽帧数据集> --output <新的相机包目录>
```

包的`dataset/sequences/...`保留完整相对路径，只包含相机info、frames、images、meta，不带根samples.txt，不覆盖其他任务输出。旧0.5及之前的数据集仍可camera export；旧构建的抽帧复现继续使用旧build入口。

## 3. 分割模块和标注界面

0.9.0默认地平线忽略半宽为1.00%，加载旧配置时保留其值。支持所有visible镜头的首/中/末三帧并行验证，4×4按时刻总览与逐镜头三帧并排，见[MULTICAMERA.md](MULTICAMERA.md)。

0.8.0增加4×4结果总览、独立调试、仅导出勾选镜头；0.7.0已支持当前片段各路可见光独立估参与并行生成，默认并发4路、最高16路。入口、抽样一致性规则和参数记录见[MULTICAMERA.md](MULTICAMERA.md)。

```powershell
north16 segmentation gui --root E:\Dataset\north16\datasets
```

原`north16 gui --dataset ...`入口与启动器继续可用。地平线、冰水阈值、自动估计、全冰/全水、缩放和平移、像素读数沿用原工具。当前GrabCut仅适配visible；infrared保持浏览，不在本次改动中自动套用算法。

结构化模式下，保存当前图片或整个镜头会直接生成JSON标签包，不再先生成drafts、projects、corrected。默认包位置为数据集相邻的`labels/<批次>`；可用“选择输出位置”选择新的包父目录。单张保存或当前文件夹处理在同一窗口内可累计到同一包；勾选批量导出若遇到已有标签，则自动创建新批次，确保只交付本次选中的镜头；每个同名JSON若已存在，报错保护人工修改。新建包可重新计算。参数随标签JSON保存，单独保存配置时位于包根parameters下。

```text
labels/<批次>/
  package.txt / files.txt / README.txt / last_run.json
  parameters/...                        手动保存或多镜头批处理时生成
  dataset/
    sequences/
      20260902_044232/
        visible/
          front_01/masks/f000000.json
          back_04/masks/f000000.json
      20260902_044732/
        visible/back_04/masks/f000000.json
```

**所有标注文件就在masks，默认.json。** 不要求先创建特定编辑软件工程，也不生成独立color/overlay/逐帧审核TXT。界面叠加图用于预览，正式标签JSON内保存polygon/rectangle等形状、原生尺寸、样本ID、源图哈希、算法参数和标签状态。

JSON沿用已有可编辑多边形结构，`imagePath=../images/<原帧名>.png`，合并到数据集后直接关联原图。标签包本身不重复携带图片；合并前仅有包内标签的编辑器无法解析该相对图片路径，应先合并到拥有images的工作数据集。未覆盖像素为ignore=255；孔洞与碎冰不删除，导出前逐像素验证JSON栅格化结果与原掩码相同。

普通图片文件夹模式同样默认生成`masks/*.json`，额外复制原图到同级images以便独立编辑，但不冒充具有全局身份的结构化标签包。历史PNG草稿和旧编辑工程保留兼容命令，不迁移或删除旧结果。

命令行等价操作：

```powershell
north16 segmentation generate --root <datasets> --sequence 20260902_044232 --camera back_04 --profile <参数.json> --output <标签包> --limit 3
north16 segmentation export --root <datasets> --output <新标签包>
```

generate用于算法预标注，export仅收集数据集masks里已有的规范JSON，适合人工修改后的再次交付。手工编辑时保留north16身份与来源信息；普通外部JSON缺失身份不能直接当本协议标签。

## 4. 整包合并与直接读取

直接把包中dataset的内容整体合并到数据集根即可；不要把dataset这一层作为子目录放进去。手动合并时遇到已有同名标签应先保留旧版，避免覆盖修改。推荐用可校验的入口：

```powershell
north16 import-package --root <datasets> --package <标签包或相机包>
```

导入前校验包清单、哈希、目录、协议、原图身份、尺寸和已有文件冲突，内容相同跳过，不同则拒绝。相机包仅允许替换同来源pending流的info声明。复制中途IO失败可能留下已复制子集；包内文件不会被删除，修复问题后可重复导入完成。新数据集从各流frames读取相机观测，根samples是可重建汇总；旧数据集继续读原samples，但masks中的JSON标签优先，不需要重写总表。

```python
from north16.datasets import SegmentationDataset

dataset = SegmentationDataset(
    root=r"E:\Dataset\north16\datasets",
    split=None,
    sequences=["20260902_044232"],
    sensor="visible",
    labeled_only=True,                    # 显式只取已有标签的图片
    allowed_label_statuses=["draft"],     # 仅用于检查/试标；正式默认要求审核标签
)
sample = dataset[0]                       # image: float32[C,H,W]; mask: int64[H,W]
```

`North16SegDataset`名称保留兼容；旧单通道PNG标签仍可读取。JSON按原图尺寸动态栅格化，不把伪彩色当类别。默认仅接受reviewed/adjudicated/frozen；checked=true不自动晋升，非draft需记录reviewer与reviewed_at。正式划分继续要求独立group与splits，复制标签不会自动生成划分。

仅浏览/推理相机图像可使用`from north16.datasets import CameraDataset`和`CameraDataset(root)`，默认读取已抽帧的两种模态，不读取标签，不解码视频。

## 5. 代码模块

```text
src/north16/
  layout/          DatasetInitializer；paths定义相机/标签相对路径
  camera/          CameraBuilder；抽帧、相机包与流索引
  segmentation/    SegmentationBuilder；masks JSON生成、验证与栅格化
  packages/        数据包清单、导出与合并导入
  datasets/        SegmentationDataset / North16SegDataset
  gui/             原标注程序，调用分割模块
  annotations/     现有算法、参数和旧工作流兼容
```

旧`init`用于生成批次配置项目，旧`build`是包含抽帧的兼容入口；它们不等于新的纯目录初始化`initialize`。已有数据集不会被重新初始化。本版不生成融合标签、不新增检测/雷达/SAR处理，不改变配准工作台。
