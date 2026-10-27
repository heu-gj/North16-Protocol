# TXT 与索引规范

修订：design-v0.7。布局见 DATASET.md；任务语义见 TASKS.md。以下是计划的完整写入合同，现有 reader 只实现其相机分割读取子集。

## 1. 通用格式

元信息 TXT 使用 UTF-8、LF、key=value；按首个 = 切分，忽略空行与 # 整行注释，键不得重复。值不允许隐含换行；未知写 unknown，不用空字符串代替。路径使用 /。

表格 TXT 使用 UTF-8 TSV，首行唯一列名，不放说明性注释或占位样本行。字段内不得含原始 TAB/CR/LF，需保存此类原文时引用单独 source 文件。缺失表格数值/字符串统一 unknown；只有明确约定的 mask 路径允许为空。split TXT 是例外，每行一个样本 ID，允许空行与 # 注释。

YAML 未解决值为 null；写入 TXT 时为 unknown；inherit 仅允许工作集逐帧属性成组继承，不能出现在最终 samples。真假值统一 true/false，计数/索引为十进制非负整数，时间误差为非负数或 unknown。UTC 为带 Z 的 ISO8601，保存必要小数位；原始时间不改写。

路径相对 datasets 根，禁止绝对路径、反斜杠、冒号和 ..，符号链接解析后仍须位于根内。raw 原件路径由 raw_root_id + source_relative_path 定位，不把外部路径填入 image/meta/mask。

## 2. 声明与局部元信息

| 位置 | 必填内容 |
| --- | --- |
| 根 info.txt | dataset_id、layout_version、protocol_id/revision、dataset/label/split/association/converter/reader/evaluator 版本、working/frozen |
| 根 protocol.txt | schema_version=north16_seg_v1、protocol_id/revision/status、task=semantic_segmentation、num_classes=4、ignore_index=255 |
| 根 classes.txt | sky=0、water=1、ice=2、other=3、ignore=255 |
| sequence/info.txt | sequence、source_namespace/session、raw_root_id、源相对路径、默认适用范围及条件证据 |
| 相机 info.txt | sequence/sensor/camera、source_id、原视频、尺寸、编码/像素格式、帧数和解码状态/版本 |
| meta/f*.txt | id/sequence/sensor/camera、source_id、解码序号、PTS/time_base、日志候选、时间状态、scene/group、属性、标签路径/状态/版本 |
| sync/info.txt | association_version、规则、delta 符号约定、时钟/标定证据版本及生成状态 |
| 雷达/SAR info.txt | 原始量、位深/通道、地理信息、NoData、采集/接收/可用时间与处理链 |

frame schema 延续 north16_frame_v3，新增可选追溯字段；老字段不改语义。正式发布所需字段不能因当前 reader 不使用就省略；未实测的保持 unknown。相机 info 的 source_video_path 为源根相对路径；frame.source_video_path 与 source_id 对应同一资产。

根 info 的 source_registry 指向最近一次成功提交的完整 sources 快照，用于跨运行稳定身份。sync/clocks/<clock_model_id>/info.txt 登记时钟模型有效范围、参数、误差与审核证据；sync/calibrations/<calibration_id>/info.txt 登记变换、适用范围、误差指标和验收证据。参数和原始证据作为同目录支持文件保存，不以单个 verified 字符串代替验证过程。

scene_id 是物理评测场景；group 是防泄漏连通组。没有证据时均可 unknown，但进入正式 split 时必须完成审核；scene-macro 评测还要求冻结 scene 映射。不可将 sequence 直接拷贝成独立 scene。

## 3. samples.txt

列固定为：
id、sequence、sensor、camera、image、mask、meta、weather、illumination、label_status、group。

每行一个 visible/infrared 观测，id 全局唯一；三条路径完整指向该行文件。未标注或公开隐藏 gold 时 mask 为空；label_status 仍如实标识，不靠空路径推断真实负样本。其他必需字段不能空。scene 映射由正式 splits/scenes.txt 提供；不在训练时动态更改。

weather：clear / cloudy_overcast / fog_precipitation / unknown。
illumination：day / night / unknown。
label_status：unlabeled / draft / reviewed / adjudicated / frozen。
group：审核隔离组，试点允许 unknown，正式 split 不允许。

这张表是构建器在某版本下展开属性后的快照，不与人工 TXT 同时手工维护。雷达、SAR、检测和融合不混入此相机分割表，后续使用各任务清单。

## 4. 条件继承与审核

sequence 的 default_scope=all_observations_in_sequence 只在人工证明全部目标观测适用后填写，否则为 none。逐帧 weather/illumination 的显式值（包括 unknown）优先；值为 inherit 时，source/evidence_id/confidence/status/reason/attribute_version 成组从经审核默认值解析。缺失适用范围或证据则解析 unknown，并记录原因。

现有 frame 中各属性带独立 weather_* / illumination_* 字段；attribute_version 表示整条属性修订。不得部分继承导致标签与证据不一致。未确认跨设备时间/视场适用范围时，不因同一 sequence 就将可见光天气无条件传播给全部红外/雷达。

天气和光照状态为 unreviewed/reviewed/adjudicated；confidence 为 low/medium/high/unknown 的人工置信标记，不代表校准概率。unknown 也可被审核确认，reason 必须解释证据不足或 twilight。气象分类和太阳高度约定见 TASKS.md。

## 5. 时间与关联表

