# 合同测试

已加入 test_reader.py（13 项 reader 回归）与 test_build.py（实际 FFmpeg 合成视频/恢复/辅助资产和路径测试），共 16 项通过。实际数据的后验检查由 north16.validation.pilot 执行；测试不代替人工标注或时钟认证。

测试设置项目 src 路径后使用 unittest discover。依赖 FFmpeg/ffprobe 的测试当前使用本机已确认路径；完整原始数据不是默认测试夹具。后续按模块扩展合同测试。
