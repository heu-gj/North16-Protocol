# 数据质量与发布校验

状态：部分实现，实际 .py 文件已提供相机试点能力；未出现的计划文件仍待实现。

计划文件：schema.py、assets.py、labels.py、time.py、splits.py、release.py。以实际 .py 清单和 EXECUTION.md 区分已实现与计划能力。

职责：按范围验证来源/文件/标签/关系/泄漏及发布资格，记录 pass/fail/not_checked/not_applicable，不删失败样本掩盖问题。

输入输出：ValidationReport；真实场景独立性及同步认证需要外部证据和人工审核。

完整合同见 [模块设计](../../../docs/ARCHITECTURE.md)、[总协议](../../../docs/PROTOCOL.md)。只依赖底层 common 与已声明数据合同，不反向依赖 pipeline。


实现范围见 [执行说明](../../../docs/EXECUTION.md)。不能将试点构建成功视为人工标注、同步或正式发布成功。
