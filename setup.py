"""Bundle canonical protocol files without maintaining duplicate resources."""
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithProtocol(build_py):
    def run(self):
        super().run()
        root = Path(__file__).parent
        target = Path(self.build_lib) / "north16" / "_resources"
        for folder in ("configs", "templates", "docs"):
            shutil.copytree(root / folder, target / folder, dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildWithProtocol})
