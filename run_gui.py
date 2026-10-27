"""Source-checkout launcher with a readable error dialog for pythonw."""
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    try:
        from north16.gui.app import main
        main()
    except Exception:
        detail = traceback.format_exc()
        # A failed launcher should never silently disappear under pythonw.
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, detail, "North16 GUI - launch failed", 0x10)
        raise
