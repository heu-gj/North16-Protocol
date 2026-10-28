# 从原始视频到图片＋标签交付包

0.11.0 推荐流程：初始化最终目录 → 创建独立标注工作区 → 工作区抽帧 → 调参和保存 JSON → 人工修正 → 图片＋标签整包导入最终目录 → Dataset 读取。

安装 `north16[gui]` 与 FFmpeg/FFprobe，先运行 `north16 doctor`。以下 `datasets` 是最终数据集，`annotation` 是工作区，`delivery` 是可迁移的交付包。三个目录分开，输出要求新目录。已有初始化好的 datasets 可直接从第2步开始。

```powershell
# 1. 最终目录只登记来源、预留位置，不转图片、不创建 masks
north16 initialize --raw E:\data\raw --output E:\data\datasets

# 2. 从最终目录的来源登记创建工作区，不复制图片/标签、不处理视频
north16 annotation initialize --dataset E:\data\datasets --output E:\data\annotation

# 3. 先只读查看范围、逐流图片数、保守容量与剩余磁盘
north16 annotation extract --root E:\data\annotation --interval 5 --dry-run

# 4. 在工作区抽帧。省略 --interval 则全量保存；单位为秒
north16 annotation extract --root E:\data\annotation --interval 5

# 5. 打开工作区，直接保存同镜头 masks/*.json
north16 annotation gui --root E:\data\annotation

# 6. 标注后交付所选范围；不传筛选则包含所有已完整抽帧镜头
north16 annotation export --root E:\data\annotation --output E:\data\delivery

# 7. 核验并整包合并，最终目录此时才获得图片与标签
north16 import-package --root E:\data\datasets --package E:\data\delivery
```

初始化当前适配 North16 采集布局，其他布局需增加发现适配器。也可用 `annotation initialize --raw <原始根> --output <新工作区>` 直接建立工作区，最终 datasets 需从同一原始来源初始化。初始化计算视频哈希但不调用 FFmpeg/FFprobe，原视频仍需保留并可访问。

界面操作：选择片段和 visible → 在16路总览点击镜头独立调参 → 两点直线调整地平线，默认忽略半宽1.00% → 人工选择冰水混合/全冰/全水 → 估计阈值并修调 → 验证16路首/中/末 → 勾选镜头 → 点击“保存勾选镜头的标签”。默认使用当前参数，确需再次估参时勾选对应选项。单张保存也直接进入工作区同镜头 masks。其他片段分别操作。

保存标签和整包交付是两个步骤。“导出图片＋标签整包”在选择的父目录建立新包，仅交付当前片段勾选的 visible 镜头；红外浏览时交付当前红外镜头。CLI 不筛选时交付全部完整镜头，可同时含 visible/infrared。所有选中镜头的图片均保留，包括未标注帧，报告单列未标注数量，不把缺失标签当作已完成。

JSON 可在人工标注工具中修正，保持与 `../images/<frame>.png` 的关联及 north16 身份字段。建议修正后再导出；已经交付的同名标签若内容不同，导入会报冲突，需作为新版本处理。自动结果始终是 draft/unreviewed，不能直接作为 benchmark 真值。人工审核记录 label_status、reviewer、reviewed_at；默认 Dataset 只接受 reviewed/adjudicated/frozen，试标需显式允许 draft。

`--interval` 按源PTS从首帧起选取与上次保留帧至少相隔指定秒数的第一个实际帧；不插帧、不保证各设备同步。保留原尺寸、源解码帧号、PTS/time_base，文件名可能不连续。不同抽帧策略使用新工作区；不覆盖已有完整流。

容量预算是 RGB24 宽×高×3×预计帧数×1.2，累计所选待处理流；PNG 实际可能更小，压缩视频大小不能代替抽帧容量估算。预检可用 `--sequences <片段>`、`--sensor visible`、`--cameras back_04` 缩小范围。工作区、交付包及最终数据集各自保留图片，复制过程会占多份空间；本版不自动删除源工作区、不做隐式移动。

当前 GrabCut 仅用于 visible；infrared 支持抽帧、浏览、像素查看和整包交付。天气、光照和场景元信息需按协议判断；16路相同帧号及登记PTS不能证明完成时间同步。雷达/SAR专用处理与正式 benchmark 冻结发布另行完成。

历史 `camera extract`、结构化 datasets 的外置标签包及 `segmentation gui` 仍兼容。新工作默认使用独立 annotation。详见 [标注工作区合同](ANNOTATION.md)、[CLI](CLI.md) 和 [模块说明](MODULES.md)。
