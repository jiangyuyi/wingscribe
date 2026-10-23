from importlib import metadata
import os
import subprocess

import pytest
from scripts import installer_dependencies as deps


def test_domestic_pip_ignores_user_indexes_and_all_local_proxies(monkeypatch):
    for key in ['HTTPS_PROXY','http_proxy','ALL_PROXY','no_proxy','PIP_PROXY','PIP_INDEX_URL','PIP_EXTRA_INDEX_URL']:
        monkeypatch.setenv(key,'private-setting')
    before=dict(os.environ)
    env=deps.pip_environment(direct=True)
    assert not any(k.upper() in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','PIP_PROXY','PIP_INDEX_URL','PIP_EXTRA_INDEX_URL'] for k in env)
    assert env['NO_PROXY']=='*' and env['PIP_CONFIG_FILE']==os.devnull
    assert deps.pip_environment(direct=False)['HTTPS_PROXY']=='private-setting'
    assert dict(os.environ)==before


def test_runtime_check_exact_variant_missing_packages_and_platform_markers(tmp_path,monkeypatch):
    lock=tmp_path/'requirements.txt'
    lock.write_text('torch==2.10.0+cpu \\\n --hash=sha256:abc\n'
                    'not-installed==1 ; sys_platform == "nonexistent"\nfastapi==0.135.0\n')
    versions={'torch':'2.10.0+cpu','fastapi':'0.135.0'}
    monkeypatch.setattr(deps.metadata,'version',lambda name:versions[name])
    deps.runtime_check(lock)
    versions['torch']='2.10.0+cu128'
    with pytest.raises(ValueError,match='torch'):
        deps.runtime_check(lock)
    def missing(name):
        raise metadata.PackageNotFoundError(name)
    monkeypatch.setattr(deps.metadata,'version',missing)
    with pytest.raises(ValueError,match='missing'):
        deps.runtime_check(lock)


def test_fetch_uses_verified_offline_cache_before_network(tmp_path,monkeypatch):
    monkeypatch.setattr(deps,'check',lambda root:None)
    monkeypatch.setattr(deps,'quarantine_bad_cache',lambda root,wheels:None)
    monkeypatch.setattr(deps.sys,'version_info',(3,11))
    monkeypatch.setattr(deps.sys,'platform','win32')
    calls=[]
    monkeypatch.setattr(deps,'run_pip',lambda args,**kw:calls.append(args))
    deps.fetch(tmp_path,'cpu')
    assert len(calls)==1 and '--no-index' in calls[0] and '--require-hashes' in calls[0]


def test_mirror_failure_falls_back_explicitly_and_final_check_is_offline(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(deps,'check',lambda root:None)
    monkeypatch.setattr(deps,'quarantine_bad_cache',lambda root,wheels:None)
    monkeypatch.setattr(deps.sys,'version_info',(3,11))
    monkeypatch.setattr(deps.sys,'platform','win32')
    directory=tmp_path/'installer/locks';directory.mkdir(parents=True)
    (directory/'cu128.txt').write_text('torch==2.10.0+cu128 --hash=sha256:abc\n')
    calls=[]
    def run(args,*,direct=True):
        calls.append((args,direct))
        if len(calls)==1 or '--index-url' in args and 'mirrors.nju' in args[args.index('--index-url')+1]:
            raise subprocess.CalledProcessError(1,'pip')
    monkeypatch.setattr(deps,'run_pip',run)
    deps.fetch(tmp_path,'gpu')
    assert calls[1][1] is True and calls[2][1] is False
    assert '--require-hashes' in calls[2][0]
    assert '--no-index' in calls[-1][0]
    assert 'falling back to official' in capsys.readouterr().out


def test_install_refuses_host_interpreter(tmp_path,monkeypatch):
    monkeypatch.setattr(deps,'check',lambda root:None)
    monkeypatch.setattr(deps.sys,'version_info',(3,11))
    monkeypatch.setattr(deps.sys,'platform','win32')
    with pytest.raises(ValueError,match='non-build interpreter'):
        deps.install(tmp_path,'cpu')


def test_corrupt_cache_is_preserved_but_no_longer_selectable(tmp_path):
    import hashlib
    wheels=tmp_path/'wheels';wheels.mkdir()
    valid=wheels/'valid.whl';valid.write_bytes(b'good')
    bad=wheels/'bad.whl';bad.write_bytes(b'bad')
    (tmp_path/'uv.lock').write_text('[[package]]\nname="fixture"\nwheels=['+
        ','.join('{url="https://example.com/'+name+'",hash="sha256:'+hashlib.sha256(b'good').hexdigest()+'"}'
                 for name in ['valid.whl','bad.whl'])+']\n')
    deps.quarantine_bad_cache(tmp_path,wheels)
    assert valid.read_bytes()==b'good' and not bad.exists()
    assert next(wheels.glob('bad.whl.rejected-*')).read_bytes()==b'bad'
