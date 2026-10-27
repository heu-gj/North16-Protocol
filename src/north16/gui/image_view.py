"""Zoomable image canvas with draggable horizon and native pixel inspection."""
import math

from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsScene, QGraphicsView
from PIL.ImageQt import ImageQt
from north16.annotations.profiles import DEFAULT_PROFILE


class Handle(QGraphicsEllipseItem):
    def __init__(self, canvas, index, x, y):
        super().__init__(-6, -6, 12, 12)
        self.canvas, self.index = canvas, index
        self.setFlag(self.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(self.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setBrush(QColor("#fff3a1"))
        self.setPen(QPen(QColor("#101c2b"), 1))
        self.setZValue(5)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setPos(x, y)

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemPositionChange and self.scene():
            x = self.canvas.points[self.index][0] * max(1, self.canvas.width_px-1)
            y = max(1., min(self.canvas.height_px-2., value.y()))
            return QPointF(x, y)
        if change == self.GraphicsItemChange.ItemPositionHasChanged and self.scene():
            self.canvas.points[self.index][1] = self.pos().y() / max(1, self.canvas.height_px-1)
            self.canvas.changed.emit()
            self.canvas.viewport().update()
        return super().itemChange(change, value)


class ImageView(QGraphicsView):
    changed = Signal()
    transform_changed = Signal()
    pixel_hovered = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(self.DragMode.ScrollHandDrag)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setBackgroundBrush(QColor("#111b29"))
        self.width_px = self.height_px = 1
        self.points, self.handles = [], []
        self.band = DEFAULT_PROFILE["horizon_ignore_half_height"]
        self.show_horizon = False
        self.pixmap_item = self.scene().addPixmap(QPixmap())

    def set_image(self, image, reset=False):
        changed_size = image.size != (self.width_px, self.height_px)
        self.width_px, self.height_px = image.size
        self.pixmap_item.setPixmap(QPixmap.fromImage(ImageQt(image.convert("RGB"))))
        self.scene().setSceneRect(0, 0, self.width_px, self.height_px)
        if reset or changed_size:
            self.fit()

    def fit(self):
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.transform_changed.emit()

    def set_horizon(self, points, band, visible):
        for handle in self.handles:
            self.scene().removeItem(handle)
        self.handles = []
        self.points = [list(p) for p in points]
        self.band, self.show_horizon = band, visible
        if visible:
            for index, (x, y) in enumerate(self.points):
                handle = Handle(self, index, x*(self.width_px-1), y*(self.height_px-1))
                self.scene().addItem(handle)
                self.handles.append(handle)
        self.viewport().update()

    def set_horizon_mode(self, mode):
        """Change control count while keeping the current line's endpoints."""
        if mode not in {"line", "polyline"}:
            raise ValueError("Unknown horizon mode")
        if len(self.points) < 2:
            return
        if (mode == "line") == (len(self.points) == 2):
            return
        left, right = self.points[0], self.points[-1]
        if mode == "line":
            points = [left, right]
        else:
            points = [[x, left[1] + (right[1]-left[1])*x]
                      for x in (0., .25, .5, .75, 1.)]
        self.set_horizon(points, self.band, self.show_horizon)
        self.changed.emit()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if not self.show_horizon or len(self.points) < 2:
            return
        xy = [(x*(self.width_px-1), y*(self.height_px-1)) for x, y in self.points]
        upper = [QPointF(x, y-self.band*self.height_px) for x, y in xy]
        lower = [QPointF(x, y+self.band*self.height_px) for x, y in reversed(xy)]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 211, 80, 35))
        painter.drawPolygon(QPolygonF(upper+lower))
        pen = QPen(QColor("#ffd350"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in xy]))

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        scale = self.transform().m11()*factor
        if .01 < scale < 20:
            self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
            self.scale(factor, factor)
            self.transform_changed.emit()
        event.accept()
        self.inspect_pixel(event.position().toPoint())

    def inspect_pixel(self, position):
        """Map viewport coordinates through zoom/pan; reject letterbox margins."""
        point = self.mapToScene(position)
        if (not self.pixmap_item.pixmap().isNull() and
                0 <= point.x() < self.width_px and 0 <= point.y() < self.height_px):
            self.pixel_hovered.emit(math.floor(point.x()), math.floor(point.y()))
        else:
            self.pixel_hovered.emit(-1, -1)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self.inspect_pixel(event.position().toPoint())

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.Leave:
            self.pixel_hovered.emit(-1, -1)
        return super().viewportEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pixmap_item.pixmap().isNull():
            self.fit()
