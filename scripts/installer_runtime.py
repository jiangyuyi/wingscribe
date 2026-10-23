"""Prepare hash-pinned Python and pip without executing an online bootstrap."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import urllib.request
import zipfile

try:
    from scripts.installer_payload import build_directory, no_links
except ModuleNotFoundError:
    from installer_payload import build_directory, no_links


# Python digest from python.org's release Sigstore bundle (messageDigest).
# pip digest from https://pypi.org/pypi/pip/25.0.1/json.
PYTHON = ('python-3.11.8-embed-amd64.zip',
          '6347068ca56bf4dd6319f7ef5695f5a03f1ade3e9aa2d6a095ab27faa77a1290',
          'https://mirrors.huaweicloud.com/python/3.11.8/python-3.11.8-embed-amd64.zip',
          'https://www.python.org/ftp/python/3.11.8/python-3.11.8-embed-amd64.zip')
PIP = ('pip-25.0.1-py3-none-any.whl',
       'c46efd13b6aa8279f33f2864459c8ce587ea6a1a59ee20de055868d8f7688f7f',
       'https://mirrors.huaweicloud.com/repository/pypi/packages/c9/bc/b7db44f5f39f9d0494071bddae6880eb645970366d0a200022a1a93d57f5/pip-25.0.1-py3-none-any.whl',
       'https://files.pythonhosted.org/packages/c9/bc/b7db44f5f39f9d0494071bddae6880eb645970366d0a200022a1a93d57f5/pip-25.0.1-py3-none-any.whl')
# Repository-bundled archive fingerprint, NOT a publisher-provided checksum.
# Keep the shipped 13.40 runtime; do not silently fall back to unrelated 13.26.
EXIFTOOL_SHA256 = 'f5916bfc851b2b9176dbc4141161e9231d0b10cb1d16d25fec2ecd4a091e0c17'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(cache, spec):
    """Keep partial downloads; a range response must start at the requested byte."""
    name, expected, mirror, official = spec
    no_links(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    no_links(target)
    if target.exists():
        if digest(target) == expected:
            return target
        raise ValueError(f'Invalid cached resource; retained for inspection: {target}')
    for index, url in enumerate((mirror, official)):
        partial = cache / (name + f'.{index}.part')
        no_links(partial)
        # ProxyHandler({}) bypasses both environment and Windows registry proxies.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if index == 0 else urllib.request.build_opener()
        print(f"Downloading {'direct domestic mirror' if index == 0 else 'official fallback'}: {url}", flush=True)
        try:
            if partial.exists() and digest(partial) == expected:
                partial.rename(target)
                return target
            offset = partial.stat().st_size if partial.exists() else 0
            request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
            with opener.open(request, timeout=30) as response:
                append = response.status == 206
                if append and not re.match(rf'^bytes {offset}-\d+/\d+$', response.headers.get('Content-Range', '')):
                    raise ValueError('Invalid download resume response')
                if response.status not in (200, 206):
                    raise ValueError(f'Unexpected HTTP status: {response.status}')
                with partial.open('ab' if append else 'wb') as stream:
                    shutil.copyfileobj(response, stream)
            if digest(partial) != expected:
                raise ValueError('Downloaded resource SHA-256 differs from pinned upstream digest')
            partial.rename(target)
            return target
        except (OSError, ValueError) as error:
            print(f'Resource download failed; partial file retained: {error}', flush=True)
    raise RuntimeError(f'No verified source available for {name}')


def archive_entries(archive, destination):
    """Validate every member before writing any file; use Windows path rules."""
    no_links(destination)
    entries, seen = [], set()
    for info in archive.infolist():
        name = info.orig_filename.replace('\\', '/').rstrip('/')
        parts = name.split('/')
        if (not name or PurePosixPath(name).is_absolute()
                or any(p in ('', '.', '..') or p.endswith((' ', '.'))
                       or any(c in p for c in ':<>"|?*')
                       or any(ord(c) < 32 for c in p)
                       or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', p, re.I)
                       for p in parts)):
            raise ValueError(f'Unsafe archive member: {info.filename}')
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('Archive links are not allowed')
        key = name.casefold()
        if key in seen:
            raise ValueError(f'Duplicate archive member: {name}')
        seen.add(key)
        target = destination.joinpath(*parts)
        no_links(target)
        entries.append((info, target))
    files = {str(p).casefold() for i, p in entries if not i.is_dir()}
    for _, target in entries:
        if any(str(parent).casefold() in files for parent in target.parents):
            raise ValueError('Archive file/directory conflict')
    return entries


def extract(archive_path, destination, *, check_only=False, overrides=None):
    """Revalidate cached runtime bytes too, preserving unrelated site packages."""
    overrides = overrides or {}
    no_links(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive_entries(archive, destination)
        for info, target in entries:
            if info.is_dir():
                continue
            content = overrides.get(info.filename, archive.read(info))
            if check_only:
                if not target.is_file() or target.read_bytes() != content:
                    raise ValueError(f'Cached runtime differs from pinned resource: {target}')
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)


def prepare(root, mode, *, check_only=False):
    build = build_directory(root, mode)
    cache = root / 'installer/runtime-cache'
    resources = []
    for spec in (PYTHON, PIP):
        if check_only:
            path = cache / spec[0]
            no_links(path)
            if not path.is_file() or digest(path) != spec[1]:
                raise ValueError(f'Missing verified runtime cache: {path}')
        else:
            path = fetch(cache, spec)
        resources.append(path)
    runtime = build / 'python'
    # No BOM: embedded Python treats a BOM as part of the first search path.
    overrides = {'python311._pth': b'python311.zip\n.\nLib/site-packages\nimport site\n'}
    extract(resources[0], runtime, check_only=check_only, overrides=overrides)
    extract(resources[1], runtime / 'Lib/site-packages', check_only=check_only)
    subprocess.run([str(runtime / 'python.exe'), '-I', '-c',
                    'import sys,pip; assert sys.version_info[:3]==(3,11,8); assert pip.__version__=="25.0.1"'], check=True)


def prepare_exiftool(root, mode, *, check_only=False):
    archive = root / 'installer/tools/exiftool-runtime.zip'
    no_links(archive)
    if not archive.is_file() or digest(archive) != EXIFTOOL_SHA256:
        raise ValueError('Bundled ExifTool archive missing or changed; no unverified download fallback')
    target = build_directory(root, mode) / 'tools'
    extract(archive, target, check_only=check_only)
    result = subprocess.run([str(target / 'exiftool.exe'), '-ver'],
                            capture_output=True, text=True, check=True)
    if result.stdout.strip() != '13.40':
        raise ValueError(f'Unexpected bundled ExifTool version: {result.stdout.strip()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['cpu', 'gpu'], required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--component', choices=['python', 'exiftool'], default='python')
    args = parser.parse_args()
    action = prepare if args.component == 'python' else prepare_exiftool
    action(Path(__file__).resolve().parents[1], args.mode, check_only=args.check)
