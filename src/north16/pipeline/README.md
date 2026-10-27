# 阶段编排与数据集生命周期

状态：部分实现，实际 .py 文件已提供相机试点能力；未出现的计划文件仍待实现。

计划文件：runner.py、stages.py、resume.py、release.py；未来 cli.py。以实际 .py 清单和 EXECUTION.md 区分已实现与计划能力。

职责：解析任务，按前置条件调度模块，记录运行/恢复，原子提交已校验资产和索引，维护来源登记，生成独立冻结快照。

输入输出：BuildResult、运行日志与数据快照；业务逻辑留在所属模块。

完整合同见 [模块设计](../../../docs/ARCHITECTURE.md)、[总协议](../../../docs/PROTOCOL.md)。只依赖底层 common 与已声明数据合同，不反向依赖 pipeline。


实现范围见 [执行说明](../../../docs/EXECUTION.md)。不能将试点构建成功视为人工标注、同步或正式发布成功。
