"""Sixteen-camera validation: 4x4 by position or three frames side by side."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox,QDialog,QFrame,QGridLayout,QHBoxLayout,
    QLabel,QScrollArea,QTabBar,QVBoxLayout,QWidget)

from north16.gui.camera_overview import Thumbnail

POSITIONS=("开头","中间","末尾")


class SampleValidationDialog(QDialog):
    def __init__(self,report,parent=None):
        super().__init__(parent)
        self.report=report
        self.stale_cameras=set()
        self.camera_labels={}
        self.setWindowTitle("16路验证 · 开头 / 中间 / 末尾")
        self.resize(1480,980)
        layout=QVBoxLayout(self)
        top=QHBoxLayout()
        top.addWidget(QLabel(f"片段 {report['sequence']} · {len(report['cameras'])} 路"),1)
        self.layout_mode=QComboBox()
        self.layout_mode.addItems(["16路总览（4×4）","三帧并排（逐镜头）"])
        self.layout_mode.currentIndexChanged.connect(self.rebuild)
        top.addWidget(self.layout_mode)
        self.display_mode=QComboBox()
        self.display_mode.addItem("叠加结果","overlay");self.display_mode.addItem("彩色掩码","color");self.display_mode.addItem("原图","source")
        self.display_mode.currentIndexChanged.connect(self.rebuild)
        top.addWidget(self.display_mode);layout.addLayout(top)
        self.positions=QTabBar()
        for name in POSITIONS:self.positions.addTab(name)
        self.positions.currentChanged.connect(self.rebuild)
        layout.addWidget(self.positions)
        self.note=QLabel("使用点击验证时各镜头的独立参数；不受导出勾选影响。首/中/末按各路自身帧序号抽样，不代表时间同步，也不是准确率评测。")
        self.note.setWordWrap(True);layout.addWidget(self.note)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self.scroll,1)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.rebuild()

    def rebuild(self):
        if not hasattr(self,"scroll"):return
        old=self.scroll.takeWidget()
        if old:old.deleteLater()
        container=QWidget();grid=QGridLayout(container);grid.setContentsMargins(0,0,0,0);grid.setSpacing(7)
        self.camera_labels={}
        self.visible_samples=[]
        compare=self.layout_mode.currentIndex()==1
        self.positions.setVisible(not compare)
        cameras=sorted(self.report["cameras"],key=lambda r:(0 if r["camera"].startswith("front_") else 1,r["camera"]))
        for i,camera in enumerate(cameras):
            indices=range(3) if compare else [self.positions.currentIndex()]
            for position in indices:
                sample=camera["samples"][position];result=sample["result"]
                frame=QFrame();frame.setStyleSheet("QFrame { background:#f5f8fc; border-radius:5px; }")
                frame.setMinimumHeight(250 if compare else 170)
                box=QVBoxLayout(frame);box.setContentsMargins(6,4,6,4);box.setSpacing(3)
                title=QLabel();title.setProperty("camera",camera["camera"])
                self.camera_labels.setdefault(camera["camera"],[]).append(title)
                box.addWidget(title)
                view=Thumbnail();view.setCursor(Qt.CursorShape.ArrowCursor)
                box.addWidget(view,1)
                if result["status"]=="succeeded":
                    view.set_picture(result[self.display_mode.currentData()])
                    caption=f"{POSITIONS[position]} · {result['image_name']}"
                elif result["status"]=="failed":
                    view.setText("该帧验证失败")
                    caption=f"{POSITIONS[position]} · {result['image_name']} · 失败"
                    frame.setToolTip(result["error"])
                else:
                    view.setText("未计算（任务已停止）")
                    caption=f"{POSITIONS[position]} · {result['image_name']} · 未计算"
                label=QLabel(caption);label.setWordWrap(True);box.addWidget(label)
                frame.setToolTip(frame.toolTip() or result["image"]+"\n参数 "+camera["profile_sha256"][:12])
                grid.addWidget(frame,i if compare else i//4,position if compare else i%4)
                self.visible_samples.append((camera["camera"],sample["position"],result["image_name"]))
        for col in range(3 if compare else 4):grid.setColumnStretch(col,1)
        if not compare:
            for row in range((len(cameras)+3)//4):grid.setRowStretch(row,1)
        self.scroll.setWidget(container)
        self.update_status()

    def update_status(self):
        for camera,labels in self.camera_labels.items():
            for label in labels:
                label.setText(camera+(" · 参数已变，需重新验证" if camera in self.stale_cameras else ""))
                label.setStyleSheet("font-weight:bold;color:"+("#9a6300;" if camera in self.stale_cameras else "#173654;"))
        r=self.report
        self.status.setText(f"{r['status']} · 成功 {r['succeeded']} / {r['expected']} 张不同帧 · 失败 {r['failed']} · 未计算 {r['unprocessed']}"+
                            (f" · {len(self.stale_cameras)}路参数已变化，当前图为旧参数结果" if self.stale_cameras else " · 未审核预览，不生成标签"))

    def mark_profile(self,root,sequence,camera,digest):
        if root!=self.report["dataset_root"] or sequence!=self.report["sequence"]:return
        record=next((r for r in self.report["cameras"] if r["camera"]==camera),None)
        if not record:return
        if digest==record["profile_sha256"]:self.stale_cameras.discard(camera)
        else:self.stale_cameras.add(camera)
        self.update_status()