frame 的 decoded_frame_index 从 0 起；source_log_row_index 为 time.txt 的 1-based 物理行号或 unknown；PTS 为源整数，time_base 为 num/den，必须成对解释，不能以序号伪造。source_packet_index 无可验证映射时为 unknown。time_mapping_status 为 unresolved/verified/rejected，UTC 与 time_uncertainty_ms 未认证时为 unknown。

pairs.txt 列：
reference_id、associated_id、relation、delta_t_ms、uncertainty_ms、time_status、spatial_status、clock_model_id、calibration_id、evidence_id、association_version、status。

delta_t_ms = associated capture UTC - reference capture UTC；可为负。不可比较时为 unknown，不能以 0 代替。time_status=unresolved/verified/rejected，spatial_status=unverified/registered/rejected/not_applicable，status=candidate/verified/rejected；最终 verified 必须满足对应任务资格。未知误差不能当成零，接收时间差不能冒充采集时间差。

sar_links.txt 列：
reference_id、product_id、acquisition_start_utc、acquisition_end_utc、delta_t_s、age_s、availability_time_utc、footprint_overlap、temporal_setting、clock_model_id、evidence_id、association_version、status。

SAR delta_t_s 以过境起止中点减参考采集时刻计算，仅用于明确登记的关联摘要，不隐藏产品时间跨度。age_s 为参考时刻减过境中点，可为负；causal 还必须检查采集结束和实际可用时间不晚于参考时刻，不能只检查中点。footprint_overlap 为参考地理 ROI 被产品覆盖的面积比例 [0,1]，缺少可信 ROI/几何时 unknown；不能以整张 SAR 覆盖船位代替视场重叠。

sync 只保存实际生成的关系；没有候选可只有表头，阶段未执行时需在日志声明，不能解释成“不存在关联”。

## 6. 运行与标注表

| 文件 | TSV 列 |
| --- | --- |
| logs/<run_id>/sources.txt | source_id, raw_root_id, source_namespace, session_id, source_relative_path, sha256, size_bytes, sequence, sensor, camera, state, reason |
| logs/<run_id>/steps.txt | step, scope_id, state, started_at_utc, ended_at_utc, reason |
| logs/<run_id>/errors.txt | step, source_id, sample_id, code, message, severity |
| logs/<run_id>/checks.txt | check_id, scope_id, result, severity, message, evidence_path |
| logs/<run_id>/candidates.txt | id, selection_method, selection_reason, sampling_weight, status |
| annotations/reviews.txt | id, task_id, label_version, revision, label_status, annotator_id, reviewer_id, evidence_regime, evidence_ids, reviewed_at_utc |
| annotations/history.txt | id, task_id, revision, previous_revision, action, actor_id, changed_at_utc, reason, artifact_path |
| splits/scenes.txt | id, scene_id, group |

表中逗号仅展示列顺序，实际使用 TAB；模板在 ../templates/txt/。sources 是跨运行稳定登记的资产快照；steps 是每个阶段和范围的事件，恢复时追加事件，不用后一次状态掩盖上一次失败。checks 结果为 pass/fail/not_checked/not_applicable；severity 为 info/warning/error。errors 无错误时只有表头，不造一行 unknown 错误。

run info.txt 保存原始根登记/范围、完整配置快照文件引用、配置哈希、协议与软件版本、started/ended、run_status、计数。配置快照用 resolved.yaml，校验和用 checksums.txt（path、sha256 两列），都列入运行产物。这里的 resolved.yaml 是计划的输出文件，不是本轮生成的执行记录。

annotation 工程位于 annotations/projects/；修订资产存 annotations/history/，当前有效 mask 仍在相机 masks/。gold 私有目录不进入公开导出。公开版需要清除 meta 的私有证据路径、审阅人敏感标识和 history 中可恢复的测试标签，不能只删除 masks。

## 7. 验证边界

模板 record_status=template，必须填实测值并更新状态后使用。数值范围、版本、引用存在性与 enum 都要检查；官方发布不能沿用 placeholder ID。

现有 reader 只实现 protocol/classes/samples/split 和相机图像/mask/meta 的读取校验，不解释本章全部状态、关联表和历史。正式构建/评测模块必须共同执行扩展合同，不能以原型可读取代替完整验收。


## 已实现的相机帧回执

每个相机目录 frames.txt 为带表头 TSV：id、image、meta、image_sha256、image_bytes、pts、pts_time、time_base。它登记不可变的源解码身份和图像完整性；人工条件与标签仍以 meta 为依据，不覆盖回执。image/meta 是相对数据集根的完整路径。image_bytes 为非负字节数，pts_time 是解码器输出的相对时间，不能解释成 UTC。回执和相机 info 验收后提交，用于断点恢复。

每次运行 decoder/ 下保留各 source_id 的 FFmpeg 命令 JSON 与完整 stderr 日志，probes.json 保留原始 stream 字段（含色彩标记缺失），environment.json 保留依赖及实际项目代码哈希。后验 validation.json 明确全量/抽查范围，preview.jpg 仅用于检查，不作为像素标签。

## 已实现的属性修订记录

属性批次与扩展字段见 [ATTRIBUTES.md](ATTRIBUTES.md)。attribute_registry 指向当前属性修订的元数据/索引校验和，原构建校验和作为历史快照保留。scene_type 为宽泛内容类型，独立于 scene_id；AI 抽样判断与人工审核状态分开。
