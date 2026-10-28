# 0.11.0工具补充：工作区与完整交付

协议ID、类别、审核及评测要求保持不变。默认工具流程改为独立annotation抽帧/标注，完成后图片＋JSON＋meta以kind=annotation整包校验导入初始化好的datasets。规范见 [ANNOTATION.md](ANNOTATION.md)，配置见configs/protocol.yaml的annotation_workspace。自动标签仍是draft/unreviewed，完整交付不代表已人工审核或已认证同步。

# North16 总协议

协议 ID：`north16-seg-v0.1-draft`。文档修订：`design-v0.7`。日期：2026-10-23。状态：draft。

## 1. 范围与规范用语

本协议适用于由已登记适配器识别的采集数据，目标是生成统一数据目录，使不同日期和批次能够使用同一套标注、Dataset 和评测流程。任意输入是指受支持格式的任意批次；新格式必须新增或修订适配器，不能保证未知文件自动转换正确。

首版核心为 `SEG-VIS` 与 `SEG-IR`：分别在可见光、红外视频解码图像上进行 sky/water/ice/other 四类分割。船舶检测、冰雷达、导航雷达、SAR 和融合任务保留登记，达到各自证据门槛后开放。

“必须”是构建、校验和发布需要共同执行的约束；“建议”允许在有记录的情况下调整；“待验证”不得被默认值替代。模块目录、YAML 和模板均不代表其实现已完成。

## 2. 规范分工与一致性

| 文件 | 唯一负责的内容 |
| --- | --- |
| 本文件 | 范围、跨模块约束、状态、兼容和发布原则 |
| [BUILD.md](BUILD.md) | 阶段顺序、预处理、失败、恢复和增量更新 |
| [DATASET.md](DATASET.md) | 数据目录、样本身份与 Dataset 外部接口 |
| [METADATA.md](METADATA.md) | 字段类型、TXT/TSV 表结构和继承解析 |
| [TASKS.md](TASKS.md) | 标注语义、气象/光照判据、隔离分组和评测定义 |
| [PILOT.md](PILOT.md) | 首次三个片段的输入、范围和验收 |
| [../configs/protocol.yaml](../configs/protocol.yaml) | 上述规则中可配置、可机器检查的值 |

YAML 中的枚举、类别 ID、schema 和阈值是程序加载的参数来源；字段含义及科学规则由对应文档定义。模板从相同 schema 生成或校验，不另维护一套标签常量。发现 YAML、模板、文档不一致时，校验必须失败，修复一致性后再处理数据，不能由程序静默选择一份。

旧的根目录文档仅作为跳转入口，不继续维护第二套规范。审计报告是历史证据，不因协议修订而改写历史检查结果。

## 3. 输入、输出与身份

- 原始根目录只读；数据输出不得进入原始输入目录。发现时排除目标输出和重复根路径。
- 输出根目录为 `datasets/`，目录层次固定为 `sequences/<sequence>/<sensor>/<camera>/{images,masks,meta}`。
- sensor 仅用 `visible`、`infrared`；雷达、导航和 SAR 使用独立规定的目录。
- `sequence` 是源存储片段，`scene_id` 是经审核的物理评测场景，`group` 是用于 split 隔离的来源关联组。三者不能互相替代，一个 group 可含多个 scene。
- 全局样本 ID 必须稳定；同一来源重复导入复用已有身份。文件夹时间、SHA-256 或帧文件名均不能单独证明唯一物理观测。
- 数据集根、源资产、转换配置、标注和关联均必须可追溯。具体身份登记和冲突规则见 BUILD.md。

## 4. 必须共同遵守的规则

1. 四类标签固定为 sky=0、water=1、ice=2、other=3；ignore=255。other 是可辨认的其他实体，ignore 是无效或无法判断像素。
2. 保存实际解码帧，不补黑帧、不复制前帧，不通过固定 FPS 重采样伪造观测。图像保留原尺寸；训练增强和归一化为显式实验配置。
3. 原始时间原样保留。只有时区、时钟及帧日志映射通过验证后才赋值经认证的 UTC；否则为 unknown。
4. 时间关联与空间配准分别登记；相同帧名、镜头编号和同日 SAR 均不证明同步或共像素。
5. 天气和昼夜独立存储，允许 unknown。属性继承必须有审核范围和证据；不能仅凭时间相近复制跨设备属性。
6. 未标注样本 mask 路径留空，不生成全零标签；缺失传感器不补伪图像。缺失、损坏、无标签和有效负样本分别记录。
7. `samples.txt` 是经校验的派生读取快照；人工标注、属性及来源记录是其依据。Dataset 不反向改写这些记录。
8. 正式 split 按已核实的 scene/source group 隔离，多模态筛选发生在固定划分之后。试点不伪造 train/val/test。
9. 训练只读冻结快照，索引、图像、meta 和标签不能在加载期间变动。错误不静默跳过。
10. 未通过验收的融合、雷达/SAR 标签或导航语义不得进入对应正式任务；不阻断已满足条件的独立相机任务。

