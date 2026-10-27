"""Launch the independent North16 registration workbench."""
import argparse
from pathlib import Path
import sys


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",help="Extracted camera folder or North16 dataset root")
    parser.add_argument("--output",help="Separate calibration/registration output parent")
    parser.add_argument("--visible-model",help="Local detector .pt; never downloaded automatically")
    parser.add_argument("--infrared-model",help="Local detector .pt; infrared proposals require review")
    parser.add_argument("--project",help="Restore a saved project.json after source hash validation")
    parser.add_argument("--screenshot",help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtWidgets import QApplication
    from .window import RegistrationWindow
    app=QApplication.instance() or QApplication(sys.argv[:1])
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if font.exists():QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Microsoft YaHei',10))
    window=RegistrationWindow(args.root,args.output,dict(visible=args.visible_model or '',infrared=args.infrared_model or ''));window.show()
    if args.project:window.restore_session(args.project)
    if args.screenshot:
        def capture():window.fit_views();window.grab().save(args.screenshot);window.close()
        QTimer.singleShot(1000,capture)
    return app.exec()


if __name__=='__main__':main()
