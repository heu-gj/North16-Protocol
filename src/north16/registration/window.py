"""Paired registration workbench: automatic candidates, manual points and ship ROIs."""
from copy import deepcopy
from pathlib import Path
import json

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QFileDialog, QMessageBox, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QListWidget,
    QSpinBox, QDoubleSpinBox, QSlider, QCheckBox)

from north16.gui.image_view import ImageView
from north16.gui.workers import Worker
from .canvas import Canvas
from .dataset import discover
from .geometry import fit, warp
from .matching import auto_register
from .storage import load_rgb, save_project, read_project


class RegistrationWindow(QMainWindow):
    def __init__(self, root=None, output=None, weights=None):
        super().__init__()
        self.setWindowTitle("North16 · 可见光—红外配准工作台 0.5.0")
        self.resize(1660, 1020)
        self.pairs, self.observations, self.solutions = {}, {}, {}
        self.current_key, self.current_stamp = None, None
        self.visible, self.infrared, self.result = None, None, None
        self.pending, self.active_worker, self.stale = {}, None, False
        self.pool = QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.updating = False
        self._build(output, weights or {})
        if root:
            self.open_root(root)

    def button(self, label, callback, layout):
        button = QPushButton(label);button.clicked.connect(callback);layout.addWidget(button);return button

    def _build(self, output, weights):
        self.setStyleSheet("QWidget {font-family:'Microsoft YaHei';font-size:12px;} QPushButton{padding:6px;} QTableWidget{background:white;}")
        central=QWidget();self.setCentralWidget(central);layout=QVBoxLayout(central)
        bar=QHBoxLayout();layout.addLayout(bar)
        self.button("打开数据根目录",self.choose_root,bar)
        self.root_field=QLineEdit();self.root_field.setReadOnly(True);bar.addWidget(self.root_field,1)
        self.button("加载配准工程",self.load_session,bar)
        row=QHBoxLayout();layout.addLayout(row)
        self.pair_combo=QComboBox();self.pair_combo.currentIndexChanged.connect(self.select_pair);row.addWidget(self.pair_combo)
        self.button("上一对图",lambda:self.move(-1),row)
        self.frames=QComboBox();self.frames.currentIndexChanged.connect(self.select_frame);row.addWidget(self.frames,1)
        self.button("下一对图",lambda:self.move(1),row)
        self.button("适应窗口",self.fit_views,row)
        self.main_split=QSplitter();layout.addWidget(self.main_split,1)
        center=QSplitter(Qt.Orientation.Vertical)
        sources=QWidget();source_layout=QHBoxLayout(sources);source_layout.setContentsMargins(0,0,0,0)
        self.visible_view,self.infrared_view=Canvas(),Canvas()
        for title,view in [("可见光参考图 · V船框",self.visible_view),("红外待配准图 · I船框",self.infrared_view)]:
            panel=QWidget();inner=QVBoxLayout(panel);inner.setContentsMargins(0,0,0,0)
            inner.addWidget(QLabel(title));inner.addWidget(view);source_layout.addWidget(panel)
        center.addWidget(sources)
        preview=QWidget();preview_layout=QVBoxLayout(preview);preview_layout.setContentsMargins(0,0,0,0)
        modes=QHBoxLayout();preview_layout.addLayout(modes)
        self.view_mode=QComboBox();self.view_mode.addItems(["透明叠加","棋盘格","红外配准图","有效区域"])
        self.view_mode.currentIndexChanged.connect(self.refresh_preview);modes.addWidget(self.view_mode)
        modes.addWidget(QLabel("红外透明度"));self.alpha=QSlider(Qt.Orientation.Horizontal);self.alpha.setRange(0,100);self.alpha.setValue(50)
        self.alpha.valueChanged.connect(self.refresh_preview);modes.addWidget(self.alpha,1)
        self.preview_view=ImageView();preview_layout.addWidget(self.preview_view)
        self.metrics=QLabel("尚无变换；下方先显示可见光。配准结果均为待审核候选，不是完整相机标定。")
        self.metrics.setWordWrap(True);preview_layout.addWidget(self.metrics)
        center.addWidget(preview);center.setSizes([500,350]);self.main_split.addWidget(center)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(350);self.tabs.setMaximumWidth(470);self.main_split.addWidget(self.tabs)
        points_tab=QWidget();p=QVBoxLayout(points_tab);self.tabs.addTab(points_tab,"对应点")
        self.model=QComboBox();self.model.addItem("单应变换 homography","homography");self.model.addItem("仿射变换 affine","affine")
        self.model.currentIndexChanged.connect(self.mark_stale);p.addWidget(self.model)
        self.auto_button=self.button("自动配准：全图匹配",lambda:self.run_auto(False),p)
        mode_row=QHBoxLayout();p.addLayout(mode_row)
        self.tool=QComboBox();self.tool.addItem("拖动／缩放","pan");self.tool.addItem("点选对应位置","point");self.tool.addItem("画船只候选框","box")
        self.tool.currentIndexChanged.connect(self.change_tool);mode_row.addWidget(self.tool)
        self.role=QComboBox();self.role.addItem("新点：拟合点","fit");self.role.addItem("新点：检查点","check");mode_row.addWidget(self.role)
        instructions=QLabel("两图分别点击同一物理位置形成一对点。检查点不参与拟合。双击坐标可修改；role可改为fit/check/reject。")
        instructions.setWordWrap(True);p.addWidget(instructions)
        self.show_rejected=QCheckBox("在图上显示被排除的匹配点")
        self.show_rejected.toggled.connect(lambda:self.render_annotations() if self.current_stamp else None);p.addWidget(self.show_rejected)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(["可见光 x,y","红外 x,y","role","来源"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellChanged.connect(self.edit_point);p.addWidget(self.table,1)
        self.button("删除选中对应点",self.delete_points,p)
        self.solve_button=self.button("根据拟合点重新计算",self.solve,p)
        self.button("清除当前帧对应点",self.clear_points,p)
        self.tabs.addTab(self.build_ships(weights),"船只区域")
        save=QWidget();s=QVBoxLayout(save);self.tabs.addTab(save,"工程／输出")
        guide=QLabel("输出为独立批次：工程JSON、红外配准PNG、valid.png和叠加图。原始图片不改写。\n\n保存包含本相机对已访问帧的对应点、船框和关联；切帧可用当前变换预览其他时刻。\n\n同名帧仅为候选时间关联，首版不自动估计时间偏移。")
        guide.setWordWrap(True);s.addWidget(guide)
        self.output_field=QLineEdit(str(output or ""));s.addWidget(self.output_field)
        self.button("选择输出父目录",self.choose_output,s)
        self.save_button=self.button("保存工程与当前配准结果",self.save,s)
        s.addStretch(1)
        self.status=QLabel("选择码头数据根目录或north16 datasets根目录");self.status.setWordWrap(True);layout.addWidget(self.status)
        self.visible_view.point_added.connect(lambda x,y:self.add_point("visible",x,y))
        self.infrared_view.point_added.connect(lambda x,y:self.add_point("infrared",x,y))
        self.visible_view.box_added.connect(lambda box:self.add_box("visible",box))
        self.infrared_view.box_added.connect(lambda box:self.add_box("infrared",box))
        self.main_split.setSizes([1220,400])

    def build_ships(self,weights):
        tab=QWidget();layout=QVBoxLayout(tab)
        text=QLabel("检测只生成候选框，红外尤其可能漏检／误检。可手动画框。船框不直接当作几何角点，需确认同一条船后，在两框内匹配特征。")
        text.setWordWrap(True);layout.addWidget(text)
        self.weights={}
        for sensor,title in [("visible","可见光本地.pt权重"),("infrared","红外本地.pt权重")]:
            layout.addWidget(QLabel(title));row=QHBoxLayout();layout.addLayout(row)
            field=QLineEdit(str(weights.get(sensor,"")));self.weights[sensor]=field;row.addWidget(field)
            self.button("选择",lambda _checked=False,s=sensor:self.choose_weight(s),row)
        self.confidence=QDoubleSpinBox();self.confidence.setRange(.05,.95);self.confidence.setSingleStep(.05);self.confidence.setValue(.25)
        row=QHBoxLayout();row.addWidget(QLabel("候选框置信度"));row.addWidget(self.confidence);layout.addLayout(row)
        self.detect_button=self.button("检测当前两图的船只候选",self.run_detection,layout)
        row=QHBoxLayout();layout.addLayout(row)
        self.button("导入可见光船框",lambda:self.import_boxes("visible"),row)
        self.button("导入红外船框",lambda:self.import_boxes("infrared"),row)
        self.box_list=QListWidget();layout.addWidget(self.box_list,1)
        self.button("删除选中船框（清除相关联列表）",self.delete_box,layout)
        row=QHBoxLayout();layout.addLayout(row)
        self.visible_box=QSpinBox();self.visible_box.setRange(1,999)
        self.infrared_box=QSpinBox();self.infrared_box.setRange(1,999)
        row.addWidget(QLabel("V编号"));row.addWidget(self.visible_box);row.addWidget(QLabel("I编号"));row.addWidget(self.infrared_box)
        self.button("确认两框为同一条船",self.link_boxes,layout)
        self.link_list=QListWidget();layout.addWidget(self.link_list)
        self.button("删除选中船只关联",self.delete_link,layout)
        self.roi_button=self.button("根据已关联船框自动配准",lambda:self.run_auto(True),layout)
        return tab

    def state(self):
        return self.observations.setdefault(self.current_stamp,dict(points=[],boxes={"visible":[],"infrared":[]},links=[],visible_path=str(self.visible_path),infrared_path=str(self.infrared_path)))

    def choose_root(self):
        path=QFileDialog.getExistingDirectory(self,"选择包含camera或sequences的目录")
        if path:self.open_root(path)

    def open_root(self,path):
        try:pairs=discover(path)
        except Exception as exc:self.error(str(exc));return
        self.pairs=pairs;self.root=Path(path).resolve();self.root_field.setText(str(self.root))
        self.all_observations={};self.solutions={};self.current_key=None
        self.pair_combo.blockSignals(True);self.pair_combo.clear()
        for key in sorted(pairs):self.pair_combo.addItem(f"{key[0]} / {key[1]} · {len(pairs[key])}帧",key)
        self.pair_combo.blockSignals(False)
        if not self.output_field.text():self.output_field.setText(str(self.root.parent/(self.root.name+"_registration")))
        # Prefer a texture-rich actual pilot rather than an all-black stream.
        index=next((i for i in range(self.pair_combo.count()) if self.pair_combo.itemData(i)[1]=="back_05"),0)
        self.pair_combo.setCurrentIndex(index);self.select_pair()

    def select_pair(self,*_):
        key=self.pair_combo.currentData()
        if key is None:return
        if self.current_key is not None:self.all_observations[self.current_key]=self.observations
        self.current_key=key;self.observations=self.all_observations.setdefault(key,{})
        self.result=deepcopy(self.solutions.get(key));self.stale=False
        self.frames.blockSignals(True);self.frames.clear()
        for stamp,_,_ in self.pairs[key]:self.frames.addItem(stamp)
        self.frames.blockSignals(False);self.select_frame(0)

    def select_frame(self,index):
        if self.current_key is None or index<0:return
        stamp,visible_path,infrared_path=self.pairs[self.current_key][index]
        try:visible,infrared=load_rgb(visible_path),load_rgb(infrared_path)
        except Exception as exc:self.error(str(exc));return
        self.current_stamp=stamp;self.visible_path,self.infrared_path=visible_path,infrared_path
        self.visible,self.infrared=visible,infrared;self.pending={}
        if self.result and (self.result["source_size_wh"]!=list(infrared.shape[1::-1]) or self.result["target_size_wh"]!=list(visible.shape[1::-1])):
            self.result=None;self.stale=True
        self.visible_view.set_image(Image.fromarray(visible),reset=True);self.infrared_view.set_image(Image.fromarray(infrared),reset=True)
        self.render_annotations();self.refresh_preview()
        self.status.setText(f"{stamp} · 可见光 {visible.shape[1]}×{visible.shape[0]} / 红外 {infrared.shape[1]}×{infrared.shape[0]} · 同名时间候选；当前图像{'包含纯黑/纯色异常' if visible.max()==visible.min() or infrared.max()==infrared.min() else '已加载'}")

    def move(self,delta):
        target=self.frames.currentIndex()+delta
        if 0<=target<self.frames.count():self.frames.setCurrentIndex(target)

    def change_tool(self):
        self.pending={}
        for view in (self.visible_view,self.infrared_view):view.set_mode(self.tool.currentData())
        if self.current_stamp:self.render_annotations()

    def add_point(self,sensor,x,y):
        if self.current_stamp is None:return
        self.pending[sensor]=[x,y]
        if len(self.pending)==2:
            self.state()["points"].append(dict(**self.pending,role=self.role.currentData(),source="manual"))
            self.pending={};self.mark_stale()
        else:self.status.setText("已选一侧位置，请点击另一图的同一物理点")
        self.render_annotations()

    def mark_stale(self,*_):
        if self.result:
            self.stale=True
            self.solutions.pop(self.current_key,None)
        if hasattr(self,"metrics"):self.refresh_preview()

    def render_annotations(self):
        if self.current_stamp is None:return
        state=self.state();self.updating=True
        self.table.setRowCount(len(state["points"]))
        for row,point in enumerate(state["points"]):
            values=[", ".join(f"{v:.2f}" for v in point[s]) for s in ("visible","infrared")]+[point.get("role","fit"),point.get("source","")]
            for column,value in enumerate(values):
                item=QTableWidgetItem(value)
                if column==3:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row,column,item)
        self.updating=False
        for sensor,view,prefix in [("visible",self.visible_view,"V"),("infrared",self.infrared_view,"I")]:
            points=[(i+1,p[sensor],p.get("role","fit")) for i,p in enumerate(state["points"])
                    if p.get("role")!="reject" or self.show_rejected.isChecked()]
            if sensor in self.pending:points.append(("待",self.pending[sensor],"check"))
            view.annotations(points,state["boxes"][sensor],prefix)
        self.box_list.clear();self.box_items=[]
        for sensor,prefix in [("visible","V"),("infrared","I")]:
            for i,box in enumerate(state["boxes"][sensor]):
                self.box_items.append((sensor,i));self.box_list.addItem(f"{prefix}{i+1} {box.get('label','ship')} · {box.get('confidence',1):.2f} · {box['source']}")
        self.link_list.clear()
        for a,b in state["links"]:self.link_list.addItem(f"V{a+1} ↔ I{b+1}（人工关联）")

    def edit_point(self,row,column):
        if self.updating or self.current_stamp is None:return
        try:
            value=self.table.item(row,column).text().strip()
            if column<2:
                xy=[float(v.strip()) for v in value.split(',')]
                sensor="visible" if column==0 else "infrared";image=getattr(self,sensor)
                if len(xy)!=2 or not np.isfinite(xy).all() or not 0<=xy[0]<image.shape[1] or not 0<=xy[1]<image.shape[0]:raise ValueError("坐标超出原图或格式错误，使用x,y")
                self.state()["points"][row][sensor]=xy
                self.state()["points"][row]["source"]="manual"
            elif column==2:
                if value not in ("fit","check","reject"):raise ValueError("role只能为fit/check/reject")
                self.state()["points"][row]["role"]=value
            self.mark_stale()
        except Exception as exc:self.error(str(exc))
        self.render_annotations()

    def delete_points(self):
        for row in sorted({i.row() for i in self.table.selectedIndexes()},reverse=True):self.state()["points"].pop(row)
        self.pending={};self.mark_stale();self.render_annotations()

    def clear_points(self):
        if self.current_stamp is None:return
        if self.state()["points"] and QMessageBox.question(self,"清除对应点","清除当前帧全部对应点？原图和船框保留。")!=QMessageBox.StandardButton.Yes:return
        self.state()["points"]=[];self.pending={};self.mark_stale();self.render_annotations()

    def accept_result(self,result):
        result["fit_stamp"]=self.current_stamp;self.result=result;self.solutions[self.current_key]=deepcopy(result);self.stale=False
        self.refresh_preview();self.status.setText("已生成配准候选；请检查独立检查点、近远目标及其他时刻")

    def solve(self):
        if self.visible is None:return
        try:result=fit(self.state()["points"],self.model.currentData(),self.infrared.shape[1::-1],self.visible.shape[1::-1])
        except Exception as exc:self.error(str(exc));return
        result["method"]="manual_or_edited_correspondences";self.accept_result(result)

    def run_auto(self,ships=False):
        if self.visible is None:return
        state=self.state();regions=[]
        if ships:
            for v,i in state["links"]:regions.append(dict(visible=state["boxes"]["visible"][v]["xyxy"],infrared=state["boxes"]["infrared"][i]["xyxy"]))
            if not regions:self.error("先确认V框与I框为同一条船；框角点不会直接用作配准点");return
        visible,infrared,model=self.visible.copy(),self.infrared.copy(),self.model.currentData()
        manual=deepcopy([p for p in state["points"] if p.get("source")=="manual"])
        def completed(value):
            points,result=value
            if manual:
                points+=manual
                try:result=fit(points,model,infrared.shape[1::-1],visible.shape[1::-1])
                except Exception as exc:self.error(str(exc));return
                result["method"]="automatic_with_manual_points"
            self.state()["points"]=points;self.render_annotations();self.accept_result(result)
        self.start(lambda:auto_register(visible,infrared,model,regions or None),completed,"正在自动匹配并检查几何，结果可能被拒绝…")

    def add_box(self,sensor,xyxy):
        if self.current_stamp is None:return
        self.state()["boxes"][sensor].append(dict(xyxy=list(xyxy),label="ship",confidence=1,source="manual",review_status="user_drawn"));self.render_annotations()

    def delete_box(self):
        row=self.box_list.currentRow()
        if row>=0:
            sensor,index=self.box_items[row];self.state()["boxes"][sensor].pop(index);self.state()["links"]=[];self.render_annotations()

    def link_boxes(self):
        if self.current_stamp is None:return
        a,b=self.visible_box.value()-1,self.infrared_box.value()-1
        state=self.state()
        if a>=len(state["boxes"]["visible"]) or b>=len(state["boxes"]["infrared"]):self.error("船框编号不存在");return
        if any(a==v or b==i for v,i in state["links"]):self.error("一个船框只能关联一次，请先删除旧关联");return
        state["links"].append([a,b]);self.render_annotations()

    def delete_link(self):
        row=self.link_list.currentRow()
        if row>=0:self.state()["links"].pop(row);self.render_annotations()

    def choose_weight(self,sensor):
        path,_=QFileDialog.getOpenFileName(self,"选择本地检测权重",filter="PyTorch模型 (*.pt)")
        if path:self.weights[sensor].setText(path)

    def import_boxes(self,sensor):
        if self.current_stamp is None:return
        path,_=QFileDialog.getOpenFileName(self,"导入当前图像的X-AnyLabeling或COCO船只JSON",filter="JSON (*.json)")
        if not path:return
        try:
            from .ship_annotations import read_boxes
            image=getattr(self,sensor)
            boxes=read_boxes(path,getattr(self,sensor+"_path"),image.shape[1::-1])
            self.state()["boxes"][sensor].extend(boxes);self.render_annotations()
            self.status.setText(f"已导入{len(boxes)}个{sensor}船只区域，请确认两图对应关系")
        except Exception as exc:self.error(str(exc))

    def run_detection(self):
        if self.visible is None:return
        images={s:getattr(self,s).copy() for s in ("visible","infrared")}
        paths={s:self.weights[s].text().strip() for s in images};confidence=self.confidence.value()
        if any(not Path(path).is_file() for path in paths.values()):self.error("请为两种模态选择本地.pt权重；允许使用同一通用模型，红外结果需复核");return
        def compute():
            from .detector import detect
            return {s:detect(image,paths[s],confidence) for s,image in images.items()}
        def completed(value):
            state=self.state();state["links"]=[];state["detectors"]={}
            for sensor,(boxes,metadata) in value.items():
                state["boxes"][sensor]=[b for b in state["boxes"][sensor] if b.get("source")!="detector_candidate"]+boxes
                state["detectors"][sensor]=metadata
            self.render_annotations();self.status.setText("船只候选已生成：请删除误检、补画漏检，再人工关联V/I编号；尚未进行配准")
        self.start(compute,completed,"正在本机CPU检测船只候选，不自动关联…")

    def refresh_preview(self,*_):
        if self.visible is None:return
        if self.result is None:
            self.preview_view.set_image(Image.fromarray(self.visible));return
        if self.stale:
            self.metrics.setText("对应点或模型已修改：下图为上次变换，重新计算后才能导出该结果。")
        else:
            result=self.result
            checks=result.get("check_errors_px",[])
            check_text=f"独立检查点{len(checks)}个，均值{np.mean(checks):.2f}px" if checks else "无独立检查点，尚不能判定精度"
            self.metrics.setText(f"待审核 · {result['model']} · 内点{result['inlier_count']}/{result['fit_count']} · 拟合残差中位数{result['median_inlier_error_px']:.2f}px（可见光原尺寸）\n{check_text} · 求解帧{result.get('fit_stamp','')} · 当前帧{self.current_stamp}")
        # Render at preview scale; stored transform and output remain native.
        factor=min(1.,1400/self.visible.shape[1]);size=(max(1,round(self.visible.shape[1]*factor)),max(1,round(self.visible.shape[0]*factor)))
        import cv2
        scaled=np.diag([size[0]/self.visible.shape[1],size[1]/self.visible.shape[0],1])@np.asarray(self.result["matrix"])
        registered,valid=warp(self.infrared,scaled,size);visible=cv2.resize(self.visible,size);mask=valid!=0
        mode=self.view_mode.currentIndex()
        if mode==2:output=registered
        elif mode==3:output=np.repeat(valid[...,None],3,axis=2)
        else:
            output=visible.copy()
            if mode==1:
                y,x=np.indices(valid.shape);mask &= (x//64+y//64)%2==0;output[mask]=registered[mask]
            else:
                alpha=self.alpha.value()/100;output[mask]=(visible[mask]*(1-alpha)+registered[mask]*alpha).astype(np.uint8)
        self.preview_view.set_image(Image.fromarray(output))

    def fit_views(self):
        for view in (self.visible_view,self.infrared_view,self.preview_view):view.fit()

    def choose_output(self):
        path=QFileDialog.getExistingDirectory(self,"选择配准输出父目录")
        if path:self.output_field.setText(path)

    def save(self):
        if self.visible is None:return
        if not self.output_field.text().strip():self.error("请先选择输出父目录");return
        output,root,key,stamp=self.output_field.text(),self.root,self.current_key,self.current_stamp
        visible_path,infrared_path=self.visible_path,self.infrared_path
        observations=deepcopy(self.observations);result=deepcopy(self.result) if not self.stale else None
        def completed(path):self.status.setText(f"已保存：{path}" );QMessageBox.information(self,"工程已保存",str(path)+("\n当前变换过期，仅保存标注工程。" if result is None else "\n含原尺寸配准图、valid.png和叠加图，仍待审核。"))
        self.start(lambda:save_project(output,root,key,stamp,visible_path,infrared_path,observations,result),completed,"正在保存工程、来源校验和与配准图…")

    def load_session(self):
        path,_=QFileDialog.getOpenFileName(self,"加载配准工程",filter="配准工程 (project.json)")
        if not path:return
        self.restore_session(path)

    def restore_session(self,path):
        try:
            data=read_project(path);self.open_root(data["dataset_root"])
            key=(data["sequence"],data["camera"])
            if key not in self.pairs:raise ValueError("原相机对不存在")
            index=next(i for i in range(self.pair_combo.count()) if self.pair_combo.itemData(i)==key)
            self.pair_combo.setCurrentIndex(index)
            self.observations=deepcopy(data["observations"]);self.all_observations[key]=self.observations
            self.result=data["result"];self.solutions[key]=deepcopy(self.result);self.stale=False
            if self.result:
                self.model.blockSignals(True);self.model.setCurrentIndex(self.model.findData(self.result["model"]));self.model.blockSignals(False)
            frame=self.frames.findText(data["stamp"])
            if frame<0:raise ValueError("原时间帧不存在")
            self.frames.setCurrentIndex(frame);self.select_frame(frame)
            self.status.setText(f"已恢复工程：{path}")
        except Exception as exc:self.error(str(exc))

    def start(self,function,callback,message):
        if self.active_worker:return
        worker=Worker(lambda cancel,progress:function());self.active_worker=worker
        worker.signals.result.connect(callback);worker.signals.error.connect(self.error)
        worker.signals.finished.connect(self.finished)
        # Disable root/project navigation too, so background results cannot land on another pair.
        self.centralWidget().setEnabled(False);self.status.setText(message);self.pool.start(worker)

    def finished(self):
        self.active_worker=None;self.centralWidget().setEnabled(True)

    def error(self,message):
        self.status.setText(str(message).strip().splitlines()[-1][:400]);QMessageBox.warning(self,"操作未完成",str(message)[-2000:])

    def closeEvent(self,event):
        if self.active_worker:
            self.status.setText("当前任务正在运行，完成后再关闭窗口");event.ignore()
        else:event.accept()
