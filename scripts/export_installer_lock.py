"""Export audited installer inputs without downloading or changing uv.lock."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib
from urllib.parse import unquote, urlsplit


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check(root: Path) -> None:
    directory = root / 'installer' / 'locks'
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    expected = {'uv.lock', 'pyproject.toml', 'installer/locks/cpu.txt', 'installer/locks/cu128.txt'}
    if set(manifest['sha256']) != expected:
        raise ValueError('Unexpected installer lock manifest paths')
    for relative, digest in manifest['sha256'].items():
        if sha256(root / relative) != digest:
            raise ValueError(f'Installer lock export is stale or modified: {relative}')


def check_wheel(root: Path, wheel: Path) -> None:
    lock = tomllib.loads((root / 'uv.lock').read_text(encoding='utf-8'))
    allowed = {entry['hash'].removeprefix('sha256:')
               for package in lock['package'] for entry in package.get('wheels', [])
               if unquote(Path(urlsplit(entry['url']).path).name) == wheel.name}
    if sha256(wheel) not in allowed:
        raise ValueError(f'Wheel filename/hash not present in uv.lock: {wheel.name}')


def export(root: Path, uv: str) -> None:
    destination = root / 'installer' / 'locks'
    destination.mkdir(exist_ok=True)
    # Prepare both variants before publishing either one; no network resolution.
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        generated = {}
        for extra in ('cpu', 'cu128'):
            target = Path(temporary) / (extra + '.txt')
            subprocess.run([uv, 'export', '--locked', '--offline', '--no-dev', '--extra', extra,
                            '--no-emit-project', '--no-header', '--no-annotate', '-o', str(target)],
                           cwd=root, check=True, stdout=subprocess.DEVNULL)
            generated[extra] = target.read_bytes()
        for extra, content in generated.items():
            (destination / (extra + '.txt')).write_bytes(content)
    paths = ['uv.lock', 'pyproject.toml', 'installer/locks/cpu.txt', 'installer/locks/cu128.txt']
    manifest = {'schema': 1, 'sha256': {relative: sha256(root / relative) for relative in paths}}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    check(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uv', default='uv')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--wheel', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.wheel:
        check_wheel(root, args.wheel)
    elif args.check:
        check(root)
    else:
        export(root, args.uv)
    print('Installer lock validation passed.')
