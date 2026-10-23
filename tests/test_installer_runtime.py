import hashlib
from pathlib import Path
import zipfile

import pytest

from scripts import installer_runtime as runtime


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'C:/escape',
                                '..\\escape', 'a:stream', 'NUL.txt',
                                'dir./file', 'a//b'])
def test_archive_rejects_unsafe_names_before_any_writes(tmp_path, name):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('valid.txt', 'untouched')
        info = zipfile.ZipInfo('placeholder')
        info.filename = name  # Preserve a hostile backslash even on Windows.
        z.writestr(info, 'invalid')
    with pytest.raises(ValueError):
        runtime.extract(archive, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('kind', ['case', 'conflict', 'link'])
def test_archive_rejects_aliases_and_links(tmp_path, kind):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('a', 'file')
        if kind == 'link':
            info = zipfile.ZipInfo('linked')
            info.external_attr = 0o120777 << 16
            z.writestr(info, 'a')
        else:
            z.writestr('A' if kind == 'case' else 'a/child', 'other')
    with pytest.raises(ValueError):
        runtime.extract(archive, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_runtime_cache_is_checked_and_unrelated_packages_preserved(tmp_path):
    archive = tmp_path / 'python.zip'
    output = tmp_path / 'python'
    output.mkdir()
    other = output / 'user-package.py'
    other.write_bytes(b'preserve')
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('python311._pth', 'original')
        z.writestr('python.dll', b'binary')
    overrides = {'python311._pth': b'python311.zip\nimport site\n'}
    runtime.extract(archive, output, overrides=overrides)
    runtime.extract(archive, output, check_only=True, overrides=overrides)
    assert other.read_bytes() == b'preserve'
    (output / 'python.dll').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='differs'):
        runtime.extract(archive, output, check_only=True, overrides=overrides)


def test_fetch_uses_hash_verified_cache_and_preserves_bad_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.urllib.request, 'build_opener',
                        lambda *args: pytest.fail('Cache must not use network'))
    cached = tmp_path / 'resource.zip'
    cached.write_bytes(b'verified')
    spec = (cached.name, hashlib.sha256(b'verified').hexdigest(), 'mirror', 'official')
    assert runtime.fetch(tmp_path, spec) == cached
    cached.write_bytes(b'bad')
    with pytest.raises(ValueError, match='retained'):
        runtime.fetch(tmp_path, spec)
    assert cached.read_bytes() == b'bad'


@pytest.mark.parametrize('resume', [True, False])
def test_fetch_resumes_or_restarts_when_server_ignores_range(tmp_path, monkeypatch, resume):
    import io
    payload = b'complete'
    (tmp_path / 'file.zip.0.part').write_bytes(payload[:3])
    class Response(io.BytesIO):
        status = 206 if resume else 200
        headers = {'Content-Range': 'bytes 3-7/8'} if resume else {}
    class Opener:
        def open(self, request, timeout):
            assert request.headers['Range'] == 'bytes=3-'
            return Response(payload[3:] if resume else payload)
    def opener(handler):
        assert handler.proxies == {}  # No environment or Windows proxy inheritance.
        return Opener()
    monkeypatch.setattr(runtime.urllib.request, 'build_opener', opener)
    spec = ('file.zip', hashlib.sha256(payload).hexdigest(), 'https://mirror/file', 'https://official/file')
    assert runtime.fetch(tmp_path, spec).read_bytes() == payload


def test_exiftool_invalid_archive_is_never_executed(tmp_path, monkeypatch):
    archive = tmp_path / 'installer/tools/exiftool-runtime.zip'
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b'changed')
    monkeypatch.setattr(runtime.subprocess, 'run', lambda *a, **kw: pytest.fail('Must not execute'))
    with pytest.raises(ValueError, match='changed'):
        runtime.prepare_exiftool(tmp_path, 'cpu')
    assert not (tmp_path / 'installer/build-cpu').exists()
