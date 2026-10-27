"""Parameter editing separated from file IO and background processing."""
from copy import deepcopy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QLabel, QSpinBox, QWidget

from north16.annotations.profiles import DEFAULT_PROFILE, validate_profile


class Parameters(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.profile = deepcopy(DEFAULT_PROFILE)
        self.inputs = {}
        form = QFormLayout(self)
        self.sea_mode = QComboBox()
        for text, value in [("冰水混合（GrabCut）", "mixed"), ("全冰（无可见水域）", "ice_only"), ("全水（无可见冰面）", "water_only")]:
            self.sea_mode.addItem(text, value)
        self.sea_mode.currentIndexChanged.connect(self.update_mode)
        form.addRow("海面模式", self.sea_mode)
        self.mode_help = QLabel("混合模式按亮度种子区分冰水；全冰/全水需人工确认")
        self.mode_help.setWordWrap(True)
        self.mode_help.setStyleSheet("color:#78552c;")
        form.addRow(self.mode_help)
        specs = [("working_width", "工作宽度 / px", 256, 4096, 1280),
                 ("water_definite_brightness_max", "确定水域阈值", 0, 254, 78),
                 ("water_probable_brightness_max", "候选水域阈值", 0, 254, 125),
                 ("ice_definite_brightness_min", "确定冰面阈值", 1, 255, 168),
                 ("grabcut_iterations", "迭代次数", 1, 20, 5),
                 ("boundary_kernel", "边界忽略核 / 奇数", 1, 15, 3),
                 ("rng_seed", "随机种子", 0, 2147483647, 42)]
        for key, label, minimum, maximum, value in specs:
            field = QSpinBox()
            field.setRange(minimum, maximum)
            field.setValue(value)
            if key == "working_width":
                field.setSingleStep(128)
            elif key == "boundary_kernel":
                field.setSingleStep(2)
            field.valueChanged.connect(self.changed)
            self.inputs[key] = field
            form.addRow(label, field)
        field = QDoubleSpinBox()
        field.setRange(0, 20)
        field.setDecimals(2)
        field.setSingleStep(.25)
        field.setValue(DEFAULT_PROFILE["horizon_ignore_half_height"]*100)
        field.setSuffix(" %")
        field.valueChanged.connect(self.changed)
        self.inputs["band"] = field
        form.addRow("地平线忽略半宽", field)

    def update_mode(self):
        mode = self.sea_mode.currentData()
        for key in ("water_definite_brightness_max", "water_probable_brightness_max", "ice_definite_brightness_min", "grabcut_iterations", "boundary_kernel", "rng_seed"):
            if key in self.inputs:
                self.inputs[key].setEnabled(mode == "mixed")
        self.mode_help.setText("混合模式按亮度种子区分冰水；若无另一类，请选全冰/全水。" if mode == "mixed" else
                               "人工指定：地平线下可见海面全部标为冰。船体/遮挡需另行修正；混合帧需切回混合模式。" if mode == "ice_only" else
                               "人工指定：地平线下可见海面全部标为水。船体/遮挡需另行修正；混合帧需切回混合模式。")
        self.changed.emit()

    def get_profile(self, points):
        profile = deepcopy(self.profile)
        profile["sea_mode"] = self.sea_mode.currentData()
        for key in ("water_definite_brightness_max", "water_probable_brightness_max",
                    "ice_definite_brightness_min", "grabcut_iterations", "rng_seed"):
            profile[key] = self.inputs[key].value()
        width = self.inputs["working_width"].value()
        profile["working_wh"] = [width, round(width*9/16)]
        profile["boundary_ignore_kernel"] = [self.inputs["boundary_kernel"].value()]*2
        profile["horizon_ignore_half_height"] = self.inputs["band"].value()/100
        profile["horizon_normalized_xy"] = deepcopy(points)
        return validate_profile(profile)

    def set_profile(self, profile):
        self.profile = validate_profile(profile)
        self.sea_mode.blockSignals(True)
        self.sea_mode.setCurrentIndex(self.sea_mode.findData(self.profile["sea_mode"]))
        self.sea_mode.blockSignals(False)
        for key, field in self.inputs.items():
            if key == "working_width":
                value = self.profile["working_wh"][0]
            elif key == "boundary_kernel":
                value = self.profile["boundary_ignore_kernel"][0]
            elif key == "band":
                value = self.profile["horizon_ignore_half_height"]*100
            else:
                value = self.profile[key]
            field.blockSignals(True)
            field.setValue(value)
            field.blockSignals(False)
        self.update_mode()
