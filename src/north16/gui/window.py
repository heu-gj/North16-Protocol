"""North16 v1 folder browser, parameter lab, and draft batch interface."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QThreadPool, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from north16.annotations.profiles import DEFAULT_PROFILE, load_profile, profile_hash
from north16.annotations.workspace import colored, export_editor, list_images, preview, read_image, run_job
from north16.annotations.xanylabeling import save_json
from north16.gui.camera_overview import CameraOverview
from north16.gui.image_view import ImageView
from north16.gui.parameters import Parameters
from north16.gui.workers import Worker


class Window(QMainWindow):
    def __init__(self, folder=None):
        super().__init__()
        self.setWindowTitle("North16 · 海冰预标注工作台")
        self.resize(1500, 940)
        self.images, self.source, self.mask = [], None, None
        self.current_path, self.result_key, self.active_worker = None, None, None
        self.last_output, self.validations = None, {}
        self.estimations, self.last_estimation = {}, None
        self.dataset_workspace, self.stream_key, self.last_dataset = None, None, None
        self.stream_profiles = {}
        self.copied_profile = None
        self.camera_estimations = {}
        self.camera_previews = {}
        self.camera_selections = {}
        self.camera_validations = {}
        self.sample_dialog = None
        self.overview_scope = None
        self._applying_profile = False
        self.label_packages = {}
        self.hover_position = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._syncing = False
        self._build()
        self.setStyleSheet("""
            QMainWindow, QWidget { font-family: 'Microsoft YaHei'; font-size: 12px; }
            QMainWindow { background: #edf2f7; }
            QGroupBox { font-weight: bold; border: 1px solid #ced8e3; border-radius: 7px;
                margin-top: 12px; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; }
            QPushButton { padding: 7px 12px; border: 1px solid #c4d0de; border-radius: 5px; background: white; }
            QPushButton:hover { background: #e1ecfa; }
            QPushButton:disabled { color: #98a4b3; background: #edf1f5; }
            QPushButton#primary { color: white; background: #1766b3; border: none; font-weight: bold; }
            QListWidget { background: white; border: 1px solid #ced8e3; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 4px; }
            QProgressBar { min-height: 16px; border: 1px solid #ced8e3; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background: #3488c8; }
        """)
        if folder:
            self.open_folder(folder)

    def button(self, text, callback, parent, primary=False):
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(callback)
        parent.addWidget(button)
        return button

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        title = QLabel("海冰预标注工作台")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #173654;")
        top.addWidget(title)
        top.addStretch()
        self.sensor_badge = QLabel("VISIBLE  ·  GrabCut  ·  草稿 → 人工修正")
        top.addWidget(self.sensor_badge)
        self.button("使用说明", self.help, top)
        layout.addLayout(top)
        banner = QLabel("流程：打开数据集 → 选择片段 / 镜头 → 调参预览 → 保存 masks/*.json → 整包合并到数据集")
        banner.setStyleSheet("color:#47617a; padding:6px;")
        layout.addWidget(banner)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        left = QWidget()
        left.setMinimumWidth(200)
        left.setMaximumWidth(280)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        self.dataset_button = self.button("打开数据集 / 标注工作区", self.choose_dataset, left_layout, True)
        self.sequence_combo, self.camera_combo = QComboBox(), QComboBox()
        self.sensor_combo = QComboBox()
        self.sensor_combo.addItem("可见光 visible", "visible")
        self.sensor_combo.addItem("红外 infrared", "infrared")
        self.sequence_combo.setPlaceholderText("片段")
        self.camera_combo.setPlaceholderText("镜头")
        left_layout.addWidget(self.sequence_combo)
        left_layout.addWidget(self.sensor_combo)
        left_layout.addWidget(self.camera_combo)
        self.sensor_combo.currentIndexChanged.connect(self.select_sensor)
        self.sequence_combo.currentTextChanged.connect(self.select_sequence)
        self.camera_combo.currentTextChanged.connect(self.select_stream)
        self.open_button = self.button("打开普通图片文件夹", lambda: self.choose_folder(), left_layout)
        self.folder_label = QLabel("请选择直接包含图片的文件夹")
        self.folder_label.setMinimumWidth(0)
        self.folder_label.setMaximumWidth(260)
        self.folder_label.setWordWrap(True)
        left_layout.addWidget(self.folder_label)
        self.files = QListWidget()
        self.files.currentRowChanged.connect(self.select_image)
        left_layout.addWidget(self.files, 1)
        navigation = QHBoxLayout()
        self.previous_button = self.button("← 上一张", lambda: self.move(-1), navigation)
        self.next_button = self.button("下一张 →", lambda: self.move(1), navigation)
        left_layout.addLayout(navigation)
        self.count_label = QLabel("0张图片")
        left_layout.addWidget(self.count_label)
        splitter.addWidget(left)

        middle = QWidget()
        center_layout = QVBoxLayout(middle)
        center_layout.setContentsMargins(4, 0, 4, 0)
        toolbar = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["叠加结果", "彩色掩码", "仅原图"])
        self.mode.currentIndexChanged.connect(self.refresh_display)
        toolbar.addWidget(self.mode)
        self.horizon_toggle = QCheckBox("编辑地平线")
        self.horizon_toggle.setChecked(True)
        self.horizon_toggle.toggled.connect(self.update_horizon)
        toolbar.addWidget(self.horizon_toggle)
        self.horizon_mode = QComboBox()
        self.horizon_mode.addItem("两点直线", "line")
        self.horizon_mode.addItem("多点折线", "polyline")
        self.horizon_mode.setToolTip("两点直线：上下拖动左右端点，调整高度和倾斜。\n"
                                    "切为直线保留当前两端位置，移除中间控制点；切回折线沿直线补为5点。")
        self.horizon_mode.currentIndexChanged.connect(self.change_horizon_mode)
        toolbar.addWidget(self.horizon_mode)
        self.button("适应窗口", self.fit_views, toolbar)
        toolbar.addStretch()
        center_layout.addLayout(toolbar)
        captions = QHBoxLayout()
        captions.addWidget(QLabel("原图 · 拖动黄色控制点调整地平线"))
        captions.addWidget(QLabel("结果 · 滚轮缩放 / 拖动画布平移"))
        center_layout.addLayout(captions)
        views = QSplitter(Qt.Orientation.Horizontal)
        self.original_view, self.result_view = ImageView(), ImageView()
        views.addWidget(self.original_view)
        views.addWidget(self.result_view)
        center_layout.addWidget(views, 1)
        self.original_view.changed.connect(self.parameter_changed)
        for source, target in [(self.original_view, self.result_view), (self.result_view, self.original_view)]:
            source.transform_changed.connect(lambda s=source, t=target: self.sync_views(s, t))
            source.horizontalScrollBar().valueChanged.connect(lambda _v, s=source, t=target: self.sync_views(s, t))
            source.verticalScrollBar().valueChanged.connect(lambda _v, s=source, t=target: self.sync_views(s, t))
        display = QHBoxLayout()
        display.addWidget(QLabel("叠加透明度"))
        self.alpha = QSlider(Qt.Orientation.Horizontal)
        self.alpha.setRange(0, 100)
        self.alpha.setValue(42)
        self.alpha.valueChanged.connect(self.refresh_display)
        display.addWidget(self.alpha)
        self.visibility = {}
        for value, text in [(0, "天空"), (1, "水"), (2, "冰"), (3, "其他"), (255, "忽略")]:
            box = QCheckBox(text)
            box.setChecked(True)
            box.toggled.connect(self.refresh_display)
            display.addWidget(box)
            self.visibility[value] = box
        center_layout.addLayout(display)
        self.result_label = QLabel("尚未运行预览")
        self.result_label.setWordWrap(True)
        center_layout.addWidget(self.result_label)
        self.pixel_label = QLabel("像素：将鼠标移到原图或结果图上查看")
        self.pixel_label.setWordWrap(True)
        self.pixel_label.setMinimumHeight(52)
        self.pixel_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pixel_label.setStyleSheet("color:#173654; background:#e5edf5; padding:6px; border-radius:4px;")
        self.pixel_label.setToolTip("坐标从左上角(0,0)开始。RGB取原图原尺寸像素；亮度=(R+G+B)/3，与冰水阈值一致。掩码读数来自当前显示的分割结果。")
        center_layout.addWidget(self.pixel_label)
        for view in (self.original_view, self.result_view):
            view.pixel_hovered.connect(lambda x,y,v=view: self.inspect_pixel(v,x,y))
        self.center_tabs = QTabWidget()
        self.center_tabs.addTab(middle,"单镜头调试")
        self.overview = CameraOverview()
        self.center_tabs.addTab(self.overview,"16路总览 / 勾选导出")
        self.overview.camera_activated.connect(self.debug_camera)
        self.overview.selection_changed.connect(self.remember_camera_selection)
        self.overview.preview_requested.connect(self.run_camera_previews)
        self.overview.estimate_requested.connect(self.run_camera_estimation)
        self.overview.samples_requested.connect(self.run_camera_samples)
        self.overview.export_requested.connect(self.run_camera_batch)
        self.overview.frame_changed.connect(self.overview_frame_changed)
        self.center_tabs.currentChanged.connect(self.overview_tab_changed)
        splitter.addWidget(self.center_tabs)

        right_scroll = QScrollArea()
        right_scroll.setMinimumWidth(330)
        right_scroll.setMaximumWidth(390)
        right_scroll.setWidgetResizable(True)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        group = QGroupBox("1  分割参数")
        self.parameter_group=group
        group_layout = QVBoxLayout(group)
        self.parameters = Parameters()
        self.parameters.changed.connect(self.parameter_changed)
        group_layout.addWidget(self.parameters)
        self.keep_horizon = QCheckBox("自动估计时保留当前地平线")
        self.keep_horizon.setChecked(True)
        self.keep_horizon.setToolTip("默认只自动调整冰水阈值。先拖动黄色控制点定位地平线；取消勾选仅尝试启发式候选，模糊图像可能无法定位。")
        group_layout.addWidget(self.keep_horizon)
        self.estimate_button = self.button("自动估计参数并预览", self.run_estimation, group_layout, True)
        self.estimate_label = QLabel("先定位黄色地平线；默认自动估计仅调整冰水阈值")
        self.estimate_label.setWordWrap(True)
        self.estimate_label.setStyleSheet("color:#47617a; font-weight:normal;")
        group_layout.addWidget(self.estimate_label)
        self.estimate_details_button = self.button("查看最近估计依据", self.show_estimation, group_layout)
        self.preview_button = self.button("运行当前图片预览", self.run_preview, group_layout, True)
        self.sample_button = self.button("验证开头 / 中间 / 末尾", self.run_samples, group_layout)
        self.reset_button = self.button("恢复默认参数", lambda: self.apply_profile(DEFAULT_PROFILE), group_layout)
        right_layout.addWidget(group)
        group = QGroupBox("2  配置版本")
        config_layout = QVBoxLayout(group)
        self.note = QLineEdit()
        self.note.setPlaceholderText("适用镜头 / 场景备注，例如 back_04 白天")
        config_layout.addWidget(self.note)
        self.load_button = self.button("加载参数 JSON", self.load_parameters, config_layout)
        self.save_button = self.button("保存参数及验证记录", self.save_parameters, config_layout)
        transfer_row = QHBoxLayout()
        self.copy_profile_button = self.button("复制当前参数", self.copy_parameters, transfer_row)
        self.paste_profile_button = self.button("粘贴到当前镜头", self.paste_parameters, transfer_row)
        config_layout.addLayout(transfer_row)
        self.apply_all_profiles_button = self.button("当前参数应用到本片段全部镜头", self.apply_parameters_to_all_cameras, config_layout)
        self.profile_clipboard_label = QLabel("未复制参数；复制后可切换镜头粘贴。")
        self.profile_clipboard_label.setWordWrap(True)
        self.profile_clipboard_label.setStyleSheet("color:#47617a; font-weight:normal;")
        config_layout.addWidget(self.profile_clipboard_label)
        self.copy_profile_button.setToolTip("复制完整分割参数快照（含地平线、海面模式、阈值），在当前窗口中保留。跨次启动复用请保存参数JSON。")
        self.paste_profile_button.setToolTip("用已复制的参数替换当前镜头参数；不复制来源镜头的预览、估参依据或验证记录。")
        self.apply_all_profiles_button.setToolTip("使用右侧当前参数，替换当前片段所有已加载visible镜头参数，包括未勾选镜头；其他片段和infrared不受影响。")
        right_layout.addWidget(group)
        group = QGroupBox("3  生成与人工修正")
        batch_layout = QVBoxLayout(group)
        self.output_field = QLineEdit()
        self.output_field.setPlaceholderText("本次输出的新目录")
        batch_layout.addWidget(self.output_field)
        self.output_button = self.button("选择输出位置", self.choose_output, batch_layout)
        self.save_current_button = self.button("保存当前图片结果", self.save_current, batch_layout)
        self.batch_button = self.button("按当前参数处理整个文件夹", self.run_batch, batch_layout, True)
        parallel_row = QHBoxLayout()
        parallel_row.addWidget(QLabel("并发镜头数"))
        self.parallel_workers = QSpinBox()
        self.parallel_workers.setRange(1,16)
        self.parallel_workers.setValue(4)
        parallel_row.addWidget(self.parallel_workers)
        batch_layout.addLayout(parallel_row)
        self.parallel_estimate = QCheckBox("生成前各镜头独立自动估参")
        self.parallel_estimate.setChecked(False)
        batch_layout.addWidget(self.parallel_estimate)
        self.estimate_cameras_button = self.button("本片段各镜头：估参并预览", self.run_camera_estimation, batch_layout)
        self.parallel_button = self.button("导出勾选镜头的标签", self.run_camera_batch, batch_layout, True)
        self.parallel_button.setToolTip("处理勾选镜头在当前片段中的全部图片；已有标签时自动使用新的标签包。")
        parallel_hint = QLabel("仅处理当前片段的可见光镜头；每路抽样首/中/末帧。保留各自地平线，未调过的镜头使用默认线，需检查。")
        parallel_hint.setWordWrap(True)
        parallel_hint.setStyleSheet("color:#47617a; font-weight:normal;")
        batch_layout.addWidget(parallel_hint)
        self.export_button = self.button("查看最近标签包", self.run_export, batch_layout)
        self.open_output_button = self.button("打开最近输出目录", self.open_output, batch_layout)
        warning = QLabel("预标注不代表完成审核。other需人工补画；暗色薄冰、反光和船体可能误分。当前类别仍为天空 / 水 / 冰 / 其他。")
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #78552c; padding: 6px;")
        batch_layout.addWidget(warning)
        right_layout.addWidget(group)
        right_layout.addStretch()
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)
        splitter.setSizes([235, 925, 340])
        bottom = QHBoxLayout()
        self.status_label = QLabel("就绪")
        bottom.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        bottom.addWidget(self.progress, 1)
        self.stop_button = self.button("停止任务", self.stop, bottom)
        self.stop_button.setEnabled(False)
        layout.addLayout(bottom)
        self.apply_profile(DEFAULT_PROFILE)
        self.busy(False)
        for key, delta in [(Qt.Key.Key_Left, -1), (Qt.Key.Key_Right, 1)]:
            action = QAction(self)
            action.setShortcut(key)
            action.triggered.connect(lambda _checked=False, d=delta: self.move(d))
            self.addAction(action)

    def help(self):
        QMessageBox.information(self, "使用方法", "1.打开north16数据集根目录（包含protocol/classes/samples.txt和sequences），选择片段及可见光镜头；也支持普通图片文件夹。\n"
            "可在左侧切换可见光/红外；红外支持8位显示PNG浏览与像素值查看，尚不提供当前可见光算法的分割或估参。\n"
            "2.在左图上下拖动黄色地平线控制点，右侧调整阈值，点击预览。\n"
            "地平线可选两点直线：拖动左右端点调整高度和倾斜；多点折线可用于弯曲边界。\n"
            "自动估计默认保留当前地平线，仅估计冰水阈值；取消保留后仅尝试地平线候选，有歧义时不替换。\n"
            "仅有冰或仅有水时选择对应海面模式。此时不运行冰水二分，海面按指定类别填充；混合帧需切回混合模式。\n"
            "3.参数变化后旧结果会标记过期，需重新预览。\n"
            "配置版本中可复制当前参数，切换镜头后粘贴；也可将当前参数应用到本片段全部可见光镜头（不受勾选限制）。参数JSON可跨次启动保存/加载。\n"
            "4.多图验证只显示预标注一致性预览，不代表准确率；保存配置保留来源和哈希。\n"
            "5.annotation工作区：保存按钮将JSON写到同镜头masks，图片保留在images；导出图片＋标签整包后用import-package导入最终数据集。\n"
            "6.旧数据集模式仍生成独立标签包。整包校验导入后可由Dataset读取；已有标签不覆盖。\n"
            "7.取消会在当前图片计算结束后生效，已完成文件保留。\n"
            "8.切换16路总览可同时查看各镜头结果，点击卡片独立调试。勾选控制批量保存和整包交付范围。工作区已有标签会拒绝重新生成，请保留人工修改。")

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择直接包含图片的文件夹")
        if folder:
            self.open_folder(folder)

    def choose_dataset(self):
        folder = QFileDialog.getExistingDirectory(self, "选择north16数据集根目录（包含samples.txt）")
        if folder:
            self.open_dataset(folder)

    def remember_stream(self):
        if self.dataset_workspace and self.stream_key:
            try:
                self.stream_profiles[(str(self.dataset_workspace.root), self.stream_key)] = self.current_profile()
            except ValueError:
                pass

    def current_sensor(self):
        return self.stream_key[1] if self.stream_key else self.sensor_combo.currentData()

    def select_sensor(self, _index):
        if self.active_worker:
            return
        if self.dataset_workspace:
            self.select_sequence(self.sequence_combo.currentText(), self.camera_combo.currentText())
        else:
            self.last_estimation = None
            self.mask, self.result_key, self.hover_position = None, None, None
            self.refresh_display()
            self.busy(False)
            self.require_visible()

    def require_visible(self):
        if self.current_sensor() == "infrared":
            self.status_label.setText("红外浏览模式：可查看图片和像素值；当前可见光分割/估参尚未适配红外")
            return False
        return True

    def open_dataset(self, root, preferred=None):
        if self.active_worker:
            return
        try:
            from north16.annotations.dataset_workspace import DatasetWorkspace
            workspace = DatasetWorkspace(root)
            keys = workspace.keys(None)
            if not keys:
                raise ValueError("该数据集没有相机图像样本")
        except Exception as exc:
            self.error(str(exc));return
        self.remember_stream()
        self.dataset_workspace, self.stream_key = workspace, None
        sensor = preferred[1] if preferred and preferred in keys else "visible" if workspace.keys() else "infrared"
        self.sensor_combo.blockSignals(True)
        self.sensor_combo.setCurrentIndex(self.sensor_combo.findData(sensor))
        self.sensor_combo.blockSignals(False)
        for combo in (self.sequence_combo, self.camera_combo):
            combo.blockSignals(True);combo.clear();combo.blockSignals(False)
        sequences = sorted({key[0] for key in keys})
        self.sequence_combo.blockSignals(True)
        self.sequence_combo.addItems(sequences)
        self.sequence_combo.setCurrentText(preferred[0] if preferred and preferred in keys else sequences[0])
        self.sequence_combo.blockSignals(False)
        self.select_sequence(self.sequence_combo.currentText(), preferred[2] if preferred and preferred in keys else None)
        self.busy(False)

    def select_sequence(self, sequence, preferred=None):
        if not self.dataset_workspace or not sequence:
            return
        sensor = self.sensor_combo.currentData()
        keys = [key for key in self.dataset_workspace.keys(None) if key[0] == sequence]
        sensors = {key[1] for key in keys}
        if sensor not in sensors:
            sensor = "visible" if "visible" in sensors else "infrared"
            self.sensor_combo.blockSignals(True)
            self.sensor_combo.setCurrentIndex(self.sensor_combo.findData(sensor))
            self.sensor_combo.blockSignals(False)
        cameras = [key[2] for key in keys if key[1] == sensor]
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear();self.camera_combo.addItems(cameras)
        self.camera_combo.setCurrentIndex(0)
        if preferred in cameras:
            self.camera_combo.setCurrentText(preferred)
        self.camera_combo.blockSignals(False)
        self.select_stream(self.camera_combo.currentText())

    def select_stream(self, camera):
        if not self.dataset_workspace or not camera or self.active_worker:
            return
        self.remember_stream()
        key = (self.sequence_combo.currentText(), self.sensor_combo.currentData(), camera)
        try:
            images = self.dataset_workspace.images(key)
        except Exception as exc:
            self.stream_key = None
            self.files.clear();self.images=[];self.current_path=None;self.mask=None
            self.error(str(exc));return
        self.stream_key = key
        self.parameter_group.setTitle("1  分割参数 · "+camera)
        self.last_estimation = None
        self.apply_profile(self.stream_profiles.get((str(self.dataset_workspace.root), key), DEFAULT_PROFILE))
        self.show_images(images[0].parent, images)
        self.last_estimation = self.estimation_for_profile(self.current_profile())
        self.count_label.setText(f"{key[0]} / {key[1]} / {camera}\n{len(images)}张" + (" · 红外浏览" if key[1] == "infrared" else " · 每镜头独立参数"))
        self.folder_label.setText(str(self.dataset_workspace.root))
        self.folder_label.setToolTip(str(images[0].parent))
        self.set_dataset_output()
        self.rebuild_overview()
        self.restore_camera_preview()
        self.busy(False)

    def set_dataset_output(self):
        annotation=self.annotation_mode()
        if self.dataset_workspace and self.stream_key:
            root = self.dataset_workspace.root
            output = root if annotation else self.label_packages.setdefault(str(root), root.parent / "labels" / self.dataset_workspace.new_run_id())
            self.output_field.setText(str(output))
            self.output_field.setToolTip("工作区就地保存：sequences/.../masks/*.json；图片位于同镜头images。" if annotation else
                                         "整包导出位置；不同片段/镜头共用。标签位于dataset/sequences/.../masks/*.json")
        self.output_field.setReadOnly(self.dataset_workspace is not None)
        self.output_button.setEnabled(not annotation)
        self.export_button.setText("导出图片＋标签整包" if annotation else "查看最近标签包")
        self.parallel_button.setText("保存勾选镜头的标签" if annotation else "导出勾选镜头的标签")
        self.parallel_button.setToolTip("保存到工作区同镜头masks；已有标签拒绝覆盖。完成后用下方按钮导出图片＋标签整包。" if annotation else
                                       "处理勾选镜头在当前片段中的全部图片；已有标签时自动使用新的标签包。")

    def annotation_mode(self):
        return bool(self.dataset_workspace and self.dataset_workspace.info.get("workspace_role")=="annotation")

    def open_folder(self, folder):
        if self.active_worker:
            return
        path = Path(folder).resolve()
        if (path / "samples.txt").is_file() or (path / "protocol.txt").is_file():
            self.open_dataset(path);return
        root = next((p for p in path.parents if (p/"samples.txt").is_file() and (p/"protocol.txt").is_file()), None)
        if root is not None:
            parts = path.relative_to(root).parts
            if len(parts) == 5 and parts[0] == "sequences" and parts[-1] == "images":
                self.open_dataset(root, preferred=(parts[1], parts[2], parts[3]));return
        try:
            images = list_images(folder)
        except Exception as exc:
            self.error(str(exc));return
        self.remember_stream()
        self.dataset_workspace, self.stream_key = None, None
        self.parameter_group.setTitle("1  分割参数")
        self.camera_previews.clear()
        self.overview_scope=None
        self.center_tabs.setCurrentIndex(0)
        for combo in (self.sequence_combo, self.camera_combo):
            combo.blockSignals(True);combo.clear();combo.blockSignals(False)
        self.apply_profile(DEFAULT_PROFILE)
        self.last_estimation = None
        self.show_images(folder, images)
        self.output_field.setReadOnly(False)
        self.busy(False)

    def show_images(self, folder, images):
        self.images = images
        self.files.blockSignals(True)
        self.files.clear()
        self.files.addItems([p.name for p in images])
        self.files.blockSignals(False)
        self.folder_label.setText(str(Path(folder).resolve()))
        self.folder_label.setToolTip(str(Path(folder).resolve()))
        self.files.setCurrentRow(0)
        self.count_label.setText(f"共 {len(images)} 张 · 当前镜头独立调参")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        parent = Path(folder).resolve()
        # Standard roots get a sibling draft below annotations; plain folders
        # get a sibling result, never children inside the source images folder.
        dataset = next((p for p in parent.parents if (p/"samples.txt").is_file() and (p/"sequences").is_dir()), None)
        output = dataset / "annotations" / f"grabcut_gui_{parent.parent.name}_{stamp}" if dataset else parent.parent / f"{parent.name}_grabcut_{stamp}"
        self.output_field.setText(str(output))

    def select_image(self, index):
        if not 0 <= index < len(self.images):
            return
        self.hover_position = None
        self.refresh_pixel_readout()
        try:
            source = read_image(self.images[index])
        except Exception as exc:
            self.source, self.mask, self.current_path = None, None, None
            self.error(str(exc));return
        self.current_path, self.source, self.mask, self.result_key = self.images[index], source, None, None
        self.original_view.set_image(source, reset=True)
        self.result_view.set_image(source, reset=True)
        self.update_horizon()
        self.result_label.setText(f"{self.current_path.name} · {source.width} × {source.height} · 尚未运行预览")
        self.estimate_label.setText("请确认当前黄色线的位置；自动估计默认保留该线，只调整冰水阈值")
        self.restore_camera_preview()
        if self.current_sensor() == "infrared":
            self.status_label.setText("红外浏览模式 · 像素值为视频显示值，未经辐射定标，不能视为温度")

    def move(self, delta):
        if not self.active_worker:
            index = self.files.currentRow()+delta
            if 0 <= index < len(self.images):
                self.files.setCurrentRow(index)

    def current_profile(self):
        return self.parameters.get_profile(self.original_view.points)

    def estimation_for_profile(self, profile):
        digest=profile_hash(profile)
        if self.dataset_workspace and self.stream_key:
            report=self.camera_estimations.get((str(self.dataset_workspace.root),self.stream_key))
            if report and report.get("profile_sha256")==digest:return report
            report=self.estimations.get(digest)
            # A shared parameter hash does not identify a camera or its source.
            if (report and report.get("source_image") and self.current_path and
                    Path(report["source_image"]).parent==self.current_path.parent):return report
            return None
        return self.estimations.get(digest)

    def apply_profile(self, profile):
        self._applying_profile=True
        try:
            self.parameters.set_profile(profile)
            self.original_view.set_horizon(profile["horizon_normalized_xy"], profile["horizon_ignore_half_height"], self.horizon_toggle.isChecked())
        finally:
            self._applying_profile=False
        self.parameter_changed()

    def update_horizon(self):
        self.original_view.set_horizon(self.original_view.points or deepcopy(DEFAULT_PROFILE["horizon_normalized_xy"]),
            self.parameters.inputs["band"].value()/100, self.horizon_toggle.isChecked() and self.current_sensor() != "infrared")
        self.sync_horizon_mode()

    def sync_horizon_mode(self):
        mode = "line" if len(self.original_view.points) == 2 else "polyline"
        self.horizon_mode.blockSignals(True)
        self.horizon_mode.setCurrentIndex(self.horizon_mode.findData(mode))
        self.horizon_mode.blockSignals(False)

    def change_horizon_mode(self):
        self.original_view.set_horizon_mode(self.horizon_mode.currentData())

    def parameter_changed(self):
        self.sync_horizon_mode()
        if self._applying_profile:return
        self.original_view.band = self.parameters.inputs["band"].value()/100
        self.original_view.viewport().update()
        if self.mask is not None:
            self.result_label.setText("参数已变化 · 右图为上次结果，请重新运行预览")
        self.status_label.setText("参数已更新，点击预览计算")
        if self.last_estimation and hasattr(self, "estimate_label"):
            self.estimate_label.setText("参数已调整 · 自动估计仅作起点，需重新预览")
        self.refresh_pixel_readout()
        self.mark_current_card_stale()
        self.mark_sample_validation_stale()

    def inspect_pixel(self, view, x, y):
        if x < 0 or y < 0:
            self.hover_position = None
        else:
            self.hover_position = (view, x, y)
        self.refresh_pixel_readout()

    def refresh_pixel_readout(self):
        if not hasattr(self, "pixel_label"):
            return
        if self.hover_position is None or self.source is None:
            self.pixel_label.setText("像素：将鼠标移到原图或结果图上查看")
            return
        view, x, y = self.hover_position
        if not (0 <= x < self.source.width and 0 <= y < self.source.height):
            self.pixel_label.setText("像素：鼠标位于图像范围外")
            return
        r,g,b = self.source.getpixel((x,y))
        origin = "原图" if view is self.original_view else "结果图"
        text = f"{origin}位置  x={x}  y={y}  |  原图 RGB=({r}, {g}, {b})  |  亮度均值={(r+g+b)/3:.1f}"
        if self.current_sensor() == "infrared":
            text += "（红外显示值，非温度）"
        if self.mask is None:
            text += "\n掩码：尚未生成"
        else:
            value = int(self.mask[y,x])
            name = {0:"天空 sky", 1:"水 water", 2:"冰 ice", 3:"其他 other", 255:"忽略 ignore"}.get(value,"未知类别")
            try:
                current = self.result_key == (str(self.current_path), profile_hash(self.current_profile()))
            except ValueError:
                current = False
            text += f"\n掩码：{value}（{name}）" + ("" if current else " · 上次结果，参数已变化")
        self.pixel_label.setText(text)

    def sync_views(self, source, target):
        if self._syncing:
            return
        self._syncing = True
        target.setTransform(source.transform())
        target.horizontalScrollBar().setValue(source.horizontalScrollBar().value())
        target.verticalScrollBar().setValue(source.verticalScrollBar().value())
        self._syncing = False

    def fit_views(self):
        self.original_view.fit()
        self.result_view.fit()

    def refresh_display(self):
        if self.source is None:
            return
        result = self.source
        if self.mask is not None and self.mode.currentIndex() != 2:
            color = colored(self.mask)
            result = color if self.mode.currentIndex() == 1 else Image.blend(self.source, color, self.alpha.value()/100)
            hidden = np.zeros(self.mask.shape, bool)
            for value, box in self.visibility.items():
                if not box.isChecked():
                    hidden |= self.mask == value
            if hidden.any():
                pixels = np.array(result)
                pixels[hidden] = np.array(self.source)[hidden]
                result = Image.fromarray(pixels)
        self.result_view.set_image(result)
        self.refresh_pixel_readout()

    def busy(self, active):
        for widget in [self.open_button, self.files, self.previous_button, self.next_button, self.parameters,
                       self.preview_button, self.sample_button, self.reset_button, self.load_button,
                       self.save_button, self.save_current_button, self.batch_button, self.output_field,
                       self.output_button, self.export_button, self.horizon_toggle]:
            widget.setEnabled(not active)
        self.estimate_button.setEnabled(not active)
        self.keep_horizon.setEnabled(not active)
        self.dataset_button.setEnabled(not active)
        self.sequence_combo.setEnabled(not active and self.dataset_workspace is not None)
        self.camera_combo.setEnabled(not active and self.dataset_workspace is not None)
        self.output_button.setEnabled(not active and not self.annotation_mode())
        self.sensor_combo.setEnabled(not active)
        for control in (self.parallel_workers,self.parallel_estimate,self.estimate_cameras_button,self.parallel_button):
            control.setEnabled(not active and self.dataset_workspace is not None and self.current_sensor() != "infrared")
        overview_enabled=self.dataset_workspace is not None and self.current_sensor() != "infrared"
        self.center_tabs.setTabEnabled(1,overview_enabled)
        if not overview_enabled:self.center_tabs.setCurrentIndex(0)
        self.overview.set_busy(active or not overview_enabled)
        self.parallel_button.setEnabled(not active and overview_enabled and bool(self.overview.selected_cameras()))
        infrared = self.current_sensor() == "infrared"
        self.sample_button.setText("验证16路：开头 / 中间 / 末尾" if self.dataset_workspace else "验证开头 / 中间 / 末尾")
        self.sensor_badge.setText("INFRARED  ·  图片 / 像素浏览" if infrared else "VISIBLE  ·  GrabCut  ·  草稿 → 人工修正")
        for control in (self.parameters, self.preview_button, self.sample_button, self.estimate_button,
                        self.reset_button, self.load_button, self.save_button, self.save_current_button,
                        self.batch_button, self.export_button, self.keep_horizon):
            control.setEnabled(not active and not infrared)
        self.copy_profile_button.setEnabled(not active and not infrared)
        self.paste_profile_button.setEnabled(not active and not infrared and self.copied_profile is not None)
        self.apply_all_profiles_button.setEnabled(not active and not infrared and self.dataset_workspace is not None and self.stream_key is not None)
        self.export_button.setEnabled(not active and (self.annotation_mode() or not infrared))
        self.horizon_toggle.setEnabled(not active and not infrared)
        self.horizon_mode.setEnabled(not active and not infrared)
        self.original_view.set_horizon(self.original_view.points, self.original_view.band,
                                       self.horizon_toggle.isChecked() and not infrared)
        if infrared:
            self.estimate_label.setText("红外浏览：支持图片、缩放和平移、像素读数。当前可见光亮度分割尚未适配红外。")
        self.original_view.setInteractive(not active)
        self.stop_button.setEnabled(active)

    def start(self, function, on_result, label):
        if self.active_worker:
            return
        worker = Worker(function)
        self.active_worker = worker
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(self.error)
        worker.signals.progress.connect(self.task_progress)
        worker.signals.finished.connect(self.finished)
        self.busy(True)
        self.progress.setRange(0, 0)
        self.status_label.setText(label)
        self.pool.start(worker)

    def finished(self):
        self.active_worker = None
        self.busy(False)
        maximum=self.progress.maximum()
        percent=round(100*max(0,self.progress.value())/maximum) if maximum else 0
        self.progress.setRange(0, 100)
        self.progress.setValue(percent)

    def task_progress(self, done, total, name):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status_label.setText(f"{done}/{total} · {name}")

    def error(self, message):
        self.status_label.setText("操作失败，详见提示")
        box = QMessageBox(self)
        box.setWindowTitle("无法完成操作")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(message.strip().splitlines()[-1][:350])
        box.setDetailedText(message)
        box.exec()

    def run_preview(self):
        if not self.require_visible():
            return
        if self.current_path is None:
            self.error("请先打开一张图片");return
        try:
            profile = self.current_profile()
        except Exception as exc:
            self.error(str(exc));return
        path = self.current_path
        key = (str(path), profile_hash(profile))
        def compute(cancel, progress):
            mask = preview(path, profile)
            return None if cancel.is_set() else mask
        def complete(mask):
            if mask is None:
                self.status_label.setText("预览已取消");return
            self.mask, self.result_key = mask, key
            self.refresh_display()
            self.progress.setRange(0, 100);self.progress.setValue(100)
            counts = " / ".join(f"{name} {np.count_nonzero(mask == value)/mask.size:.1%}" for value, name in [(0,"天空"),(1,"水"),(2,"冰"),(255,"忽略")])
            self.result_label.setText(f"{path.name} · 参数 {key[1][:10]} · {counts}")
            self.cache_current_preview(profile,path,mask)
            self.status_label.setText("预览完成 · 草稿，需人工复核")
        self.start(compute, complete, "正在计算当前图片…")

    def run_estimation(self):
        if not self.require_visible():
            return
        if self.current_path is None:
            self.error("请先打开一张图片");return
        from north16.annotations.estimation import estimate_parameters
        from north16.annotations.grabcut import digest
        from north16.annotations.profiles import validate_profile
        path = self.current_path
        try:
            base = self.current_profile()
        except ValueError:
            # Automatic estimation can also recover invalid threshold edits.
            base = deepcopy(DEFAULT_PROFILE)
            base["sea_mode"] = self.parameters.sea_mode.currentData()
            base["horizon_normalized_xy"] = deepcopy(self.original_view.points)
            try:
                base = validate_profile(base)
            except ValueError:
                base = deepcopy(DEFAULT_PROFILE)
        keep = self.keep_horizon.isChecked()
        def compute(cancel, progress):
            suggested, report = estimate_parameters(path, base, keep_horizon=keep)
            progress(1, 2, "参数估计完成，正在生成预览")
            if cancel.is_set():
                return None
            try:
                mask = preview(path, suggested)
                failure = None
            except ValueError as exc:
                mask, failure = None, str(exc)
            if digest(path) != report["source_image_sha256"]:
                raise ValueError("预览期间原图发生变化，请重新加载")
            report.update(preview_status="failed" if failure else "succeeded", preview_error=failure)
            return None if cancel.is_set() else (suggested, report, mask, failure)
        def complete(result):
            if result is None:
                self.status_label.setText("自动估计已取消，原参数保留");return
            suggested, report, mask, failure = result
            self.apply_profile(suggested)
            self.last_estimation = report
            key = profile_hash(suggested)
            self.estimations[key] = report
            if self.dataset_workspace and self.stream_key:
                self.camera_estimations[(str(self.dataset_workspace.root),self.stream_key)]=report
            self.mask = mask
            if mask is not None:self.cache_current_preview(suggested,path,mask)
            self.result_key = (str(path), key) if mask is not None else None
            self.refresh_display()
            a, b, c = [suggested[k] for k in ["water_definite_brightness_max", "water_probable_brightness_max", "ice_definite_brightness_min"]]
            mode = suggested["sea_mode"]
            mode_text = "亮度阈值 %s / %s / %s" % (a,b,c) if mode == "mixed" else "全冰模式：海面填冰，不做冰水二分" if mode == "ice_only" else "全水模式：海面填水，不做冰水二分"
            line = "保留当前地平线（请确认位置）" if keep else "无法可靠定位，保留当前线" if report["horizon"]["status"] == "retained" else "地平线候选（需人工确认）"
            self.estimate_label.setText(f"{path.name} · {line}\n{mode_text}\n" +
                ("估计依据较弱或部分参数保留原值；请检查预览。" if report["warnings"] else "起始参数已生成，请检查冰水边界和地平线。"))
            self.estimate_label.setToolTip("\n".join(report["warnings"]) or report["caveat"])
            if failure:
                self.result_label.setText("参数已估计，但预览失败。请调整参数后重新预览。")
                self.estimate_label.setToolTip(failure)
            else:
                self.result_label.setText(f"{path.name} · 自动建议参数 {key[:10]} · 未经人工审核")
            self.progress.setRange(0, 100);self.progress.setValue(100)
            self.status_label.setText("自动估计完成 · 建议参数可修改，批量前请进行多图验证")
        self.start(compute, complete, "正在分析当前图片的地平线与海域亮度…")

    def show_estimation(self):
        if self.last_estimation is None:
            QMessageBox.information(self, "自动估计依据", "请先对当前图片运行自动估计。")
            return
        report = self.last_estimation
        box = QMessageBox(self)
        box.setWindowTitle("自动估计依据 · 不是准确率")
        if report.get("method")=="per_camera_three_frame_consensus_v1":
            box.setText(f"镜头：{report['camera']}\n地平线：{report['horizon']['status']}\n"
                        f"亮度：{report['brightness']['status']}\n\n"+"\n".join(report["warnings"]))
            box.setDetailedText(json.dumps(report,ensure_ascii=False,indent=2))
            box.exec()
            return
        box.setText(f"来源：{Path(report['source_image']).name}\n"
            f"地平线：{report['horizon']['reason']}\n亮度：{report['brightness']['reason']}\n\n{report['caveat']}")
        box.setDetailedText(json.dumps(report, ensure_ascii=False, indent=2))
        box.exec()

    def run_samples(self):
        if not self.require_visible():
            return
        if self.dataset_workspace:
            return self.run_camera_samples()
        if not self.images:
            self.error("请先选择图片文件夹");return
        try:
            profile = self.current_profile()
        except Exception as exc:
            self.error(str(exc));return
        paths = [self.images[i] for i in sorted({0, len(self.images)//2, len(self.images)-1})]
        key = profile_hash(profile)
        def compute(cancel, progress):
            from north16.annotations.grabcut import digest
            from PIL import ImageDraw, ImageFont
            font_path = Path("C:/Windows/Fonts/msyh.ttc")
            font = ImageFont.truetype(str(font_path), 15) if font_path.exists() else ImageFont.load_default()
            sheets, receipts = [], []
            for i, path in enumerate(paths):
                if cancel.is_set():
                    return None
                image = read_image(path)
                checksum = digest(path)
                mask = preview(path, profile)
                if digest(path) != checksum:
                    raise ValueError("验证期间原图发生变化")
                row = Image.new("RGB", (960, 290), "#eef2f6")
                draw = ImageDraw.Draw(row)
                for col, picture in enumerate([image, Image.blend(image, colored(mask), .42), colored(mask)]):
                    picture.thumbnail((316, 250))
                    row.paste(picture, (col*320+(316-picture.width)//2, 26+(250-picture.height)//2))
                draw.text((8, 5), f"{i+1}: {path.name}", fill="#193c5c", font=font)
                sheets.append(row)
                receipts.append(dict(image=str(path), image_sha256=checksum,
                                     mask_sha256=__import__('hashlib').sha256(mask.tobytes()).hexdigest()))
                progress(i+1, len(paths), path.name)
            sheet = Image.new("RGB", (960, 290*len(sheets)), "white")
            for i, row in enumerate(sheets):
                sheet.paste(row, (0, i*290))
            return sheet, receipts
        def complete(result):
            if result is None:
                self.status_label.setText("多图验证已取消");return
            sheet, receipts = result
            self.validations[key] = receipts
            from PySide6.QtWidgets import QDialog
            dialog = QDialog(self)
            dialog.setWindowTitle("抽样预览 · 原图 / 叠加 / 掩码（不代表准确率）")
            dialog.resize(1100, 800)
            layout = QVBoxLayout(dialog)
            view = ImageView()
            layout.addWidget(view)
            view.set_image(sheet)
            dialog.show();view.fit();dialog.exec()
            self.status_label.setText(f"完成{len(receipts)}张抽样预览 · 可保存参数和验证记录")
        self.start(compute, complete, "正在验证开头、中间、末尾…")

    def mark_sample_validation_stale(self):
        if not self.sample_dialog or not self.dataset_workspace or not self.stream_key:return
        try:digest=profile_hash(self.current_profile())
        except ValueError:digest="invalid_parameters"
        self.sample_dialog.mark_profile(str(self.dataset_workspace.root),self.stream_key[0],self.stream_key[2],digest)

    def validations_for_profile(self,profile):
        digest=profile_hash(profile)
        if self.dataset_workspace and self.stream_key:
            return self.camera_validations.get((str(self.dataset_workspace.root),self.stream_key,digest),[])
        return self.validations.get(digest,[])

    def run_camera_samples(self):
        if not self.require_visible() or self.active_worker:return
        try:
            builder,sequence,options=self.camera_batch_context()
            options.pop("keep_horizon")
        except Exception as exc:
            self.error(str(exc));return
        from north16.gui.overview_jobs import validate_camera_samples
        def complete(report):
            for record in report["cameras"]:
                key=(sequence,"visible",record["camera"])
                receipts=[dict(image=r["image"],image_sha256=r["source_image_sha256"],mask_sha256=r["mask_sha256"])
                          for r in record["unique_results"] if r["status"]=="succeeded"]
                # A partial check cannot be recorded as completed three-frame validation.
                if len(receipts)==record["unique_expected"]:
                    self.camera_validations[(str(builder.root),key,record["profile_sha256"])]=receipts
            from north16.gui.sample_validation import SampleValidationDialog
            if self.sample_dialog:
                self.sample_dialog.close();self.sample_dialog.deleteLater()
            self.sample_dialog=SampleValidationDialog(report,self)
            self.sample_dialog.show()
            self.status_label.setText(f"{report['status']} · 16路首/中/末验证：{report['succeeded']}/{report['expected']} 张，不生成标签")
        self.start(lambda cancel,progress:validate_camera_samples(builder,sequence,cancel=cancel,progress=progress,**options),
                   complete,"正在并行验证各镜头开头 / 中间 / 末尾…")

    def copy_parameters(self):
        if self.active_worker or not self.require_visible():return
        try:
            self.copied_profile = deepcopy(self.current_profile())
        except Exception as exc:
            self.error(str(exc));return
        self.remember_stream()
        source = " / ".join(self.stream_key) if self.stream_key else "当前图片文件夹"
        self.profile_clipboard_label.setText(f"已复制：{source}\n参数 {profile_hash(self.copied_profile)[:10]} · 当前窗口有效")
        self.paste_profile_button.setEnabled(True)
        self.status_label.setText("参数快照已复制；可切换镜头后粘贴。跨次启动复用请保存参数JSON。")

    def paste_parameters(self):
        if self.active_worker or not self.require_visible():return
        if self.copied_profile is None:
            self.error("请先复制一组参数");return
        profile = deepcopy(self.copied_profile)
        if self.dataset_workspace and self.stream_key:
            self.apply_camera_results([dict(camera=self.stream_key[2],profile=profile)])
        else:
            self.apply_profile(profile)
            self.mask,self.result_key=None,None
            self.refresh_display()
        self.last_estimation = None
        self.estimate_label.setText("已粘贴参数 · 请检查本镜头地平线并重新预览、验证")
        self.parallel_estimate.setChecked(False)
        self.remember_stream()
        self.status_label.setText("已粘贴到当前镜头，批量生成将使用当前参数；请重新预览、验证。")

    def apply_parameters_to_all_cameras(self):
        if self.active_worker or not self.require_visible():return
        if not self.dataset_workspace or not self.stream_key:
            self.error("请先打开结构化数据集或标注工作区并选择片段");return
        try:
            self.dataset_workspace.assert_unchanged()
            profile=self.current_profile()
            sequence=self.stream_key[0]
            keys=[key for key in self.dataset_workspace.keys() if key[0]==sequence]
        except Exception as exc:
            self.error(str(exc));return
        self.apply_camera_results([dict(camera=key[2],profile=deepcopy(profile)) for key in keys])
        self.last_estimation = None
        self.estimate_label.setText("参数已应用到本片段全部可见光镜头 · 请逐镜头检查并验证")
        self.parallel_estimate.setChecked(False)
        self.status_label.setText(f"当前参数已应用到 {sequence} 全部 {len(keys)} 路可见光镜头（含未勾选）；请刷新预览并验证。")

    def load_parameters(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载参数", "", "JSON (*.json)")
        if path:
            try:
                self.apply_profile(load_profile(path))
                self.status_label.setText(f"已加载 {Path(path).name}")
            except Exception as exc:
                self.error(str(exc))

    def save_parameters(self):
        try:
            profile = self.current_profile()
        except Exception as exc:
            self.error(str(exc));return
        if self.dataset_workspace and self.stream_key:
            try:
                self.dataset_workspace.assert_unchanged()
                path = str(Path(self.output_field.text()) / "parameters" / Path(*self.stream_key) / (profile_hash(profile)+".json"))
            except Exception as exc:
                self.error(str(exc));return
        else:
            path, _ = QFileDialog.getSaveFileName(self, "保存参数（建议每个镜头独立保存）", "grabcut_profile.json", "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            receipt = Path(path).with_name(Path(path).stem+".validation.json")
            if receipt.exists() and QMessageBox.question(self, "覆盖配置记录", "对应验证记录已存在，是否覆盖？") != QMessageBox.StandardButton.Yes:
                return
            key = profile_hash(profile)
            save_json(Path(path), profile)
            save_json(receipt, dict(profile_sha256=key, note=self.note.text(),
                sampled_images=self.validations_for_profile(profile),
                automatic_estimation=self.estimation_for_profile(profile),
                status="sampled_unreviewed" if self.validations_for_profile(profile) else "not_sampled",
                review_status="unreviewed", saved_at=datetime.now().astimezone().isoformat()))
            self.status_label.setText("参数与抽样记录已保存")
            if self.dataset_workspace and not self.annotation_mode():
                from north16.packages import refresh_package
                refresh_package(Path(self.output_field.text()), kind="segmentation", protocol_id=self.dataset_workspace.protocol["protocol_id"])
            self.copy_parameters()
            self.status_label.setText("参数JSON与验证记录已保存，并已复制参数快照，可切换镜头粘贴。")
        except Exception as exc:
            self.error(str(exc))

    def choose_output(self):
        if self.annotation_mode():return
        if self.dataset_workspace:
            parent = QFileDialog.getExistingDirectory(self, "选择标签包父目录（自动创建新包，可容纳多个镜头）")
            if parent:
                output = Path(parent) / self.dataset_workspace.new_run_id()
                self.label_packages[str(self.dataset_workspace.root)] = output
                self.set_dataset_output()
            return
        parent = QFileDialog.getExistingDirectory(self, "选择输出父目录（程序将在下面创建新任务目录）")
        if parent:
            self.output_field.setText(str(Path(parent) / ("grabcut_"+datetime.now().strftime("%Y%m%d_%H%M%S"))))

    def save_current(self):
        if self.current_path is None:
            self.error("请先打开图片");return
        self.begin_job([self.current_path])

    def run_batch(self):
        if not self.images:
            self.error("请先选择图片文件夹");return
        self.begin_job(list(self.images))

    def rebuild_overview(self):
        if not self.dataset_workspace or not self.stream_key:return
        scope=(str(self.dataset_workspace.root),self.stream_key[0])
        keys=[key for key in self.dataset_workspace.keys() if key[0]==self.stream_key[0]]
        cameras=[key[2] for key in keys]
        if scope!=self.overview_scope:
            self.overview_scope=scope
            self.camera_previews.clear()
            selected=self.camera_selections.setdefault(scope,set(cameras))
            self.overview.set_cameras(cameras,selected,max((len(self.dataset_workspace.streams[key]) for key in keys),default=0))
        self.refresh_overview_cards()

    def remember_camera_selection(self):
        if self.overview_scope is not None:
            self.camera_selections[self.overview_scope]=set(self.overview.selected_cameras())
        enabled=self.dataset_workspace is not None and self.current_sensor()!="infrared" and not self.active_worker
        self.overview.export_button.setEnabled(enabled and bool(self.overview.selected_cameras()))
        self.parallel_button.setEnabled(enabled and bool(self.overview.selected_cameras()))

    def overview_frame_changed(self):
        for card in self.overview.cards.values():
            if card.result:card.show_result(card.result,self.overview.mode.currentData(),True)
        self.overview.summary.setText("预览帧序号已改变，请刷新全部预览")

    def overview_tab_changed(self,index):
        if (index==1 and not self.active_worker and self.dataset_workspace and self.current_sensor()=="visible"
                and self.overview.cards and not any(c.result for c in self.overview.cards.values())):
            self.run_camera_previews()

    def show_overview(self):
        self.center_tabs.blockSignals(True)
        self.center_tabs.setCurrentIndex(1)
        self.center_tabs.blockSignals(False)

    def refresh_overview_cards(self):
        if not self.dataset_workspace or not self.stream_key:return
        if self.overview_scope!=(str(self.dataset_workspace.root),self.stream_key[0]):return
        root,sequence=self.overview_scope
        self.overview.hint.setText(f"当前调试：{self.stream_key[2]}（右侧参数）。点击任一路放大，勾选仅控制批量导出；帧序号不代表时间同步。")
        for camera,card in self.overview.cards.items():
            card.set_active(camera==self.stream_key[2])
            result=self.camera_previews.get(camera)
            if result is None:continue
            key=(sequence,"visible",camera)
            profile=self.stream_profiles.get((root,key),DEFAULT_PROFILE)
            if key==self.stream_key:
                try:profile=self.current_profile()
                except ValueError:
                    card.show_result(result,self.overview.mode.currentData(),True);continue
            stale=(result["profile_sha256"]!=profile_hash(profile) or result.get("requested_frame_index")!=self.overview.frame_index.value())
            card.show_result(result,self.overview.mode.currentData(),stale)

    def mark_current_card_stale(self):
        if not hasattr(self,"overview") or not self.dataset_workspace or not self.stream_key:return
        if self.overview_scope!=(str(self.dataset_workspace.root),self.stream_key[0]):return
        card=self.overview.cards.get(self.stream_key[2])
        result=self.camera_previews.get(self.stream_key[2])
        if not card or result is None:return
        try:stale=(result["profile_sha256"]!=profile_hash(self.current_profile()) or result.get("requested_frame_index")!=self.overview.frame_index.value())
        except ValueError:stale=True
        card.show_result(result,self.overview.mode.currentData(),stale)

    def cache_current_preview(self,profile,path,mask):
        if not self.dataset_workspace or not self.stream_key or self.stream_key[1]!="visible":return
        if self.overview_scope!=(str(self.dataset_workspace.root),self.stream_key[0]):return
        from north16.gui.overview_jobs import preview_result
        from north16.common.files import sha256
        result=preview_result(path,self.source,mask,profile,sha256(path))
        result["camera"]=self.stream_key[2]
        result["requested_frame_index"]=self.overview.frame_index.value()
        self.camera_previews[self.stream_key[2]]=result
        self.refresh_overview_cards()

    def restore_camera_preview(self):
        if not self.dataset_workspace or not self.stream_key or self.stream_key[1]!="visible":return
        if self.overview_scope!=(str(self.dataset_workspace.root),self.stream_key[0]):return
        result=self.camera_previews.get(self.stream_key[2])
        if not result or str(self.current_path)!=result["image"]:return
        from north16.common.files import sha256
        try:
            if profile_hash(self.current_profile())!=result["profile_sha256"]:return
            if sha256(self.current_path)!=result["source_image_sha256"]:return
        except (ValueError,OSError):return
        self.mask=result["mask"]
        self.result_key=(str(self.current_path),result["profile_sha256"])
        self.refresh_display()
        self.result_label.setText(f"{self.current_path.name} · 已载入该镜头预览 · 草稿")

    def debug_camera(self,camera):
        if self.active_worker or not self.dataset_workspace or self.current_sensor()!="visible":return
        if camera not in self.overview.cards:return
        self.camera_combo.setCurrentText(camera)
        result=self.camera_previews.get(camera)
        if result and result.get("requested_frame_index")!=self.overview.frame_index.value():result=None
        index=next((i for i,p in enumerate(self.images) if result and str(p)==result["image"]),
                   min(self.overview.frame_index.value(),len(self.images)-1))
        self.files.setCurrentRow(index)
        self.restore_camera_preview()
        self.center_tabs.setCurrentIndex(0)

    def apply_camera_previews(self,report):
        for result in report["cameras"]:self.camera_previews[result["camera"]]=result
        for error in report["errors"]:
            self.camera_previews.pop(error["camera"],None)
            card=self.overview.cards.get(error["camera"])
            if card:card.show_error(error["error"])
        self.refresh_overview_cards()
        self.restore_camera_preview()
        self.overview.summary.setText(f"{report['status']} · 预览 {report['succeeded']}/{report['expected']} 路 · 失败 {report['failed']}")
        self.show_overview()

    def run_camera_previews(self):
        if not self.require_visible() or self.active_worker:return
        try:
            builder,sequence,options=self.camera_batch_context()
            options.pop("keep_horizon")
            frame_index=self.overview.frame_index.value()
        except Exception as exc:
            self.error(str(exc));return
        from north16.gui.overview_jobs import preview_cameras
        def complete(report):
            self.apply_camera_previews(report)
            self.status_label.setText(f"{report['status']} · 预览 {report['succeeded']}/{report['expected']} 路，可点击单路调试并勾选导出")
        self.start(lambda cancel,progress:preview_cameras(builder,sequence,frame_index=frame_index,
                   cancel=cancel,progress=progress,**options),complete,"正在生成各镜头结果总览…")

    def camera_batch_context(self):
        from north16.annotation.workspace import builder_for
        if not self.dataset_workspace or not self.stream_key:
            raise ValueError("请先打开north16结构化数据集并选择片段")
        self.current_profile()  # Invalid edits must not silently fall back to a saved profile.
        self.remember_stream()
        self.dataset_workspace.assert_unchanged()
        builder=builder_for(self.dataset_workspace.root)
        builder.workspace=self.dataset_workspace
        root=str(builder.root)
        sequence=self.stream_key[0]
        profiles={key[2]:self.stream_profiles[(root,key)] for key in builder.workspace.keys()
                  if key[0]==sequence and (root,key) in self.stream_profiles}
        return builder,sequence,dict(profiles=profiles,workers=self.parallel_workers.value(),
                                     keep_horizon=self.keep_horizon.isChecked())

    def apply_camera_results(self, results):
        root=str(self.dataset_workspace.root)
        sequence=self.stream_key[0]
        for result in results:
            if "profile" not in result:continue
            key=(sequence,"visible",result["camera"])
            self.stream_profiles[(root,key)]=result["profile"]
            self.camera_estimations[(root,key)]=result.get("estimation")
            if self.sample_dialog:
                self.sample_dialog.mark_profile(root,sequence,result["camera"],profile_hash(result["profile"]))
        profile=next((r["profile"] for r in results if r.get("camera")==self.stream_key[2]
                      and self.stream_key[1]=="visible" and "profile" in r),None)
        if profile is not None:
            self.apply_profile(profile)
            self.last_estimation=self.estimation_for_profile(profile)
            self.mask,self.result_key=None,None
            self.refresh_display()
            self.result_label.setText("各镜头参数已更新 · 请运行当前图片预览")
        self.refresh_overview_cards()

    def run_camera_estimation(self):
        if not self.require_visible() or self.active_worker:return
        try:
            builder,sequence,options=self.camera_batch_context()
            frame_index=self.overview.frame_index.value()
        except Exception as exc:
            self.error(str(exc));return
        from north16.gui.overview_jobs import preview_cameras
        def compute(cancel,progress):
            report=builder.estimate_cameras(sequence,cancel=cancel,
                progress=lambda d,t,n:progress(d,t*2,n),**options)
            if cancel.is_set():return report
            suggested=dict(options["profiles"])
            suggested.update({r["camera"]:r["profile"] for r in report["cameras"]})
            report["preview_report"]=preview_cameras(builder,sequence,profiles=suggested,
                workers=options["workers"],frame_index=frame_index,cancel=cancel,
                progress=lambda d,t,n:progress(t+d,t*2,n))
            return report
        def complete(report):
            self.apply_camera_results(report["cameras"])
            self.parallel_estimate.setChecked(False)
            preview_report=report.pop("preview_report",None)
            if preview_report:self.apply_camera_previews(preview_report)
            self.show_overview()
            self.status_label.setText(f"{report['status']} · 已估参 {report['succeeded']}/{report['expected']} 路，可点击图像逐路调试")
            text=f"估参 {report['succeeded']}/{report['expected']} 路"
            if preview_report:text+=f" · 预览 {preview_report['succeeded']}/{preview_report['expected']} 路 · 失败 {preview_report['failed']}"
            self.overview.summary.setText(text+" · 可继续独立调试")
        self.start(compute,complete,"正在分别估参并生成16路结果总览…")

    def run_camera_batch(self):
        if not self.require_visible() or self.active_worker:return
        try:
            cameras=self.overview.selected_cameras()
            if not cameras:raise ValueError("请先在16路总览中勾选至少一个要导出的镜头")
            builder,sequence,options=self.camera_batch_context()
            options["cameras"]=cameras
            options["profiles"]={c:p for c,p in options["profiles"].items() if c in cameras}
            output=Path(self.output_field.text()).resolve()
            # A selection export is a self-contained package. Historical labels
            # from another camera must never leak into this selection.
            if not self.annotation_mode() and (output/"dataset").exists() and any(p.is_file() for p in (output/"dataset").rglob("*")):
                output=output.parent/builder.workspace.new_run_id()
            estimate=self.parallel_estimate.isChecked()
            root=str(builder.root)
            estimations={key[2]:self.camera_estimations[(root,key)] for key in builder.workspace.keys()
                         if key[0]==sequence and key[2] in cameras and (root,key) in self.camera_estimations}
            self.label_packages[root]=output
            self.set_dataset_output()
        except Exception as exc:
            self.error(str(exc));return
        def complete(report):
            self.apply_camera_results(report["cameras"])
            self.job_complete(report,output,(self.dataset_workspace,self.stream_key))
            self.overview.summary.setText(f"已导出 {len(cameras)} 路 · 标签成功 {report['succeeded']} 张 · {report['status']}")
        self.start(lambda cancel,progress:builder.generate_cameras(sequence,output,estimate=estimate,
                   cancel=cancel,progress=progress,estimations=estimations,**options),complete,
                   f"正在导出勾选的 {len(cameras)} 路镜头…")

    def begin_job(self, images):
        if not self.require_visible():
            return
        if self.dataset_workspace:
            try:
                from north16.annotation.workspace import builder_for
                output = Path(self.output_field.text()).resolve()
                profile = self.current_profile()
                builder = builder_for(self.dataset_workspace.root)
                # Verify original workspace snapshots too; newly opening a builder
                # must not hide changes made after the GUI loaded the data.
                self.dataset_workspace.assert_unchanged()
                builder.workspace = self.dataset_workspace
                key = self.stream_key
                image_list = list(images)
                def compute(cancel, progress):
                    return builder.generate(key, image_list, profile, output, cancel=cancel, progress=progress,
                                            estimation=self.estimation_for_profile(profile))
                self.start(compute, lambda report: self.job_complete(report, output, (self.dataset_workspace, key)),
                           "正在保存 masks/*.json…" if self.annotation_mode() else "正在导出 masks/*.json 标签包…")
            except Exception as exc:
                self.error(str(exc))
            return
        try:
            from north16.annotations.workspace import check_output
            profile = self.current_profile()
            if not self.output_field.text().strip():
                raise ValueError("请选择输出目录")
            output = check_output(images, self.output_field.text())
            if self.dataset_workspace:
                expected = self.dataset_workspace.output_path("drafts", self.stream_key, output.name)
                if output != expected:
                    raise ValueError("数据集模式必须使用protocol预设输出目录")
        except Exception as exc:
            self.error(str(exc));return
        mode = profile["sea_mode"]
        mode_text = "冰水混合（GrabCut）" if mode == "mixed" else "全冰：地平线下统一标为冰" if mode == "ice_only" else "全水：地平线下统一标为水"
        text = f"使用当前参数生成 {len(images)} 张草稿。\n海面模式：{mode_text}\n输出：{output}\n\nother和薄冰区域需要人工复核。"
        if mode != "mixed":
            text += "\n单类模式应用于本次所有图片。请确认每张图都符合；出现冰水混合时应分开处理，船体/遮挡仍需修正。"
        if QMessageBox.question(self, "开始生成", text) != QMessageBox.StandardButton.Yes:
            return
        estimation = self.estimation_for_profile(profile)
        workspace, key = self.dataset_workspace, self.stream_key
        if workspace:
            from north16.annotations.dataset_workspace import run_dataset_job
            compute = lambda cancel, progress: run_dataset_job(workspace, key, images, profile, output, cancel=cancel, progress=progress, estimation=estimation)
        else:
            from north16.segmentation.builder import generate_folder
            compute = lambda cancel, progress: generate_folder(images, profile, output, cancel=cancel, progress=progress)
        self.start(compute, lambda report: self.job_complete(report, output, (workspace, key) if workspace else None), "正在生成草稿…")

    def job_complete(self, report, output, dataset=None):
        self.last_output = Path(output)
        self.last_dataset = dataset
        if self.dataset_workspace:
            self.set_dataset_output()
        self.status_label.setText(f"{report['status']} · 成功 {report['succeeded']} / 失败 {report.get('failed', 0)} · {output}")
        if report.get("errors"):
            QMessageBox.warning(self, "部分图片失败", "任务记录已保存，请查看last_run.json中的错误。")

    def run_export(self):
        if self.annotation_mode():
            return self.export_annotation_workspace()
        if self.last_output and (self.last_output/"last_run.json").is_file():
            QMessageBox.information(self, "JSON标签输出", f"标签已直接保存到masks，无需二次导出。\n{self.last_output}\n\n结构化标签包：将dataset内的内容整体合并到数据集根目录。\n普通文件夹输出：images与masks平级保存。")
            return
        if self.last_dataset:
            if self.last_output:
                QMessageBox.information(self, "JSON标签包", f"标签已直接保存，无需二次导出。\n{self.last_output}\n\n将dataset目录内的内容整体合并到数据集根目录。\n标签位于对应镜头的masks/*.json；已有标签不会覆盖。")
            return
        if not self.last_output or not (self.last_output/"manifest.json").exists():
            self.error("请先保存当前图片或完成一次批量生成");return
        if self.last_dataset:
            workspace, key = self.last_dataset
            output = workspace.output_path("projects", key, self.last_output.name)
            if output.exists():
                QMessageBox.information(self, "编辑工程已存在", f"本批次已有编辑工程，保留现有修改。\n请打开：\n{output/'images'}\n\n如上次导出未完成，请保留该目录并重新生成独立草稿批次。")
                return
        else:
            parent = QFileDialog.getExistingDirectory(self, "选择编辑工程的父目录")
            if not parent:
                return
            output = Path(parent) / ("xanylabeling_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
        source = self.last_output
        def complete(report):
            self.status_label.setText(f"编辑工程 {report['status']} · {report['succeeded']} 张 · {output}")
            QMessageBox.information(self, "编辑工程已保存", f"在X-AnyLabeling中打开：\n{output/'images'}\n\n修正回读命令见工程README.txt")
        self.start(lambda cancel, progress: export_editor(source, output, cancel=cancel, progress=progress), complete, "正在导出可编辑多边形…")

    def export_annotation_workspace(self):
        if self.active_worker:return
        cameras=self.overview.selected_cameras() if self.current_sensor()=="visible" else [self.stream_key[2]]
        if not cameras:
            self.error("请先勾选要交付的镜头");return
        parent=QFileDialog.getExistingDirectory(self,"选择图片＋标签交付包父目录（当前片段；可见光勾选镜头/红外当前镜头；含未标注图片）")
        if not parent:return
        from north16.annotation import AnnotationWorkspace
        workspace=AnnotationWorkspace(self.dataset_workspace.root)
        output=Path(parent)/("annotation_"+self.dataset_workspace.new_run_id())
        sequence=self.stream_key[0];sensor=self.current_sensor()
        def compute(cancel,progress):
            if cancel.is_set():return None
            return workspace.export(output,sequences=[sequence],sensor=sensor,cameras=cameras,
                                    cancel=cancel,progress=progress)
        def complete(report):
            if report is None:return
            if report.get("status")=="cancelled":
                self.status_label.setText("整包导出已停止，未生成交付包；工作区图片和标注保留。")
                return
            self.last_output=output
            self.status_label.setText(f"整包导出完成：{report['images']} 张图片 / {report['labels']} 个标签 / "
                                      f"{report['unlabeled_images']} 张未标注 · {output}")
        self.start(compute,complete,"正在校验并复制图片＋标签整包；原图和已有标注保留…")

    def open_output(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def stop(self):
        if self.active_worker:
            self.active_worker.cancel.set()
            self.status_label.setText("正在停止，当前图片计算结束后生效…")
            self.stop_button.setEnabled(False)

    def closeEvent(self, event):
        if self.active_worker:
            self.stop()
            QMessageBox.information(self, "任务正在运行", "已请求停止。请等待当前图片完成后再关闭窗口。")
            event.ignore()
        else:
            event.accept()
