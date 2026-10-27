"""Camera grid; selection is independent from the active debugging camera."""
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox,QComboBox,QFrame,QGridLayout,QHBoxLayout,
    QLabel,QPushButton,QScrollArea,QSizePolicy,QSpinBox,QVBoxLayout,QWidget)


class Thumbnail(QLabel):
    clicked=Signal()

    def __init__(self):
        super().__init__("尚未预览")
        self.picture=None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(80,65)
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background:#111b29; color:#b8c9da; border-radius:3px;")

    def set_picture(self, image):
        self.picture=QPixmap.fromImage(ImageQt(image.convert("RGB")))
        self.render_picture()

    def render_picture(self):
        if self.picture is not None:
            self.setPixmap(self.picture.scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.render_picture()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.clicked.emit()
        super().mouseReleaseEvent(event)


class CameraCard(QFrame):
    activated=Signal(str)
    selection_changed=Signal(str,bool)

    def __init__(self,camera,selected):
        super().__init__()
        self.camera=camera
        self.result=None
        self.stale=False
        self.setMinimumHeight(145)
        self.setStyleSheet("CameraCard { background:white; border:1px solid #ced8e3; border-radius:5px; }")
        layout=QVBoxLayout(self);layout.setContentsMargins(6,5,6,5);layout.setSpacing(3)
        header=QHBoxLayout();header.setSpacing(4)
        self.checkbox=QCheckBox(camera)
        self.checkbox.setChecked(selected)
        self.checkbox.setToolTip("勾选后参与批量导出；不影响预览与独立调参")
        self.checkbox.toggled.connect(lambda checked:self.selection_changed.emit(camera,checked))
        header.addWidget(self.checkbox,1)
        self.debug=QPushButton("调试");self.debug.setStyleSheet("padding:2px 6px;")
        self.debug.clicked.connect(lambda:self.activated.emit(camera))
        header.addWidget(self.debug);layout.addLayout(header)
        self.thumbnail=Thumbnail();self.thumbnail.clicked.connect(lambda:self.activated.emit(camera))
        layout.addWidget(self.thumbnail,1)
        self.status=QLabel("尚未生成预览");self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size:11px;color:#526a80;")
        layout.addWidget(self.status)

    def show_result(self,result,mode="overlay",stale=False):
        self.result=result;self.stale=stale
        self.thumbnail.set_picture(result[mode])
        self.status.setText(result["image_name"]+(" · 参数/帧已变，待刷新" if stale else " · 预览完成"))
        self.status.setStyleSheet("font-size:11px;color:"+("#9a6300;" if stale else "#326c59;"))
        self.thumbnail.setToolTip(result["image"]+"\n点击放大调试；"+result["profile_sha256"][:12])

    def show_error(self,message):
        self.result=None;self.thumbnail.picture=None;self.thumbnail.clear();self.thumbnail.setText("预览失败")
        self.status.setText("失败 · "+message[:65]);self.status.setToolTip(message)
        self.status.setStyleSheet("font-size:11px;color:#a33232;")

    def set_active(self,active):
        self.setStyleSheet("CameraCard { background:"+("#eef6ff" if active else "white")+
                          "; border:1px solid "+("#1766b3" if active else "#ced8e3")+"; border-radius:5px; }")


class CameraOverview(QWidget):
    camera_activated=Signal(str)
    selection_changed=Signal()
    preview_requested=Signal()
    estimate_requested=Signal()
    samples_requested=Signal()
    export_requested=Signal()
    frame_changed=Signal()

    def __init__(self):
        super().__init__()
        self.cards={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(5)
        top=QHBoxLayout()
        self.selection_label=QLabel("未打开数据集")
        top.addWidget(self.selection_label,1)
        self.select_all=QPushButton("全选");self.select_none=QPushButton("全不选")
        self.select_all.clicked.connect(lambda:self.set_selection(set(self.cards)))
        self.select_none.clicked.connect(lambda:self.set_selection(set()))
        top.addWidget(self.select_all);top.addWidget(self.select_none)
        layout.addLayout(top)
        tools=QHBoxLayout()
        tools.addWidget(QLabel("预览帧"))
        self.frame_index=QSpinBox();self.frame_index.setRange(0,0);self.frame_index.setFixedWidth(75)
        self.frame_index.valueChanged.connect(self.frame_changed)
        tools.addWidget(self.frame_index)
        self.mode=QComboBox();self.mode.addItem("叠加结果","overlay");self.mode.addItem("彩色掩码","color");self.mode.addItem("原图","source")
        self.mode.currentIndexChanged.connect(self.refresh_mode)
        tools.addWidget(self.mode)
        self.preview_button=QPushButton("刷新全部预览");self.preview_button.clicked.connect(self.preview_requested)
        self.estimate_button=QPushButton("估参并预览全部");self.estimate_button.clicked.connect(self.estimate_requested)
        self.samples_button=QPushButton("验证首 / 中 / 末");self.samples_button.clicked.connect(self.samples_requested)
        tools.addWidget(self.preview_button);tools.addWidget(self.estimate_button);tools.addWidget(self.samples_button)
        layout.addLayout(tools)
        self.hint=QLabel("点击任一路图像或“调试”放大；各路参数独立。勾选仅控制批量导出。帧序号不代表时间同步。")
        self.hint.setWordWrap(True);self.hint.setStyleSheet("color:#47617a;font-size:11px;")
        layout.addWidget(self.hint)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.container=QWidget();self.grid=QGridLayout(self.container);self.grid.setContentsMargins(0,0,0,0);self.grid.setSpacing(6)
        self.scroll.setWidget(self.container);layout.addWidget(self.scroll,1)
        bottom=QHBoxLayout()
        self.summary=QLabel("预览不会生成标签文件")
        bottom.addWidget(self.summary,1)
        self.export_button=QPushButton("导出勾选镜头的标签");self.export_button.setObjectName("primary")
        self.export_button.setToolTip("处理勾选镜头在当前片段中的全部图片，导出JSON标签；不是仅保存当前预览帧。")
        self.export_button.clicked.connect(self.export_requested)
        bottom.addWidget(self.export_button);layout.addLayout(bottom)

    def set_cameras(self,cameras,selected,max_frames):
        while self.grid.count():
            item=self.grid.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.cards={}
        # Keep front and back in separate rows for the standard sixteen streams.
        for i,camera in enumerate(sorted(cameras,key=lambda c:(0 if c.startswith("front_") else 1,c))):
            card=CameraCard(camera,camera in selected)
            card.activated.connect(self.camera_activated)
            card.selection_changed.connect(lambda _camera,_checked:self.update_selection())
            self.cards[camera]=card;self.grid.addWidget(card,i//4,i%4)
        for col in range(4):self.grid.setColumnStretch(col,1)
        self.frame_index.blockSignals(True)
        self.frame_index.setRange(0,max(0,max_frames-1));self.frame_index.setValue(0)
        self.frame_index.blockSignals(False)
        self.update_selection()

    def selected_cameras(self):
        return sorted(camera for camera,card in self.cards.items() if card.checkbox.isChecked())

    def set_selection(self,selected):
        for camera,card in self.cards.items():
            card.checkbox.blockSignals(True);card.checkbox.setChecked(camera in selected);card.checkbox.blockSignals(False)
        self.update_selection()

    def update_selection(self):
        self.selection_label.setText(f"已勾选 {len(self.selected_cameras())} / {len(self.cards)} 路")
        self.selection_changed.emit()

    def refresh_mode(self):
        for card in self.cards.values():
            if card.result:card.show_result(card.result,self.mode.currentData(),card.stale)

    def set_busy(self,active):
        for control in (self.select_all,self.select_none,self.frame_index,self.preview_button,self.estimate_button,self.samples_button,self.export_button):
            control.setEnabled(not active)
        for card in self.cards.values():
            card.checkbox.setEnabled(not active);card.debug.setEnabled(not active)
        self.export_button.setEnabled(not active and bool(self.selected_cameras()))
