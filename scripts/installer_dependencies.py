"""Fetch hashed installer wheels, install offline, and verify runtime versions."""
import argparse
import hashlib
from importlib import metadata
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import unquote, urlsplit
from uuid import uuid4

try:
    from packaging.requirements import Requirement
except ImportError:
    from pip._vendor.packaging.requirements import Requirement

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from scripts.export_installer_lock import check
except ModuleNotFoundError:
    from export_installer_lock import check
from installer_payload import build_directory, no_links


PYPI_MIRROR = 'https://pypi.tuna.tsinghua.edu.cn/simple'
TORCH_MIRROR = 'https://mirrors.nju.edu.cn/pytorch/whl'


def pip_environment(*, direct):
    env = {key:value for key,value in os.environ.items() if not key.upper().startswith('PIP_')}
    env['PIP_CONFIG_FILE'] = os.devnull
    env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    if direct:
        env = {k:v for k,v in env.items() if k.upper() not in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY')}
        env['NO_PROXY'] = '*'
        env['no_proxy'] = '*'
    return env


def requirements(path):
    for line in path.read_text(encoding='utf8').replace('\\\n','').splitlines():
        text = line.split('--hash=',1)[0].strip()
        if text and not text.startswith('#'):
            yield Requirement(text), line


def runtime_check(path):
    failures = []
    for req, _ in requirements(path):
        if req.marker and not req.marker.evaluate({'extra':''}):
            continue
        try:
            installed = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            failures.append(f'{req.name}: missing')
            continue
        if not req.specifier.contains(installed, prereleases=True):
            failures.append(f'{req.name}: installed {installed}, expected {req.specifier}')
    if failures:
        raise ValueError('Runtime differs from installer lock:\n'+'\n'.join(failures))


def run_pip(args, *, direct=True):
    subprocess.run([sys.executable,'-m','pip','--disable-pip-version-check',*args],
                   env=pip_environment(direct=direct), check=True)


def quarantine_bad_cache(root, wheels):
    """Retain corrupt cache evidence without letting pip repeatedly select it."""
    allowed = {}
    for package in tomllib.loads((root/'uv.lock').read_text(encoding='utf8'))['package']:
        for entry in package.get('wheels', []):
            name = unquote(Path(urlsplit(entry['url']).path).name)
            allowed.setdefault(name,set()).add(entry['hash'].removeprefix('sha256:'))
    for path in wheels.glob('*.whl'):
        no_links(path)
        if path.name not in allowed:
            continue  # Unrelated legacy cache cannot satisfy the pinned requirements.
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream,'sha256').hexdigest()
        if digest not in allowed[path.name]:
            target = path.with_name(path.name+'.rejected-'+uuid4().hex)
            path.rename(target)
            print(f'Preserved corrupt cached wheel for inspection: {target.name}',flush=True)


def fetch(root, mode):
    check(root)
    if sys.version_info[:2] != (3,11) or sys.platform != 'win32':
        raise ValueError('Installer wheel fetching requires Windows Python 3.11')
    channel = 'cpu' if mode=='cpu' else 'cu128'
    lock = root/'installer/locks'/f'{channel}.txt'
    wheels = root/'installer'/f'wheels-{mode}'
    no_links(wheels)
    wheels.mkdir(parents=True,exist_ok=True)
    quarantine_bad_cache(root,wheels)
    base = ['download','--require-hashes','--no-deps','--only-binary=:all:',
            '--no-cache-dir','--timeout','30','--retries','2','--dest',str(wheels),
            '--find-links',str(wheels)]
    for shared in (root/'installer'/('wheels-gpu' if mode=='cpu' else 'wheels-cpu'),
                   root/'installer/wheels'):
        if shared.is_dir():
            no_links(shared)
            quarantine_bad_cache(root,shared)
            base += ['--find-links',str(shared)]
    try:
        run_pip([*base,'--no-index','-r',str(lock)])
        print('Complete verified wheel cache; no network needed.', flush=True)
        return
    except subprocess.CalledProcessError:
        print('Offline cache incomplete or invalid; fetching locked wheels.', flush=True)
    # PyTorch variants have a dedicated index; all other public wheels use PyPI.
    with tempfile.TemporaryDirectory(dir=wheels) as temporary:
        torch_lock = Path(temporary)/'torch.txt'
        torch_lock.write_text('\n'.join(line for req,line in requirements(lock)
                                        if req.name in ('torch','torchvision'))+'\n',encoding='utf8')
        for subset, mirror, official in (
            (torch_lock, TORCH_MIRROR+'/'+channel, 'https://download.pytorch.org/whl/'+channel),
            (lock, PYPI_MIRROR, 'https://pypi.org/simple'),
        ):
            try:
                print(f'Downloading from domestic mirror directly: {mirror}', flush=True)
                run_pip([*base,'--index-url',mirror,'-r',str(subset)])
            except subprocess.CalledProcessError:
                print(f'Mirror download/verification failed; falling back to official index: {official}', flush=True)
                run_pip([*base,'--index-url',official,'-r',str(subset)],direct=False)
    # Verify the full set is usable without a network before modifying a runtime.
    run_pip([*base,'--no-index','-r',str(lock)])


def install(root, mode):
    check(root)
    channel = 'cpu' if mode=='cpu' else 'cu128'
    lock = root/'installer/locks'/f'{channel}.txt'
    wheels = root/'installer'/f'wheels-{mode}'
    if sys.version_info[:2] != (3,11) or sys.platform != 'win32':
        raise ValueError('Installer runtime must be Windows Python 3.11')
    expected = build_directory(root,mode)/'python'/'python.exe'
    no_links(expected)
    expected = expected.resolve()
    if Path(sys.executable).resolve() != expected:
        raise ValueError('Refusing to install into a non-build interpreter')
    run_pip(['download','--no-index','--find-links',str(wheels),'--dest',str(wheels),
             '--require-hashes','--only-binary=:all:','--no-deps','-r',str(lock)])
    run_pip(['install','--no-index','--find-links',str(wheels),'--require-hashes',
             '--only-binary=:all:','--no-deps','--force-reinstall','-r',str(lock)])
    runtime_check(lock)
    run_pip(['check'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['fetch','install','check'])
    parser.add_argument('--mode',choices=['cpu','gpu'],required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.action == 'fetch':
        fetch(root,args.mode)
    elif args.action == 'install':
        install(root,args.mode)
    else:
        check(root)
        runtime_check(root/'installer/locks'/('cpu.txt' if args.mode=='cpu' else 'cu128.txt'))
    print('Installer dependency operation completed successfully.', flush=True)
