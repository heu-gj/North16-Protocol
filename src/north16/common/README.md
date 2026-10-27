# 公共配置与数据合同

状态：部分实现，实际 .py 文件已提供相机试点能力；未出现的计划文件仍待实现。

计划文件：schema.py、config.py、text.py、paths.py、identity.py。以实际 .py 清单和 EXECUTION.md 区分已实现与计划能力。

职责：加载已声明的协议与任务配置，读取 TXT/TSV，验证路径与版本，登记稳定来源身份。所有常量来自已校验的配置；训练读取只依赖这里的轻量功能。

输入输出：ProtocolConfig、BuildConfig、SourceAsset、Observation；统一错误类型。

完整合同见 [模块设计](../../../docs/ARCHITECTURE.md)、[总协议](../../../docs/PROTOCOL.md)。只依赖底层 common 与已声明数据合同，不反向依赖 pipeline。


实现范围见 [执行说明](../../../docs/EXECUTION.md)。不能将试点构建成功视为人工标注、同步或正式发布成功。
