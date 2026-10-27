# 官方评测

状态：接口设计，尚无业务实现。

计划文件：predictions.py、segmentation.py、detection.py、groups.py、report.py。这些文件本轮不创建。

职责：按固定样本与 scene 映射检查预测并计算指标，正确处理 ignore/空类/缺预测；按天气/光照报告数量和版本。

输入输出：带 task、protocol、label、split、evaluator 版本的可追溯结果。禁止用 test 调阈值。

完整合同见 [模块设计](../../../docs/ARCHITECTURE.md)、[总协议](../../../docs/PROTOCOL.md)。只依赖底层 common 与已声明数据合同，不反向依赖 pipeline。
