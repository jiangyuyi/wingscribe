"""Stage only distributable source/configuration into a generated build directory."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat

try:
    from scripts.export_installer_lock import check
except ModuleNotFoundError:
    from export_installer_lock import check


CONFIG_FILES = (
    'settings.example.yaml', 'secrets.example.yaml',
    'dictionaries/location_aliases.example.yaml',
    'dictionaries/foreign_countries.txt', 'dictionaries/china_bird_list.txt',
    'dictionaries/china_admin_divisions.example.csv',
)
RUNTIME_SCRIPTS = ('config_wizard.py', 'run_culling.py', 'migrate_avilist.py',
                   'download_model.py', 'check_gpu.py', 'backup_db.ps1')
STARTUP_SCRIPTS = ('start_web.bat', 'start_web.ps1', 'init_env.py')
REFERENCE_FILES = (
    'avilist-v2025b.csv', 'avilist-v2025b.json', 'inaturalist_china_provinces.json',
    'bird_order_mapping.csv', 'bird_order_mapping_complete.csv',
    'bird_family_mapping.csv', 'bird_family_mapping_complete.csv',
    'bird_genus_mapping.csv', 'bird_genus_mapping_complete.csv',
    'IOC_Names_File_Plus-15.1_red.xlsx', 'Multiling IOC 15.1_d.xlsx',
    '动物界-脊索动物门-2025-10626.xlsx', '动物界-脊索动物门-2025-10626_repaired.xlsx',
)
SOURCE_SUFFIXES = {'.py', '.html', '.js', '.css', '.ico', '.svg', '.png', '.jpg',
                   '.jpeg', '.gif', '.webp', '.woff', '.woff2', '.ttf', '.json', '.txt'}
DOC_SUFFIXES = {'.md', '.png', '.jpg', '.jpeg', '.svg'}


def no_links(path: Path):
    for candidate in (*reversed(path.parents), path):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Linked payload path is not allowed: {candidate}')


def build_directory(root: Path, mode: str):
    if mode not in ('cpu', 'gpu'):
        raise ValueError('Unknown build variant')
    root = root.absolute()
    build = root/'installer'/f'build-{mode}'
    no_links(build)
    if not build.resolve().is_relative_to(root.resolve()/'installer'):
        raise ValueError('Build directory escaped installer workspace')
    return build


def payload_files(root: Path, mode: str):
    files = {}
    for directory, suffixes in [('src', SOURCE_SUFFIXES), ('docs', DOC_SUFFIXES)]:
        source = root/directory
        if not source.is_dir():
            raise ValueError(f'Missing payload directory: {source}')
        for path in source.rglob('*'):
            relative = path.relative_to(root)
            if '__pycache__' in relative.parts or any(p.startswith('.') for p in relative.parts):
                continue
            no_links(path)
            if path.is_file() and path.suffix.lower() in suffixes:
                files[relative.as_posix()] = path
    for name in CONFIG_FILES:
        files['config/'+name] = root/'config'/name
    for name in RUNTIME_SCRIPTS:
        files['scripts/'+name] = root/'scripts'/name
    for name in STARTUP_SCRIPTS:
        files['scripts/'+name] = root/'installer/scripts'/name
    for name in REFERENCE_FILES:
        files['data/references/'+name] = root/'data/references'/name
    for name in ('README.md', 'CLAUDE.md', 'pyproject.toml', 'uv.lock'):
        files[name] = root/name
    files['requirements.txt'] = root/'installer/locks'/('cpu.txt' if mode=='cpu' else 'cu128.txt')
    for path in files.values():
        no_links(path)
        if not path.is_file():
            raise ValueError(f'Missing payload file: {path}')
    return files


def stage(root: Path, mode: str):
    root = root.absolute()
    check(root)
    build = build_directory(root, mode)
    files = payload_files(root, mode)  # preflight all inputs before cleaning output
    managed = [build/name for name in ('src','config','scripts','docs','data/references')]
    for target in managed:
        no_links(target)
        if not target.resolve().is_relative_to(build.resolve()):
            raise ValueError('Payload cleanup escaped build directory')
        if target.exists():
            for entry in target.rglob('*'):
                no_links(entry)
    for target in managed:
        if target.exists():
            shutil.rmtree(target)
    hashes = {}
    for relative, source in files.items():
        destination = build/relative
        no_links(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        hashes[relative] = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest = {'schema':1, 'mode':mode, 'sha256':hashes}
    manifest_path = build/'payload-manifest.json'
    no_links(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['cpu','gpu'], required=True)
    args = parser.parse_args()
    result = stage(Path(__file__).resolve().parents[1], args.mode)
    print(f"Staged {len(result['sha256'])} audited payload files ({args.mode})")
