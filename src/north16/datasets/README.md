# PyTorch 数据读取

状态：部分实现，实际 .py 文件已提供相机试点能力；未出现的计划文件仍待实现。

计划文件：segmentation.py、transforms.py；后续 detection.py、fusion.py。以实际 .py 清单和 EXECUTION.md 区分已实现与计划能力。

职责：North16SegDataset 读取固定索引；计划支持显式片段的无 split 检查。图像 float32，mask int64；联合变换保持几何。不在训练中构建或改写数据。

输入输出：North16SegDataset、SegResize；后续类按任务合同开放。当前新包未实现。

完整合同见 [模块设计](../../../docs/ARCHITECTURE.md)、[总协议](../../../docs/PROTOCOL.md)。只依赖底层 common 与已声明数据合同，不反向依赖 pipeline。


实现范围见 [执行说明](../../../docs/EXECUTION.md)。不能将试点构建成功视为人工标注、同步或正式发布成功。
