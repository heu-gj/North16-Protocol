"""Launch the North16 local desktop parameter workspace."""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--folder", help="Open 8-bit images or a North16 dataset root; infrared supports browsing")
    source.add_argument("--dataset", help="Open a North16 structured dataset root")
    parser.add_argument("--screenshot", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QFontDatabase
    from north16.gui.window import Window
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from pathlib import Path
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Microsoft YaHei", 10))
    window = Window(args.dataset or args.folder)
    window.show()
    if args.screenshot:
        def capture():
            window.fit_views()
            window.grab().save(args.screenshot)
            window.close()
        QTimer.singleShot(1200, capture)
    return app.exec()


if __name__ == "__main__":
    main()
