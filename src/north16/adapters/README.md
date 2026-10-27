# 原始格式适配

状态：部分实现，实际 .py 文件已提供相机试点能力；未出现的计划文件仍待实现。

计划文件：base.py、registry.py、north16_capture.py。以实际 .py 清单和 EXECUTION.md 区分已实现与计划能力。

职责：按签名发现源片段与流，探测格式并保留原始字段，输出统一 SourceAsset/RawRecord。未知布局明确拒绝；不猜时区、不直接写标签。

输入输出：discover、probe、read_raw_records；输入为只读原始根和 adapter 参数。

完整合同见 [模块设计](../../../docs/ARCHITECTURE.md)、[总协议](../../../docs/PROTOCOL.md)。只依赖底层 common 与已声明数据合同，不反向依赖 pipeline。


实现范围见 [执行说明](../../../docs/EXECUTION.md)。不能将试点构建成功视为人工标注、同步或正式发布成功。
