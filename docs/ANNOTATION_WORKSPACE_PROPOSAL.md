# 独立标注工作区方案

状态：设计提案，尚未作为CLI、GUI或Dataset的新存储格式实现。现有0.10.1仍在选定数据集根目录抽帧，GUI结构化标签包默认不重复携带图片。本文不提供尚未实现的命令。

目标：把抽帧和标注集中到一个工作区；结构化datasets初始化只登记视频及预留位置，不承担抽帧任务。最终交付保持原有visible/infrared、片段/镜头身份和Dataset接口。

推荐目录：同一个标注工作区内，以片段/模态/镜头组织，图片和JSON分别放images与masks。这样图像和标注始终一起交付，保留现有JSON的../images/<frame>.png关系。

```text
data/
  raw/                              原始视频，只读
  annotation/                       抽帧和标注工作区
    info.txt / sources.txt
    parameters/
    sequences/<sequence>/visible/<camera>/
      info.txt / frames.txt
      images/f000000.png
      masks/f000000.json             标注后生成
      meta/f000000.txt
  datasets/                         最终结构化数据集
    info.txt / protocol.txt / classes.txt
    sources.txt / samples.txt
    sequences/<sequence>/visible/<camera>/
      info.txt / frames.txt
      images/f000000.png             导入整包后出现
      masks/f000000.json
      meta/f000000.txt
```

流程：登记原视频/初始化最终目录 → 在annotation中按间隔抽帧 → GUI直接打开annotation → 每镜头估参、调参、首中末检查 → JSON保存到同镜头masks → 导出图片＋标签＋逐帧元信息的完整交付包 → 整包校验导入datasets → Dataset读取。未标注图片的保留/导出范围须显式选择，不应默默丢弃。

相机与标签组合包需新增包类型或版本：现有camera包不能包含masks，segmentation包只能包含masks。新包导入应核验源视频身份、图片哈希、逐帧PTS、JSON尺寸/类别/样本ID与图片对应关系；先检查所有冲突再复制，保留人工修改，不覆盖旧标签。images和masks同工作区不会减少PNG本身大小，减少占用仍依赖间隔抽帧；可后续提供显式搬移/硬链接策略以避免同盘双份图片，但不默认删除源工作区。

需要区分的另一种需求是datasets永久只保存索引、图片和标签一直留在外部。该方案需要资产根目录映射与可迁移的相对路径注册，修改Dataset、GUI和校验器的路径解析；不能只把images挪走，现有严格的根目录内路径检查会拒绝。也不能默默改成绝对路径，从而失去跨机器可迁移性。

如果要求同一个镜头文件夹直接混放f000000.png与f000000.json，则需另一个显式布局适配器；现有默认仍推荐images/masks分目录。
