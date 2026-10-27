# 0.6.0 数据集与读取

当前规范以[初始化、相机、分割模块](MODULES.md)为准：初始化不抽帧、不创建masks；相机模块独立处理；分割默认导出同结构masks/*.json；整包合并后Dataset直接读取。下方保留旧版接口与历史实现说明，仅用于兼容和追溯。

# North16-Seg：目录、Protocol 与 PyTorch Dataset

数据集名称用 **North16**，海冰分割任务用 **North16-Seg**，对应类名 `North16SegDataset`。当前 protocol ID 为 `north16-seg-v0.1-draft`；完成数据与评测冻结后再发布正式版本。文件名用小写英文加下划线，目录只用已有含义清楚的词。

## 标准目录

```text
datasets/
  info.txt                         数据集/标签/划分版本与来源说明
  classes.txt                      sky=0 water=1 ice=2 other=3 ignore=255
  protocol.txt                     机器可读协议入口
  samples.txt                      总样本表，制表符分列
  splits/                          正式划分后生成，试点不生成
    train.txt                      每行一个样本 ID
    val.txt
    test.txt
    scenes.txt                     TSV：id、scene_id、group
  annotations/                     有人工标注时生成
    README.txt / index.txt         工作区说明与自动批次清单
    reviews.txt                    审核与证据登记
    history.txt                    修订记录
    drafts/<片段>/visible/<镜头>/<批次>/  GUI预标注与本批samples.txt
    profiles/<片段>/visible/<镜头>/<哈希>/  GUI保存的参数及依据
    projects/                      原始标注工程
    corrected/<片段>/<模态>/<镜头>/<批次>/  人工修正回读，仍待审核
    archive/                       历史试验与迁移映射，不作为正式训练标签
    history/                       历史资产，公开版不得暴露测试 gold
  sequences/20260902_044232/
    info.txt                       采集批次、来源片段、共同天气/光照
    visible/front_01/
      info.txt                     流的设备、原视频、尺寸和解码统计
      images/f000000.png
      masks/f000000.png
      meta/f000000.txt
      frames.txt                   不可变帧来源与图像校验回执
      det.json                     可选：启用检测任务后生成
    infrared/front_01/...                相同结构，保持实际原始分辨率
    source/time.txt                原始时间日志，不自动分配到帧
    ice_radar/                     有对应资产时生成
      info.txt
      records.txt                  接收记录引用 scan，不重复计数
      source/                      原始 KML 和 index
      metadata_checks.txt          严格 XML 检查与异常
      scans/<scan_id>/
        image.tif                  保留原始数值/地理信息
        source.kml                 原件，存在时保存
        info.txt
      masks/<scan_id>.png           可选：专家确认后生成
    nav/
      info.txt
      source.txt                   原始文本或带校验的来源登记
      records.txt                  解析记录及状态
    nav_radar/                     仅有实际图像时生成
      info.txt
      records.txt
      scans/<scan_id>/...
      det.json                     可选
  sar/<product_id>/
    info.txt                       卫星、过境、覆盖、产品及处理信息
    source/...
    processed/...                  可选：产品专用派生
    masks/...                      可选：独立 SAR 标签
    det.json                       可选
  sync/
    info.txt
    pairs.txt                      关联不代表已同步或配准
    sar_links.txt
    clocks/<clock_model_id>/info.txt       有时钟证据时生成
    calibrations/<calibration_id>/info.txt 有空间标定时生成
  logs/<run_id>/
    info.txt
    resolved.yaml                  完整运行配置快照
    sources.txt
    steps.txt
    errors.txt
    checks.txt
    checksums.txt
    candidates.txt                 仅执行候选选择时生成
```

`sequence` 是原始存储片段，不等于独立物理场景；防泄漏使用另外登记的 `group`。同一航次/会话等信息写入 info.txt，不再为它增加目录层级。`20260902_044232` 是源数据时间标签，不保证为 UTC；跨批次重名时由来源登记增加固定区分后缀，不按输入遍历次序重新编号。

原始 `front_visible/lens_01.mp4` 映射到 `visible/front_01`，`front_infrared/lens_01.mp4` 映射到 `infrared/front_01`；front/back 保留方位含义。仅名称对应不能证明两个传感器已配准。原始索引映射保留在 meta/source 记录中。

工作集同一时刻只使用一套已声明标签/划分版本。公开发布时输出相同目录结构的独立、不可覆盖版本，而不是在每层目录加版本号。隐私测试 gold 不随公开数据导出；空 mask 不代表负样本。

## samples.txt 与元信息

samples.txt 为 UTF-8 TSV，必须有以下表头；`mask` 未标注或测试真值隐藏时留空，其余必填身份和路径字段不能空：

```text
id  sequence  sensor  camera  image  mask  meta  weather  illumination  label_status  group
```

上面的空格用于展示，实际分隔符必须是 TAB。只登记 可见光/红外 分割样本；雷达、SAR 和检测后续有各自任务清单，不混进这个 loader 的 camera manifest。

| 字段 | 约定 |
| --- | --- |
| id | 全局唯一且稳定；例如 `n16_20260902_044232_visible_front_01_f000000`，源身份规则须处理冲突 |
| sequence | 原始片段 ID |
| sensor | `visible` 或 `infrared` |
| camera | `front_01`、`back_01` 等 |
| image / mask / meta | 相对于数据根目录的路径，统一 `/`，不能越界 |
| weather | `clear / cloudy_overcast / fog_precipitation / unknown` |
| illumination | `day / night / unknown`；晨昏原因保留在 meta |
| label_status | `unlabeled / draft / reviewed / adjudicated / frozen` |
| group | 物理场景及共享来源形成的隔离组；进入 split 的样本不允许 unknown |

info.txt 和 meta TXT 使用 `key=value`。共同天气/光照可在 sequence/info.txt 标注，经审核确认适用整个片段后才允许逐帧继承；逐帧覆盖优先。构建器须把属性解析为确定枚举或 unknown 写入 samples.txt，Dataset 不在训练时推断或修改天气。samples.txt 是当前版本的读取快照，修改属性后先重新校验和生成索引，再训练。

逐帧 meta 至少含 `id`，并保留源视频/帧号、原始日志候选、PTS/time_base、采集 UTC 与验证状态。时间未核实写 `unknown`，不按 f000000 推断绝对时间。Dataset 会核验 meta 的 id 并返回 capture_time_utc；完整元信息可用 `read_info(path)` 读取。

classes.txt 与 protocol.txt 模板位于 ../templates/txt/。未生成真实 images、samples 和 split 前，模板目录本身不能用于训练。

## 使用代码

使用当前项目 src 路径或安装项目后：

```python
from torch.utils.data import DataLoader
from north16.datasets import North16SegDataset, SegResize

dataset = North16SegDataset(
    root=r"E:\Dataset\north16\datasets",
    split="train",
    sensor="visible",                  # 改成 infrared 可读取红外
    joint_transform=SegResize((512, 768)),
)
loader = DataLoader(dataset, batch_size=4, shuffle=True, num_workers=0)
batch = next(iter(loader))
# batch["image"]: float32 [B,3,512,768]，范围 [0,1]
# batch["mask"]:  int64   [B,512,768]，值域 {0,1,2,3,255}
# 使用 CrossEntropyLoss(ignore_index=255)
```

`SegResize` 对图像用双线性插值，对 mask 用最近邻；原始数据保持原尺寸。自定义 joint_transform 必须同时变换 image/mask，输入输出为 `(PIL.Image, PIL.Image或None)`。加载器在变换前后检查 mask 值域和几何一致性。模型特定均值/标准差归一化需显式添加，不隐式套用。

条件子集：

```python
fog_test = North16SegDataset(
    root=r"E:\Dataset\north16\datasets",
    split="test", sensor="infrared",
    weather="fog_precipitation", illumination="night",
    require_mask=False,
    joint_transform=SegResize((512, 768)),
)
```

`require_mask=False` 不读取 GT 且不返回 mask，适合隐藏测试标签推理；需要本地有标签评测时使用默认 True。默认只接受 reviewed/adjudicated/frozen 标签，缺少标签会报错，不能静默剔除。试标训练如需 draft，必须显式修改 allowed_label_statuses，并保留实验设置。

可见光与红外 默认均返回三通道，保留视频图像显示表示；`infrared_channels=1` 显式转为单通道亮度，不能称为辐射测温。可以 `sensor=["visible", "infrared"]` 混合训练，但这不是配对融合；红外单通道与可见光三通道混合时需自行统一通道，原尺寸不同的 batch 需 joint resize 或自定义 collate。

返回字段：image、可选 mask、id、sequence、sensor、camera、group、weather、illumination、capture_time_utc、meta_path、protocol_id、original_size。original_size 为 `[H,W]`，便于把预测映射回原图评测。

## 校验范围与限制

已实现：protocol/classes 一致性、样本/分组的 split 冲突、同图异 ID 跨 split、路径越界、未知 ID、条件枚举、标注状态、mask 格式/值域/尺寸和 meta ID 检查。已加载 Dataset 不支持在训练中途修改工作目录；训练使用冻结快照。

不能仅靠 Dataset 证明物理场景独立、不同文件内容近重复、时间同步、标注正确或 SAR 不泄漏；这些由构建器/QC 和审核保证。未声明 split 的样本可保留在未标注池，但不会被本类自动加入训练。

代码目前支持 camera 可见光/红外 的四类分割。船舶检测 Dataset、配对融合 Dataset、雷达/SAR Dataset 和官方评测器尚未实现；显式片段相机导入已实现，通用发现尚待扩展。

验证命令：

```powershell
python -m unittest discover -s north16_benchmark/tests -v
```

依赖：Python 3.10+、PyTorch、NumPy、Pillow。测试使用临时合成图像，不修改原始数据。


## 试点读取（已实现）

新包位于 protocol/src/north16。暂不依赖全局安装，示例先将该 src 加入当前 Python 路径：

```python
import sys
sys.path.insert(0, r"E:\Dataset\north16\protocol\src")
from north16.datasets import North16SegDataset, SegResize

ds = North16SegDataset(
    root=r"E:\Dataset\north16\datasets",
    split=None,
    sequences=["20260902_044232", "20260902_044732", "20260902_045232"],
    sensor=["visible", "infrared"],
    require_mask=False,
    joint_transform=SegResize((256, 384)),
)
```

无 split 检查必须显式 sequences 且 require_mask=False；它不提供训练资格，不与正式 split 参数同时使用。正式训练仍要求审核标签、固定 split 和隔离组。混合模态是未配对样本，绝不证明同步。

原型包仍保留，不自动更改旧依赖。新包还未拆分所有公共 reader 辅助函数，检测/融合及真实场景资格仍需后续实现。reader 支持 north16_seg_v1，不能因此宣称已验证全部逐帧 schema 与真实时间。

完整目录是允许的资产布局，无数据时不必创建雷达/SAR/检测空目录。时钟与标定阶段未执行时写入日志状态；正式 scene 映射仍须审核冻结。
