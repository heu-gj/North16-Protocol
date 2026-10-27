# 观测标准化与索引

状态：部分实现，实际 .py 文件已提供相机试点能力；未出现的计划文件仍待实现。

计划文件：camera.py、clock.py、radar.py、navigation.py、sar.py、associate.py、index.py、groups.py。以实际 .py 清单和 EXECUTION.md 区分已实现与计划能力。

职责：保留原尺寸/PTS/来源；处理时钟证据、扫描复用、异步关联、属性解析后索引和分组提案。派生变换可追溯，不覆盖人工记录。

输入输出：Observation、Association、samples 快照、分组提案与数量对账。

完整合同见 [模块设计](../../../docs/ARCHITECTURE.md)、[总协议](../../../docs/PROTOCOL.md)。只依赖底层 common 与已声明数据合同，不反向依赖 pipeline。


实现范围见 [执行说明](../../../docs/EXECUTION.md)。不能将试点构建成功视为人工标注、同步或正式发布成功。
