"""Verify sdist/wheel resources and generate release checksums."""
from pathlib import Path
import hashlib
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
wheel, = (root/'dist').glob('*.whl')
sdist, = (root/'dist').glob('*.tar.gz')
excluded = {'.venv', '.git', 'backups', '__pycache__'}
with zipfile.ZipFile(wheel) as archive, tarfile.open(sdist) as source:
    names = archive.namelist()
    members = source.getnames()
    assert not any(excluded.intersection(Path(n).parts) for n in names+members)
    prefix = members[0].split('/')[0]
    # north16/datasets is application code; only top-level runtime data is forbidden.
    assert not any(Path(n).parts[0] in {'datasets', 'labels'} for n in names)
    assert not any(len(Path(n).parts) > 1 and Path(n).parts[1] in {'datasets', 'labels'} for n in members)
    for folder in ('configs', 'templates', 'docs'):
        for path in (root/folder).rglob('*'):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            expected = path.read_bytes()
            assert archive.read('north16/_resources/'+relative) == expected, relative
            assert source.extractfile(prefix+'/'+relative).read() == expected, relative
checksums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (wheel, sdist))
(root/'dist/SHA256SUMS.txt').write_text(checksums, encoding='utf-8')
print(checksums, end='')
print('Wheel and sdist contain all canonical resources; runtime data excluded.')