## 5. 状态必须分开记录

| 状态维度 | 值/约定 | 说明 |
| --- | --- | --- |
| 构建步骤 | pending / running / succeeded / failed / blocked / skipped | 写入 steps.txt；skipped 需原因 |
| 原资产处理 | discovered / inspected / extracted / quarantined / failed | 写入 sources.txt；多个阶段事件可分别保留 |
| 时间映射 | unresolved / verified / rejected | 与是否成功抽帧独立 |
| 空间关系 | unverified / registered / rejected / not_applicable | registered 需外参/变换与验证证据 |
| 天气/光照审核 | unreviewed / reviewed / adjudicated | 与类别 unknown 分开 |
| 分割标签 | unlabeled / draft / reviewed / adjudicated / frozen | 仅复核后的标签默认可用于训练 |
| 关联可用性 | candidate / verified / rejected | verified 的时间/空间门槛由具体任务决定 |
| 数据集 | working / frozen | 冻结后不得原位覆盖 |

某帧可以已抽取、未同步、未标注，同时天气已审核为 unknown。这些不是互斥的单一“完成状态”。

## 6. 质量门槛

| 门槛 | 通过条件 | 不通过时 |
| --- | --- | --- |
| 导入 | 原始格式可识别、路径无冲突、来源可登记、容量已评估 | 停止冲突资产/阶段，保留审计结果 |
| 标准观测 | 图像与 meta 可读、数量对账、PTS/异常和来源完整 | 隔离问题资产，不能假报完整 |
| 标注 | 标签尺寸/类别合法、证据范围和复核记录完整 | 返工；未标注池可以继续保留 |
| 同步/融合 | 所用观测时间、容差、覆盖和必要空间关系有依据 | 留在候选关联，不生成正式融合清单 |
| 训练 | 固定索引、合法标签状态、划分无来源冲突 | 不创建训练 Dataset |
| 发布 | 所有启用任务的 schema、split、gold、指标、许可、代码和校验和冻结 | 保持 working，不标记为 benchmark release |

模态时差、时间不确定度、配准误差、雷达年龄、SAR 窗口、双标一致性门槛尚待实测；启用相应阶段前必须有明确值与依据，不使用 null 启用正式任务。

## 7. 版本与变更

分别登记 `protocol_id`、`protocol_revision`、`layout_version`、各文件 `schema_version`、`dataset_version`、`label_version`、`split_version`、`association_version`、`converter_version`、`reader_version`、`evaluator_version`。未知值在工作集使用 unknown，正式发布使用明确版本或注明不适用。

本阶段协议尚未发布，继续使用 draft ID，文档修订递增并写入 CHANGELOG.md。正式发布后，类别含义、布局/字段类型或评分规则变化必须增加协议版本；数据追加、标签修订、split 更新分别增加对应版本。新 reader 必须声明支持的 schema，未知 schema 明确拒绝；不能因为协议 ID 同名就假定所有文件兼容。

实现更新：新包已支持显式片段构建、原件保留、相机索引和无 split 的试点读取。Dataset 只验证已支持的相机分割合同，不解释 YAML 全部规则、不认证真实场景独立性；同步、标注和发布门槛仍需独立验收。实现边界见 EXECUTION.md。
# 0.6.0 模块化执行合同 — 2026-10-27

新的执行与目录合同见[MODULES.md](MODULES.md)，以configs/protocol.yaml的modules配置为准。initialize只登记资产和创建相机images/meta空目录，不解码、不创建masks；camera独立抽帧；segmentation包含原调参标注程序，默认导出同目录树masks/*.json。结果包中dataset的内容可整体合并，新Dataset直接识别JSON；原图和正式划分不自动改写。既有annotations工作区、PNG和旧build入口仅作兼容，以下历史描述与新合同冲突时使用本条及MODULES.md。
