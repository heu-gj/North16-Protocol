# 0.6.0 模块结构

当前规范以[初始化、相机、分割模块](MODULES.md)为准：初始化不抽帧、不创建masks；相机模块独立处理；分割默认导出同结构masks/*.json；整包合并后Dataset直接读取。下方保留旧版接口与历史实现说明，仅用于兼容和追溯。

# 代码模块与实施合同

本文件规定模块边界和完整目标。实现已推进至相机试点构建与读取，范围见 EXECUTION.md；标注/评测等仍为计划。项目根目录为 `E:/Dataset/north16/protocol/`，Python 包使用 `src/north16/`。

## 1. 目标目录

```text
protocol/
  README.md
  docs/{PROTOCOL,BUILD,DATASET,METADATA,TASKS,PILOT,CHANGELOG,ARCHITECTURE}.md
  configs/{protocol,import.example,pilot}.yaml
  configs/adapters/north16_capture_v1.yaml
  templates/txt/
  src/north16/
    common/        schema、TXT/TSV、配置、路径、身份、校验和
    adapters/      原格式发现、探测和字段映射
    preprocess/    视频解码、时钟、雷达/SAR、关联、索引与分组
    annotations/   样本选择、属性审核、标签导入与复核
    datasets/      PyTorch 读取类和联合变换
    validation/    目录、时间、标签、独立性和发布检查
    evaluation/    预测校验、固定指标、条件与场景汇总
    pipeline/      阶段编排、恢复、运行记录、发布快照
  tests/           按合同组织的单元/集成/回归测试
```

已加入实际业务模块、pyproject.toml 和 run.py 入口；依赖环境精确版本记录在运行 resolved.yaml/实现说明，完整跨平台依赖锁后续补充。配置不携带密钥，模块不在 import 时扫描数据或创建目录。

## 2. 模块输入输出

| 模块 | 输入 | 输出/责任 | 不负责 |
| --- | --- | --- | --- |
| common | protocol YAML、TXT、来源登记 | 类型化配置/记录；路径与版本检查；稳定身份 | 不解码视频、不含模型 |
| adapters | 原始根目录、适配器参数 | SourceAsset/StreamInfo/RawRecord 清单及问题 | 不猜时区、不改统一类表、不写标签 |
| preprocess | 已登记资产、变换配置、时钟证据 | Observation、派生记录、关联表、解析后 samples 与分组提案 | 不覆盖人工字段、不训练 |
| annotations | 候选清单、原图、人工证据/工程 | 审核后的条件记录、mask/检测标注、修订历史 | 不改变源像素或擅自同步 |
| datasets | 冻结索引、图像/meta/标签、筛选与显式变换 | 固定 tensor 与身份/场景信息 | 不构建、不修复数据、不写 split |
| validation | 产物、规则、声明的检查范围 | ValidationReport：通过/失败/未检查及证据 | 不通过偷偷删样本“修复” |
| evaluation | 冻结 gold/场景映射、预测、评测配置 | 标准指标、覆盖/空类/条件统计、版本报告 | 不调测试阈值、不改 gold |
| pipeline | 任务配置、阶段及已有运行状态 | BuildResult、日志、可恢复产物、冻结快照 | 不重新实现解码/标签语义/指标 |

## 3. 公共数据合同（待实现）

| 记录 | 必要内容 |
| --- | --- |
| ProtocolConfig | 协议/schema、类表、属性枚举、启用任务、门槛与版本 |
| BuildConfig | 输入根、source namespace/session、输出、精确范围、阶段、恢复策略 |
| SourceAsset | source_id、raw_root_id、源相对路径、哈希/大小、流与来源会话 |
| Observation | 稳定 id、source_id、帧/扫描身份、image/meta、PTS、原始/认证时间状态 |
| Association | 两端 ID、关系类型、时间差/不确定度、空间状态、证据和版本 |
| AnnotationRecord | sample_id、task、label_status、版本、证据、复核人和修订 |
| ValidationReport | 检查 ID、范围、结果、严重性、关联资产、原因 |
| BuildResult | run_id、阶段结果、产物路径、失败/跳过数、配置摘要 |

记录可用 dataclass 实现，先保持简单明确的静态模块，不引入复杂插件框架。适配器按 adapter_id 注册受支持实现；新格式复用统一模型。

## 4. 依赖方向

common 为底层，业务模块只通过其 schema 和配置交换数据。adapters、preprocess、annotations、datasets、validation、evaluation 不反向依赖 pipeline；pipeline 调用这些模块编排阶段。datasets 不依赖 adapters、FFmpeg 或 pipeline，训练环境只装其需要的读取依赖。evaluation 不调用构建器；validation 不在 Dataset 里重复完整审计。

FFmpeg、雷达地理处理、SAR 处理和标注工具分别为可选依赖，按启用任务加载。统一入口只解析参数和调用 pipeline，不能堆积业务逻辑。

## 5. Dataset 类族

| 类/工具 | 首版范围 |
| --- | --- |
| North16SegDataset | 核心：visible/infrared 四类，固定 split；补无 split 的显式片段检查模式 |
| SegResize / 联合变换 | 图像插值与 mask 最近邻；几何一致 |
| North16DetDataset | 后续：COCO 检测与独立负样本/ignore 合同 |
| North16FusionDataset | 后续：指定 reference、已验证关联、缺失模态和覆盖 |

共享 manifest/schema/路径读取，不为天气或模态建立独立子类。雷达/SAR 的原始位深、通道、NoData、坐标和标签不适配时增加专用 reader，不硬套相机分割类。

## 6. 原型迁移

原型位于 `E:/Code/sar/north16_benchmark/`：dataset.py、audit_raw.py 和 tests/test_dataset.py。后续将 reader 实现迁至 datasets/segmentation.py，联合变换迁至 datasets/transforms.py，TXT/路径迁至 common/；审计工具拆入 adapters/preprocess/validation，复用字段与检查。

迁移时在旧路径保留薄的兼容导出层，使已有 `north16_benchmark.dataset` 导入继续工作；新包统一公开 north16.datasets。迁移必须先保持当前接口、结果和 13 项回归测试，再增加试点接口。相机 reader 已迁至新包，可从 north16.datasets 导入；旧原型代码仍保留，尚未替换为薄兼容层。

## 7. 测试与实施顺序

先实现 schema/配置/TXT → 发现与探测 → 相机抽帧/meta → 属性解析/索引 → 校验与试点 Dataset → 标注导入/时间关联 → 分组/快照 → 官方评测 → 其他任务。

必测行为包括非法路径/版本拒绝、帧数和映射异常保留、身份稳定、同名冲突、恢复不覆盖人工记录、标签几何/值域、跨模态泄漏、ignore 正确处理、空类汇总及参考指标。测试使用小型合成资产和明确许可的夹具，不默认扫描完整原始数据。

## 当前实现清单

已实现 common/files.py、adapters/capture.py、preprocess/{camera,auxiliary,index}.py、pipeline/build.py、datasets/segmentation.py、validation/pilot.py。其余列出的文件为计划。实际命令与限制见 EXECUTION.md。
# 数据集标注界面（0.4.0增补）

`annotations/dataset_workspace.py`独立读取协议、类别、样本索引与帧回执，管理可见光流、身份校验及protocol指定输出路径，不依赖Qt或PyTorch。`gui/window.py`负责数据集/片段/镜头选择与交互，通过该模块调用`annotations/workspace.py`的共享分割和草稿保存。普通图片目录仍使用独立文件夹模式。

输出规则集中在`configs/protocol.yaml:annotation_workspace`，数据集模式禁止临时任意重定向到正式masks。草稿批次包含全局样本ID与本批samples.txt，路径相对数据集根目录；它是待审核标注登记，不会替代正式索引。X-AnyLabeling清单保留相同ID，后续审核/发布模块据此登记。
