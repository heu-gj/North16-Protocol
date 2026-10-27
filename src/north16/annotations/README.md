# 标注与属性管理

状态：已实现 attributes.py 的显式属性决定应用、备份与索引更新；其余功能仍为接口设计。

计划文件：sampling.py、attributes.py、segmentation.py、detection.py、review.py。这些文件本轮不创建。

职责：按规则选择候选，管理天气/光照证据、标签导入、双标/仲裁和修订；原标注工程、当前 mask、历史资产分开。

输入输出：AnnotationRecord、候选清单、审核记录、合法标签；不更改源图像和 split。

完整合同见 [模块设计](../../../docs/ARCHITECTURE.md)、[总协议](../../../docs/PROTOCOL.md)。只依赖底层 common 与已声明数据合同，不反向依赖 pipeline。


属性工作流见 [ATTRIBUTES.md](../../../docs/ATTRIBUTES.md)。AI 抽样判断保留 unreviewed，不代替独立人工审核。

已增加固定参数预标注批处理 grabcut.py，见 [GRABCUT.md](../../../docs/GRABCUT.md)。输出独立 draft，不导入正式标签。

已增加 X-AnyLabeling 编辑工程导出与修正标签回读模块 xanylabeling.py，见 [XANYLABELING.md](../../../docs/XANYLABELING.md)。固定类别ID、孔洞保真、逐像素转换校验、独立编辑副本；回读结果仍待审核。
