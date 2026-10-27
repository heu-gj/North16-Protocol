"""Serialized background work, with cooperative cancellation between images."""
import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, Signal


class Signals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()
        self.cancel = threading.Event()

    def run(self):
        try:
            self.signals.result.emit(self.function(self.cancel, self.signals.progress.emit))
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()
