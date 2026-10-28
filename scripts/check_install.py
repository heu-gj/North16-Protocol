"""Run with python -I to verify the installed package without source imports."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import north16
from north16.annotations.profiles import DEFAULT_PROFILE
from north16.resources import initialize, resource_root

assert 'site-packages' in Path(north16.__file__).parts, north16.__file__
assert north16.__version__ == importlib.metadata.version('north16')
assert DEFAULT_PROFILE['horizon_ignore_half_height'] == .01
assert len(DEFAULT_PROFILE['horizon_normalized_xy']) == 2
resources = resource_root()
for name in ('configs/protocol.yaml', 'templates/txt/classes.txt', 'docs/GUI.md',
             'docs/WORKFLOW.md', 'docs/ANNOTATION.md', 'docs/images/gui_samples_grid_090.png',
             'docs/images/ice_only_comparison_041.jpg'):
    assert resources.joinpath(*name.split('/')).is_file(), name
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    initialize(root/'batch', root/'raw', root/'datasets', ['segment_a'])
    assert (root/'batch/docs/WORKFLOW.md').is_file()
    for args in (['--version'], ['initialize', '--help'], ['camera', '--help'],
                 ['annotation', '--help'], ['annotation', 'initialize', '--help']):
        subprocess.run([sys.executable, '-I', '-m', 'north16', *args], cwd=root, check=True, capture_output=True)
print(json.dumps(dict(version=north16.__version__, installed_from=north16.__file__, resources='passed')))
