# 0.6.0 标注输出

当前规范以[初始化、相机、分割模块](MODULES.md)为准：初始化不抽帧、不创建masks；相机模块独立处理；分割默认导出同结构masks/*.json；整包合并后Dataset直接读取。下方保留旧版接口与历史实现说明，仅用于兼容和追溯。

# 标注工作区规范

north16 0.4.4；目录名统一使用复数 `annotations`。数据根为 `E:/Dataset/north16/datasets`。

```text
annotations/
  README.txt
  index.txt                         自动生成的TAB批次清单
  drafts/<片段>/<模态>/<镜头>/<批次>/
    masks/ color/ overlay/ meta/
    parameters.json
    manifest.json / samples.txt / dataset.json
    run.json / validation.json
  projects/<片段>/<模态>/<镜头>/<批次>/
    images/f000000.png
    images/f000000.json
    manifest.txt / classes.json / dataset.json / source.json
    README.txt / validation.json
  corrected/<片段>/<模态>/<镜头>/<新批次>/
    masks/ color/ overlay/           后两项由--preview生成
    samples.txt / dataset.json / import_log.json
  profiles/<片段>/<模态>/<镜头>/<参数哈希>/
    parameters.json / parameters.validation.json
  archive/
    <原试验目录名>/                  完整保留历史布局与文件
    migrations/<迁移批次>.json       原位置、新位置、状态、文件数
```

模态固定为 `visible`、`infrared`；读取能力不等于分割能力，0.4.4 GUI仍仅支持可见光预标注、红外浏览。每个批次只属于一个片段、模态和镜头，原帧名与全局样本ID保持不变。禁止在annotations顶层新增算法名或任意试验名目录。

草稿与首次编辑导出使用同一批次编号，`projects/.../<批次>/source.json`记录草稿及manifest哈希。重复导出已有工程时提示打开原工程，不覆盖人工修改；导出中断的工程也保留，不自动重写。修正回读使用新批次，`import_log.json`记录来源工程与JSON哈希。参数独立按配置哈希保存，便于复用。

## 操作流程

1. GUI打开datasets根目录，选片段、模态与镜头，预览并保存到drafts。
2. 点击导出X-AnyLabeling，打开对应projects批次的images文件夹。
3. 修正并保存同名JSON；对新版结构化工程执行：

```powershell
north16 import-labels --project <projects中的批次目录> --changed-only --preview
```

无需指定输出，程序按protocol自动创建corrected批次；去掉`--changed-only`则回读全部图片。JSON变化不代表审核通过。没有修改的工程使用`--changed-only`时可得到0张掩码，这是正常结果。

普通文件夹和旧版多镜头工程缺少dataset.json，仍须显式传入`--output <新目录>`。显式输出兼容既有脚本；数据集外的输出不生成无法解析的dataset-relative samples.txt。旧版多镜头回读保留visible/<镜头>/masks布局，不把旧工程伪装成新版单镜头工程。

4. 所有输出仍为draft/unreviewed或pending_review，完成独立审核后才登记到`sequences/.../masks`并重建正式samples.txt。本版本不提供自动发布gold。

## 清单与历史整理

```powershell
north16 annotations --root E:\Dataset\north16\datasets
north16 annotations --root E:\Dataset\north16\datasets --refresh
north16 annotations --root E:\Dataset\north16\datasets --organize
north16 annotations --root E:\Dataset\north16\datasets --organize --apply
```

默认仅查看；refresh重新生成说明和批次清单。GUI生成草稿、保存参数、导出工程及新版工程回读后刷新清单。清单是辅助导航，不替代根samples.txt、批次manifest或审核记录。

organize仅归档已知的四个历史目录：demo_camera04、grabcut_camera04、grabcut_20260902_044232、xanylabeling_20260902_044232。未知目录原地保留并报告。先检查全部目标冲突与树内链接，再做同卷目录改名；比较每个文件的身份、尺寸和修改时间，失败回移。迁移不改写历史JSON、PNG或其清单，保留编辑哈希；历史文件中的旧绝对路径属于当时的运行记录，迁移日志提供新位置。工程内部相对路径仍可读取，打开脚本默认路径随归档更新。部分旧脚本若硬编码旧路径，需要按迁移映射使用新路径，不能直接重跑历史脚本。

不清理sequences下预留的空masks，也不删除有内容的草稿。datasets与protocol备份分别管理，标注数据不写入Python包。
