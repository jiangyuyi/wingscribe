import hashlib
import json

import pytest

from scripts.export_installer_lock import check, check_wheel, sha256


def test_manifest_detects_source_and_export_changes(tmp_path):
    paths = ['uv.lock', 'pyproject.toml', 'installer/locks/cpu.txt', 'installer/locks/cu128.txt']
    for name in paths:
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    manifest = tmp_path/'installer/locks/manifest.json'
    manifest.write_text(json.dumps({'sha256': {name: sha256(tmp_path/name) for name in paths}}))
    check(tmp_path)
    for name in paths:
        path = tmp_path/name
        original = path.read_bytes()
        path.write_bytes(b'changed')
        with pytest.raises(ValueError, match='stale or modified'):
            check(tmp_path)
        path.write_bytes(original)
    manifest.write_text(json.dumps({'sha256': {'../outside': 'x'}}))
    with pytest.raises(ValueError, match='paths'):
        check(tmp_path)


def test_wheel_requires_matching_name_and_full_hash(tmp_path):
    wheel = tmp_path/'torch-2.10.0+cpu.whl'
    wheel.write_bytes(b'fixture')
    digest = hashlib.sha256(b'fixture').hexdigest()
    (tmp_path/'uv.lock').write_text('[[package]]\nname="torch"\n'
        f'wheels=[{{url="https://example.com/torch-2.10.0%2Bcpu.whl",hash="sha256:{digest}"}}]\n')
    check_wheel(tmp_path, wheel)
    wheel.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='filename/hash'):
        check_wheel(tmp_path, wheel)
