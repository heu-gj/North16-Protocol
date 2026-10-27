# X-AnyLabeling 人工修正工作流

新版单镜头工程及统一输出遵循[标注工作区规范](ANNOTATIONS.md)。下方历史多镜头工程已归档到annotations/archive；保持原文件格式与相对路径，仍可继续编辑。新版工程打开images目录，回读默认进入corrected。

本模块把独立 GrabCut 草稿转换为 X-AnyLabeling 的同名图片 + JSON 多边形标注，再将人工修正后的 JSON 转回单通道语义掩码。代码为 src/north16/annotations/xanylabeling.py；不写入正式 masks/，不修改原始图片或原有 GrabCut 结果。

## 本次编辑工程

工程：E:\Dataset\north16\datasets\annotations\archive\xanylabeling_20260902_044232

```
xanylabeling_20260902_044232/
  README.md
  classes.txt                 # sky water ice other ignore，可供软件载入类别
  classes.json                # 显式ID映射，不能按类别列表序号猜测ignore
  config.yaml                 # 软件类别和颜色配置
  manifest.txt                # 来源、初始JSON哈希、每图验证结果；不是正式samples
  validation.json
  progress.json
  visible/
    back_01/ ... back_08/
    front_01/ ... front_08/
      f000000.png             # 独立原图副本
      f000000.json            # 同名、原分辨率可编辑多边形
```

## 打开和修正

1. 运行 protocol/open_xanylabeling.ps1，默认打开 visible/back_04。脚本使用本机 E:\Code\X-AnyLabeling-v4.0.0-beta.3-CPU.exe。若位置改变，用 -Executable 指定。用 -Camera front_01 等切换镜头。
2. 也可在 X-AnyLabeling 中“打开目录”，选择上面工程的 visible/back_04。应当打开原图 PNG，并自动加载同名 JSON；不能打开原 masks/、color/、overlay/ 当作原图。
3. 标签只使用 sky、water、ice、other、ignore，小写拼写固定。编辑多边形、增加/删除区域，保存同名 JSON。保留本工程目录内的图片和 JSON 配对；不要另设统一的扁平保存目录（各镜头帧号重复）。
4. other 草稿原先没有，需要补绘本船、设备等真实实体；栏杆间隙按实际天空/水/冰保留。暗色薄冰需复核，确认是冰标 ice，仍不确定标 ignore。
5. JSON 转回掩码使用下方 import 命令或 protocol/import_xanylabeling.ps1。输出新版本，可选择生成叠加图复核。审核通过后另走正式发布步骤。

默认软件显示可能把相邻多边形分片边界画出来，属于编辑分片，不代表增加语义类别。可降低填充不透明度或调整边线显示。天空、水、冰的轮廓均可编辑。复杂冰水区含较多分片和顶点，应按镜头打开，避免一次加载整个工程。

## 像素语义与孔洞

固定映射：sky=0、water=1、ice=2、other=3、ignore=255。未被任何形状覆盖的像素统一为 ignore=255，不能默认水或背景。自动预标注的 ignore 作为透明未标区保留；人工也可显式画 ignore 多边形。

普通 X-AnyLabeling polygon 无通用内环字段。导出将有孔洞的连通域切分为多个不带孔洞的多边形，不删除碎冰、不设最小面积、不平滑轮廓；极少数像素交界用局部多边形补丁保持精确。不能把孔洞直接填成外层类别。导出后逐张按软件的 PIL 填充规则重建掩码，要求与输入 PNG 逐像素一致，错误数为0才成功。图像副本逐张SHA256与来源比对。

人工修正后若图形重叠，JSON shapes 列表中靠后的形状覆盖靠前的形状；不是按类别ID排序。需要确认新画的 other/ignore 在目标旧区域上方，或直接裁改旧形状。删除区域会回到 ignore。移走一个分片只会影响该分片，原有其他分片保留。

## 命令

```powershell
$env:PYTHONPATH = 'E:\Dataset\north16\protocol\src'
D:\IDE\miniconda3\python.exe -m north16.annotations.xanylabeling export `
  --root E:\Dataset\north16\datasets `
  --draft E:\Dataset\north16\datasets\annotations\archive\grabcut_20260902_044232 `
  --output E:\Dataset\north16\datasets\annotations\xanylabeling_NEW `
  --workers 4

D:\IDE\miniconda3\python.exe -m north16.annotations.xanylabeling import `
  --project E:\Dataset\north16\datasets\annotations\archive\xanylabeling_20260902_044232 `
  --output E:\Dataset\north16\datasets\annotations\xanylabeling_edited_NEW `
  --changed-only --preview
```

export 可选 --camera back_04、--limit 5 用于小批试用。import 不带 --changed-only 会导出全部JSON，带上则只导出文件内容相对初始哈希有变化的JSON；内容变化不等于完成审核。--preview 附 color/、overlay/；否则只保存 masks/ 和 import_log.json。两种操作都要求新的输出目录，拒绝覆盖已有编辑结果。

导入检查标签、几何、原图身份及哈希、图像尺寸和PNG回读；未知类别/不支持的形状明确报错。支持 polygon、rectangle、rotation、quadrilateral；海冰语义区域不要使用点、线、圆或检测框代替真实轮廓。不依赖软件通用“导出分割图”的自动类别编号，尤其避免ignore被编号成4。

## 审核与兼容性边界

所有生成JSON checked=false；导入后仍为 draft/pending_review。仅保存文件、勾选软件检查状态或成功转换均不自动发布为gold，不修改根samples.txt，不改变split。

查阅来源：官方 main 分支 LabelFile、Shape 及 utils/shape.py，https://github.com/CVHub520/X-AnyLabeling 。本机发现4.0.0-beta.3 CPU可执行文件；使用基础polygon/同名JSON格式。已验证官方像素填充函数与本工具一致；未在桌面GUI中逐项点击验收，需首次打开时确认本机界面加载正常。
