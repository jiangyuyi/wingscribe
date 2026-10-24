import hashlib
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest
from scripts import installer_payload as payload


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for directory in ('src', 'docs'):
        (tmp_path/directory).mkdir()
    (tmp_path/'src/main.py').write_text('app')
    (tmp_path/'docs/start.md').write_text('instructions')
    inputs = ['README.md','CLAUDE.md','pyproject.toml','uv.lock']
    inputs += ['config/'+p for p in payload.CONFIG_FILES]
    inputs += ['scripts/'+p for p in payload.RUNTIME_SCRIPTS]
    inputs += ['installer/scripts/'+p for p in payload.STARTUP_SCRIPTS]
    inputs += ['data/references/'+p for p in payload.REFERENCE_FILES]
    inputs += ['installer/locks/cpu.txt','installer/locks/cu128.txt']
    inputs += ['installer/models/yolo26n.pt']
    inputs += ['installer/installer-format.txt']
    for relative in inputs:
        path = tmp_path/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)
    monkeypatch.setattr(payload, 'BUNDLED_MODEL_SHA256', hashlib.sha256(
        (tmp_path/'installer/models/yolo26n.pt').read_bytes()).hexdigest())
    locked = ['uv.lock','pyproject.toml','installer/locks/cpu.txt','installer/locks/cu128.txt']
    manifest = {'schema':1,'sha256':{p:hashlib.sha256((tmp_path/p).read_bytes()).hexdigest() for p in locked}}
    (tmp_path/'installer/locks/manifest.json').write_text(json.dumps(manifest))
    return tmp_path


@pytest.mark.parametrize('mode,extra', [('cpu','cpu'),('gpu','cu128')])
def test_payload_whitelist_removes_cached_secrets_and_preserves_runtime(repo, mode, extra):
    (repo/'config/settings.yaml').write_text('personal-photo-path')
    (repo/'config/secrets.yaml').write_text('private-api-key')
    (repo/'scripts/force_reset.py').write_text('dangerous maintenance script')
    (repo/'src/.env').write_text('secret')
    build = repo/'installer'/f'build-{mode}'
    (build/'config').mkdir(parents=True)
    (build/'config/settings.yaml').write_text('old cached personal setting')
    (build/'python').mkdir()
    (build/'python/preserved').write_text('runtime')
    manifest = payload.stage(repo,mode)
    assert not (build/'config/settings.yaml').exists()
    assert not (build/'config/secrets.yaml').exists()
    assert not (build/'scripts/force_reset.py').exists()
    assert not (build/'src/.env').exists()
    assert (build/'python/preserved').read_text() == 'runtime'
    assert (repo/'config/settings.yaml').read_text() == 'personal-photo-path'
    assert (build/'requirements.txt').read_text() == f'installer/locks/{extra}.txt'
    assert (build/'docs/start.md').is_file()
    assert manifest == payload.stage(repo,mode)
    assert all(hashlib.sha256((build/p).read_bytes()).hexdigest()==digest for p,digest in manifest['sha256'].items())


def test_preflight_missing_input_does_not_clean_existing_output(repo):
    build=repo/'installer/build-cpu/config';build.mkdir(parents=True)
    marker=build/'settings.yaml';marker.write_text('cached')
    (repo/'config/settings.example.yaml').unlink()
    with pytest.raises(ValueError,match='Missing payload'):
        payload.stage(repo,'cpu')
    assert marker.read_text() == 'cached'


def test_changed_model_is_rejected_before_output_cleanup(repo):
    marker = repo/'installer/build-cpu/config/settings.yaml'
    marker.parent.mkdir(parents=True)
    marker.write_text('preserve')
    (repo/'installer/models/yolo26n.pt').write_bytes(b'changed')
    with pytest.raises(ValueError, match='fingerprint'):
        payload.stage(repo, 'cpu')
    assert marker.read_text() == 'preserve'


def test_junction_build_root_rejected_before_any_cleanup(repo, monkeypatch):
    original=Path.lstat
    def linked(path):
        if path == repo/'installer/build-cpu':
            return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
        return original(path)
    monkeypatch.setattr(Path,'lstat',linked)
    with pytest.raises(ValueError,match='Linked'):
        payload.stage(repo,'cpu')
    with pytest.raises(ValueError,match='variant'):
        payload.stage(repo,'../outside')
