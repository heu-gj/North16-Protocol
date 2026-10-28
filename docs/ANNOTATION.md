# 独立标注工作区与交付合同（0.11.0）

0.12.0参数复用：默认两点直线。调试后点击“保存参数及验证记录”会同时复制参数快照；换镜头点击“粘贴到当前镜头”。也可将当前参数应用到本片段全部可见光镜头，包括未勾选镜头；各路参数副本独立。复制只在本窗口有效，跨次启动用JSON保存/加载。操作详情见[GUI.md](GUI.md)。


状态：已实现。`north16.annotation.AnnotationWorkspace` 管理初始化、抽帧和整包交付；`AnnotationBuilder` 复用 segmentation 的估参、GrabCut、JSON生成及16路并发，按工作区角色选择存储位置。模块不依赖 GUI；GUI/CLI 调用同一业务接口。

```text
data/
  raw/                                     原始视频
  annotation/                              抽帧与标注工作区
    info.txt / protocol.txt / classes.txt
    sources.txt / samples.txt
    parameters/<sequence>/visible/*.json    参数与估参证据
    last_run.json / run_*.json               生成记录
    sequences/<sequence>/
      info.txt                             片段元信息
      visible/<camera>/
        info.txt / frames.txt
        images/f000000.png
        meta/f000000.txt
        masks/f000000.json                 保存标注后才出现
      infrared/<camera>/
        info.txt / frames.txt
        images/f000000.png
        meta/f000000.txt
    sync/info.txt / logs/
  delivery/                                新建的完整交付包
    package.txt / files.txt / README.txt
    dataset/sequences/<sequence>/<sensor>/<camera>/
      info.txt / frames.txt
      images/*.png
      meta/*.txt
      masks/*.json                         可缺部分帧
  datasets/                                最终数据集
    info.txt / protocol.txt / classes.txt
    sources.txt / samples.txt
    sequences/<sequence>/
      info.txt
      visible/<camera>/                    初始化时只有空位置和pending信息
        info.txt / frames.txt               frames在交付后出现
        images/*.png                       交付后出现
        meta/*.txt
        masks/*.json
      infrared/<camera>/...
    sync/info.txt / logs/
```

各镜头图片与标签分 images/masks。生成标签以原帧名为文件名，固定默认 JSON，JSON 内 imagePath 为 `../images/<frame>.png`。类别 sky=0、water=1、ice=2、other=3、ignore=255；unknown 不作为类别。薄冰、混合海面、船体与不确定区域需人工复核。

初始化只建立空目录和来源登记，不生成 masks。从已有 datasets 克隆工作区时仅复制来源与协议/片段头信息，不复制旧图片或旧标签；原有抽帧不会自动搬走。datasets 若已有图片，交付时同内容文件可复用，不同内容拒绝覆盖。

workspace 的 info.txt 标记 `workspace_role=annotation`、`annotation_storage=in_place_masks`。普通 datasets 无此标记，维持外置标签包行为。工作区不生成嵌套 dataset/ 或 package.txt；只有交付包才有这些内容。工作区的参数和运行记录留在原处；生成参数与估参依据亦嵌入标签 north16 字段，整包交付无需依赖原工作区绝对路径。

交付包 `schema_version=north16_package_v1`、`kind=annotation`、protocol_id 与数据集一致。files.txt 对 payload 中所有文件登记相对路径和SHA256，不携带最终根索引、工作区角色头或参数运行日志。导出校验完整流、实际图片哈希及已有标签，复制到临时目录，复核后发布新包；停止/失败不发布半成品。选择整个镜头的图片和meta，允许尚未标注的图片，明确报告 images/labels/unlabeled_images 数量。

导入先检查全包清单、哈希、原视频 source_id/source_sha256、流目录身份、帧索引与PTS、JSON尺寸/类别/样本ID/原图哈希，并预检所有目标冲突，再逐文件复制。同名同内容跳过；初始化pending流可被同来源complete流替换；其他不同内容拒绝覆盖。抽帧、就地生成、导出及导入使用根目录互斥锁，避免协议工具同时改写。外部人工编辑不持此锁，导出时请停止编辑，复制时发现变化会拒绝发布。导入异常中断后已复制文件可能保留，相同包可校验重试。

根 samples.txt 是初始化快照，合并不覆盖它；CameraDataset/SegmentationDataset 根据 `camera_index=frames` 读取各流 frames.txt，因此整包导入即可读取，无需逐个复制masks或手动重建根索引。缺失标签可用 labeled_only=True 显式筛选；不是已审核标签。试标示例：

```python
from north16.annotation import AnnotationWorkspace, AnnotationBuilder
from north16.datasets import SegmentationDataset

work = AnnotationWorkspace(r'E:\data\annotation')
work.extract(interval=5, dry_run=True)
# GUI等价业务：builder.generate(key, images, profile, work.root)
builder = AnnotationBuilder(work.root)
report = work.export(r'E:\data\delivery', sensor='visible', cameras=['back_04'])
dataset = SegmentationDataset(
    root=r'E:\data\datasets', split=None, sequences=['20260902_044232'],
    labeled_only=True, allowed_label_statuses=['draft'],
)
```

执行命令和人工操作顺序见 [WORKFLOW.md](WORKFLOW.md)。最终数据集保存图片；它不是只含外部绝对路径的索引目录。仅视频登记和占位阶段不包含已抽帧图片。
