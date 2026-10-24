import json

import pytest

from scripts.installer_artifacts import verify_manifest, write_manifest


def test_manifest_roundtrip_detects_changed_and_missing_volume(tmp_path):
    stem = 'WingScribe-Setup-GPU-1.2.3'
    exe = tmp_path / f'{stem}.exe'
    part = tmp_path / f'{stem}-1.bin'
    exe.write_bytes(b'installer')
    part.write_bytes(b'volume')
    manifest = write_manifest(tmp_path, 'gpu', '1.2.3')
    verify_manifest(manifest)
    part.write_bytes(b'change')
    with pytest.raises(ValueError, match='verification failed'):
        verify_manifest(manifest)
    part.unlink()
    with pytest.raises(ValueError, match='verification failed'):
        verify_manifest(manifest)


def test_missing_volume_and_empty_executable_rejected(tmp_path):
    stem = 'WingScribe-Setup-CPU-1.2.3'
    (tmp_path / f'{stem}.exe').write_bytes(b'')
    with pytest.raises(ValueError, match='empty'):
        write_manifest(tmp_path, 'cpu', '1.2.3')
    (tmp_path / f'{stem}-2.bin').write_bytes(b'volume')
    with pytest.raises(ValueError, match='contiguous'):
        write_manifest(tmp_path, 'cpu', '1.2.3')


def test_manifest_cannot_read_outside_directory(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'format': 1, 'mode': 'cpu', 'version': '1.2.3',
                                   'files': [{'name': '../private'}, {'name': 'WingScribe-Setup-CPU-1.2.3.exe'}]}))
    with pytest.raises(ValueError, match='filename'):
        verify_manifest(manifest)


def test_invalid_version_cannot_escape_output_directory(tmp_path):
    with pytest.raises(ValueError, match='version'):
        write_manifest(tmp_path, 'cpu', '../1.2.3')


def test_gpu_executable_alone_is_not_a_complete_package(tmp_path):
    (tmp_path / 'WingScribe-Setup-GPU-1.2.3.exe').write_bytes(b'installer')
    with pytest.raises(ValueError, match='volumes are missing'):
        write_manifest(tmp_path, 'gpu', '1.2.3')


def test_gpu_ci_upload_and_release_include_volumes():
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/build-installer.yml').read_text(encoding='utf-8'))
    upload = next(step for step in workflow['jobs']['build']['steps']
                  if step.get('name') == 'Upload GPU installer artifact')
    release = next(step for step in workflow['jobs']['release']['steps']
                  if step.get('name') == 'Create Release')
    for paths in [upload['with']['path'], release['with']['files']]:
        assert 'GPU-${{ steps.get_version.outputs.version }}-*.bin' in paths
        assert 'GPU-${{ steps.get_version.outputs.version }}.sha256.json' in paths
    script = (root / 'installer/installer-gpu.iss').read_text(encoding='utf-8-sig')
    assert 'Compression=lzma2\nSolidCompression=yes\nDiskSpanning=yes' in script


@pytest.mark.parametrize('change', ['duplicate', 'missing_exe', 'missing_volume'])
def test_incomplete_manifest_is_rejected(tmp_path, change):
    stem = 'WingScribe-Setup-GPU-1.2.3'
    (tmp_path / f'{stem}.exe').write_bytes(b'installer')
    (tmp_path / f'{stem}-1.bin').write_bytes(b'volume')
    manifest = write_manifest(tmp_path, 'gpu', '1.2.3')
    data = json.loads(manifest.read_text())
    if change == 'duplicate':
        data['files'].append(data['files'][0])
    elif change == 'missing_exe':
        data['files'] = data['files'][1:]
    else:
        data['files'] = data['files'][:1]
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        verify_manifest(manifest)
