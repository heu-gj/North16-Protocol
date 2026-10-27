# 固定参数 GrabCut 批处理

模块：src/north16/annotations/grabcut.py。输入标准数据集 samples.txt、一份固定 parameters.json、旧示例（用于逐像素复现验证），输出独立预标注目录 annotations/grabcut_<sequence>/。

命令在 run_grabcut_first.ps1 中，默认 --resume，已完成结果经原图和输出哈希校验复用。当前实现范围仅 visible，不将可见光亮度阈值用于 infrared。支持 --sequence、--workers 和独立 --output；整段无逐帧调参。

固定参数来自此前 back_04：宽1280，按比例缩放；固定相对地平线顶点与0.02半高忽略带；平均通道亮度阈值78/125/168；GrabCut 5次、seed42；3×3边界忽略；恢复原图尺寸使用最近邻。每张分别根据该图重估颜色GMM，这是同一算法的正常行为，不是改变参数或人工逐图调参。

保存单通道原尺寸 masks/、无损彩色 color/、原尺寸JPEG叠加 overlay/ 和逐图meta/回执。附每路3帧预览、总览、运行记录、参数与来源哈希、errors.txt、validation.json。输出与正式 masks 和根 samples 分开，状态始终 draft/unreviewed。

同一物理场景不保证不同镜头共用参数：朝向、地平线、曝光、光学污染、船体占比都会影响。other=3未实现，因此船体/设备会被误分，不能把生成完成当作标注验收通过。没有人工真值，不报告准确率。

首轮验证：旧图逐像素复现；所有生成mask写后完整重读、uint8/尺寸/值域检查；每张源图SHA256核对元信息；最终所有mask/color/overlay哈希校验；失败逐张记录，不补造mask。断点只复用回执及哈希完整结果。
