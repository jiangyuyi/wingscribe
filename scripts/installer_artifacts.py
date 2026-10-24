"""Record and verify compiled installer files, without signing or publishing."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_manifest(directory: Path, mode: str, version: str) -> Path:
    if mode not in ('cpu', 'gpu') or not re.fullmatch(r'\d+(?:\.\d+){2,3}', version):
        raise ValueError('Expected cpu/gpu and a numeric installer version')
    stem = f'WingScribe-Setup-{mode.upper()}-{version}'
    files = [directory / f'{stem}.exe']
    parts = sorted(directory.glob(f'{stem}-*.bin'))
    if mode == 'gpu' and not parts:
        raise ValueError('GPU installer volumes are missing')
    numbers = []
    for part in parts:
        match = re.fullmatch(re.escape(stem) + r'-(\d+)\.bin', part.name)
        if not match:
            raise ValueError(f'Unexpected volume name: {part.name}')
        numbers.append(int(match[1]))
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        raise ValueError('Installer volumes are not contiguous')
    files.extend(parts)
    records = []
    for path in files:
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Missing, empty or linked artifact: {path.name}')
        records.append({'name': path.name, 'size': path.stat().st_size,
                        'sha256': digest(path)})
    manifest = directory / f'{stem}.sha256.json'
    manifest.write_text(json.dumps({'format': 1, 'mode': mode, 'version': version,
                                    'files': records}, indent=2) + '\n', encoding='utf-8')
    return manifest


def verify_manifest(manifest: Path) -> None:
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('format') != 1 or not data.get('files'):
        raise ValueError('Invalid artifact manifest')
    for record in data['files']:
        name = record['name']
        if not re.fullmatch(r'WingScribe-Setup-(CPU|GPU)-\d+(?:\.\d+){2,3}(?:-\d+\.bin|\.exe)', name):
            raise ValueError('Invalid artifact filename')
        path = manifest.parent / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != record['size'] or digest(path) != record['sha256']:
            raise ValueError(f'Artifact verification failed: {name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--mode', choices=['cpu', 'gpu'])
    parser.add_argument('--version')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        verify_manifest(args.verify)
        print('Artifact hashes verified')
    elif args.directory and args.mode and args.version:
        print(write_manifest(args.directory, args.mode, args.version))
    else:
        parser.error('Supply --verify or --directory, --mode and --version')
