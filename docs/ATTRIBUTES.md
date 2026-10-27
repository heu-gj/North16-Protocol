# 天气、光照与场景属性工作流

本模块管理显式属性决定与证据，不是天气识别模型，不修改像素分割标注或采集时间。

## 当前批次

范围为 20260902_044232、20260902_044732、20260902_045232，共 96 个相机流、28,640 张图像。依据各可见光流的开头可用帧、中间帧与末帧，共 144 张可见光样本进行 AI 视觉判读；额外查看 144 张红外样本以描述画质。不是逐张人工复核。

三个片段可见光总体为阴云外观 cloudy_overcast、白昼外观 day、海冰与冰间水道 sea_ice_with_leads。部分视角包含本船设备。前向 visible/front_03、front_04 持续低对比度；该问题在相邻视角不一致，不能仅凭发灰判为雾，镜头污染、结露等原因尚未确认。

用户明确确认“可见光 红外是同时拍的，只看可见光就行”。据此，红外沿用同片段可见光的粗粒度天气、光照和场景类型，来源字段写 visible_context_user_confirmed_simultaneous_recording。不以红外明暗判断昼夜。该确认只支持片段级环境属性，不能替代逐帧时间误差、时区与空间配准认证。

## 字段与状态

- weather / illumination 沿用现有枚举；视觉 day 不表示已计算太阳高度角。
- weather_status / illumination_status=unreviewed；attribute_actor_id=codex_visual_assessment。AI 判读、抽样推断不伪装成人工审核。
- attribute_assignment=sampled_stream_inference；attribute_evidence_sample 标识是否为实际查看的证据样本。流内其他帧是依据抽样稳定性赋值。
- scene_type=sea_ice_with_leads：宽泛内容类型；scene_description 是中文说明。
- view_type 区分含本船设备和海冰海面视角；image_quality_flags 是样本中观察到的流级画质候选，不代表每帧独立检测结果。
- scene_id/group 保持 unknown，独立评测场景边界尚未核实；连续文件夹不能擅自视为三个独立场景。candidate_continuity_group 只是待核实连续性提示。
- sequence/info.txt 汇总片段环境；相机 info.txt 保存流级决定及证据；meta/*.txt 保存显式属性；samples.txt 由 build_index 重新派生。
- default_scope=none。当前使用显式逐帧赋值；AI 未审核的片段默认值不能通过 inherit 冒充已审核值。

## 模块与操作

src/north16/annotations/attributes.py 提供显式决定应用入口：--root、--plan、--evidence、--run-id、--protocol。decisions.json 必须精确覆盖待处理工作数据集中的每个相机流，字段受枚举与证据检查。

流程：抽取证据预览 → 查看并填写 decisions.json → 预检全部决定/引用/当前属性版本 → 完整 ZIP 备份待修改 TXT → 应用流级和逐帧属性 → 重建 samples.txt → 检查身份/图像/标签/分组未变 → 保存汇总和当前属性哈希。

当前模块对已有属性拒绝覆盖，需要显式修订方案。证据文件包括 evidence_images.txt、context_evidence.txt、co_recording_evidence.txt、decisions.json 和接触图。before.zip 与 before_checksums.txt 保留可恢复的原元数据。原构建日志和 checksums.txt 是历史快照，不能改写；新的 attribute_registry 指向属性修订快照。后验验证同时保留原图像哈希与新元数据哈希验证。

当前 samples.txt 不新增 scene_type 列，保持 Dataset 兼容；scene_type 可从逐帧 meta 或流级汇总读取。目录名保持不变，不以天气重命名图片或搬移文件。

## 发布前

需人工复核条件判据、变化区段及证据，核实太阳高度或明确采用视觉光照设置；核实独立场景/隔离组。未审核属性可用于工作集筛选，不应作为已经认证的气象或天文观测对外发布。
