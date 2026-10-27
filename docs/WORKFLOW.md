# 从原始视频到标签

流程：初始化 → 相机抽帧 → 调参 → 抽样检查 → 导出标签包 → 合并 → 人工修正与审核。

1. 安装 `north16[gui]`，并安装 FFmpeg / FFprobe。运行 `north16 doctor` 检查环境。
2. `north16 initialize --raw <原始根目录> --output <新数据集目录>`：登记来源、建立片段 / visible / infrared / 镜头位置，不转图片、不创建 masks。当前适配器识别 North16 采集布局，其他布局需适配。
3. `north16 camera extract --root <数据集目录>`：逐视频解码为 images/*.png，生成 meta/*.txt、frames.txt 与流信息。可用 `--sensor visible --cameras back_04` 缩小范围；使用 `--sequences` 选择片段。
4. `north16 segmentation gui --root <数据集目录>`：选择片段和 visible，进入16路总览，逐镜头调试。
5. 两点直线地平线：拖动左右端点调整高度和倾斜。忽略半宽默认1.00%。有明显曲线畸变时用多点折线。人工选择冰水混合 / 全冰 / 全水；保留地平线后估计亮度阈值并修调。各路参数独立。
6. 点击“验证16路：开头 / 中间 / 末尾”，查看4×4总览或逐镜头三帧并排。检查地平线、冰水边界、暗冰、反光、船体等；该检查不写标签，也不代表准确率。
7. 勾选镜头，保持“生成前各镜头独立自动估参”不勾选，点击“导出勾选镜头的标签”。处理当前片段所选镜头的全部帧；其他片段分别操作。
8. 点击“打开最近输出目录”，查看 `labels/<批次>/dataset/sequences/<片段>/visible/<镜头>/masks/*.json` 和任务汇总。输出标签状态为draft / unreviewed；单帧失败会记录，任务可能只完成部分标签。
9. `north16 import-package --root <数据集目录> --package <标签包>`：按清单校验合并。也可把包内dataset的内容整体合并到数据集根目录；不需要逐个复制masks。已有不同内容的同名文件拒绝覆盖。
10. 合并后JSON关联同镜头images原图，用X-AnyLabeling修正。不确定像素为ignore，other需要人工处理；保留north16身份与来源信息。人工审核完成后，按协议记录审核状态、reviewer和reviewed_at。
11. `SegmentationDataset` 读取合并后的JSON。试标检查显式允许draft；正式训练评测使用审核标签与冻结划分。

天气、光照等元信息由协议字段管理，不能仅凭目录名自动认定。16路相同帧号及已登记PTS不等于完成跨设备时间同步认证。红外当前可抽帧和浏览，尚不提供当前visible亮度算法的自动分割。
