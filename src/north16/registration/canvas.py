"""Native-coordinate point/box interaction on a zoomable source canvas."""
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPen, QFont
from north16.gui.image_view import ImageView


class Canvas(ImageView):
    point_added = Signal(float, float)
    box_added = Signal(object)

    def __init__(self):
        super().__init__()
        self.mode = "pan"
        self.start_box = None
        self.marks = []

    def set_mode(self, mode):
        self.mode = mode
        self.setDragMode(self.DragMode.ScrollHandDrag if mode == "pan" else self.DragMode.NoDrag)

    def mousePressEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and 0 <= point.x() < self.width_px and 0 <= point.y() < self.height_px:
            if self.mode == "point":
                self.point_added.emit(point.x(), point.y());event.accept();return
            if self.mode == "box":
                self.start_box = point;event.accept();return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mode == "box" and self.start_box is not None:
            point = self.mapToScene(event.position().toPoint())
            start, self.start_box = self.start_box, None
            x1, x2 = sorted([max(0, min(self.width_px-1, start.x())), max(0, min(self.width_px-1, point.x()))])
            y1, y2 = sorted([max(0, min(self.height_px-1, start.y())), max(0, min(self.height_px-1, point.y()))])
            if x2-x1 >= 3 and y2-y1 >= 3:
                self.box_added.emit([x1, y1, x2, y2])
            event.accept();return
        super().mouseReleaseEvent(event)

    def annotations(self, points, boxes, prefix):
        for item in self.marks:
            self.scene().removeItem(item)
        self.marks = []
        for number, xy, role in points:
            x, y = xy
            color = QColor("#43f5d0" if role == "check" else "#ffda44" if role == "fit" else "#888888")
            pen = QPen(color, 2);pen.setCosmetic(True)
            marker = self.scene().addEllipse(-4, -4, 8, 8, pen)
            marker.setPos(x, y);marker.setFlag(marker.GraphicsItemFlag.ItemIgnoresTransformations)
            text = self.scene().addSimpleText(str(number), QFont("Arial", 11));text.setBrush(color);text.setPos(x+5, y+5)
            text.setFlag(text.GraphicsItemFlag.ItemIgnoresTransformations)
            self.marks.extend([marker, text])
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = box["xyxy"]
            pen = QPen(QColor("#32e9ff"), 2);pen.setCosmetic(True)
            rectangle = self.scene().addRect(x1, y1, x2-x1, y2-y1, pen)
            text = self.scene().addSimpleText(f"{prefix}{i+1} {box.get('confidence',1):.2f}", QFont("Arial", 11))
            text.setBrush(QColor("#32e9ff"));text.setPos(x1, y1)
            text.setFlag(text.GraphicsItemFlag.ItemIgnoresTransformations)
            self.marks.extend([rectangle, text])
