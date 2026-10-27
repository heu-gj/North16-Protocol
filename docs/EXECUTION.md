# 首次执行说明

2026-10-23 开始实现与执行相机导入试点。运行情况以 datasets/logs 中实际 summary.json、info.txt、errors.txt 和 checks.txt 为准，本文不是完成证明。

## 已实现范围

- 使用 configs/pilot.yaml 的三个精确片段，读取 adapter 映射，哈希登记全部源文件。
- 对所有相机流探测尺寸/编码/标称帧数，按未完成视频的 RGB 未压缩容量乘 1.2 估算磁盘。
- FFmpeg 单次解码输出原尺寸 RGB PNG；同一 filter graph 的 showinfo 提供实际帧号/PTS/time_base，逐图校验 CRC、尺寸与哈希。
- 不复制帧、不基于 time.txt 行数裁掉帧；日志原样保留，未认证 UTC 和日志行绑定保持 unknown。
- 流目录验收后原子提交，已完成流按原始源哈希、转换指纹、输出数量与图像校验和复用。人工 meta 和 mask 不覆盖。
- 记录全部原始雷达/导航来源，保存原始导航文本、TIFF 与 KML/index。雷达完全相同文件按内容资产去重，仍保留每次接收记录；扫描物理独立性未认证。
- 导航仅拆分前缀与原始字段，KML 严格 XML 检查失败保留原件，无修复猜测。
- 从元信息解析构建 samples.txt，条件未知，mask 留空，不生成 split 或模拟标注。
- north16.datasets.North16SegDataset 支持 split=None、显式 sequences、require_mask=False 的试点检查，正式 split 校验沿用原型。

## 使用入口

run.py 从当前项目 src 加载代码，不修改全局环境。配置路径相对配置文件解析，CLI 的 --config 使用实际 YAML 路径。

```powershell
D:\IDE\miniconda3\python.exe -B E:\Dataset\north16\protocol\run.py --config E:\Dataset\north16\protocol\configs\pilot.yaml --ffmpeg D:\Software\ffmpeg\bin\ffmpeg.exe --ffprobe D:\Software\ffmpeg\bin\ffprobe.exe --workers 4
```

全流程不等同于一次抽帧运行。本工具当前执行 inspect/extract/index/validate；同步阶段 blocked，人工候选与标注 pending，split/release skipped。以这些状态判断可用资格，不能仅看 build_status=succeeded 就宣称已标注或已同步。

## 当前限制

首版仅支持单根目录、显式片段和 north16_capture_v1；未知布局拒绝。sequence 身份碰撞会报错，稳定后缀自动分配尚未实现。时钟校正/配准、人工标注导入、near-duplicate 复核、检测/融合/雷达/SAR Dataset、官方评测与正式发布尚未实现。

颜色转换采用固定 FFmpeg 构建的 swscale 默认 YUV→RGB、rgb24 输出；源色彩标记保存在 probes.json，缺失时不伪造 BT.709 等认证声明。转换命令、构建和指纹全部保留；更换此配置不能直接覆盖旧图。

崩溃未验收的 .partial 目录保留，恢复不将其视为已完成；重新提取该流使用新的临时目录。若程序被强制终止而留下 .north16_build.lock，须先确认没有运行构建进程，人工检查后解除锁，不自动删除其他进程的锁。

本轮新包已实现，旧 north16_benchmark 原型仍保留，并未将旧入口改为自动依赖新包；优先使用新路径，后续安装/兼容层另维护。

## 测试

现有 13 项 reader 回归及 3 项导入/路径/协议一致性测试通过。集成测试使用 64×48 合成视频，验证变帧相对时间、未验证日志不绑定、增量复用、人工属性不覆盖、篡改输出拒绝和无 split 读取。
