"""Coordinate OpenCV's process-wide thread setting across segmentation calls."""
from contextlib import contextmanager
from threading import Condition

import cv2

_condition = Condition()
_active = 0
_threads = None
_previous = None


@contextmanager
def opencv_threads(count):
    # Calls requesting the same setting may overlap. Changing/restoring the
    # global setting waits until all calls using it have left.
    global _active, _threads, _previous
    with _condition:
        _condition.wait_for(lambda: _active == 0 or _threads == count)
        if _active == 0:
            _previous = cv2.getNumThreads()
            cv2.setNumThreads(count)
            _threads = count
        _active += 1
    try:
        yield
    finally:
        with _condition:
            _active -= 1
            if _active == 0:
                cv2.setNumThreads(_previous)
                _threads = None
                _condition.notify_all()
