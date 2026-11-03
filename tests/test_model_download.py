import hashlib
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from src.recognition import model_download as download


@pytest.mark.parametrize('resume,ignored', [(False, False), (True, False), (True, True)])
def test_direct_mirror_resume_and_integrity(tmp_path, monkeypatch, resume, ignored):
    data = b'complete weights'
    monkeypatch.setattr(download, 'WEIGHT_SIZE', len(data))
    monkeypatch.setattr(download, 'WEIGHT_SHA256', hashlib.sha256(data).hexdigest())
    if resume:
        (tmp_path/'open_clip_model.safetensors.part').write_bytes(data[:4])
    class Session:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            assert not self.trust_env
            assert download.REVISION in url
            assert kwargs['headers'] == ({'Range': 'bytes=4-'} if resume else {})
            ranged = resume and not ignored
            response = SimpleNamespace(status_code=206 if ranged else 200,
                headers={'Content-Range': f'bytes 4-{len(data)-1}/{len(data)}'} if ranged else {},
                raise_for_status=lambda: None, iter_content=lambda size: [data[4:] if ranged else data])
            return nullcontext(response)
    monkeypatch.setattr(download.requests, 'Session', Session)
    assert download.download_bioclip2(tmp_path, 'https://hf-mirror.com').read_bytes() == data


def test_corrupt_download_is_not_published(tmp_path, monkeypatch):
    monkeypatch.setattr(download, 'WEIGHT_SIZE', 3)
    monkeypatch.setattr(download, 'WEIGHT_SHA256', hashlib.sha256(b'yes').hexdigest())
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs):
            return nullcontext(SimpleNamespace(status_code=200, headers={},
                raise_for_status=lambda: None, iter_content=lambda size: [b'bad']))
    monkeypatch.setattr(download.requests, 'Session', Session)
    with pytest.raises(OSError, match='integrity'):
        download.download_bioclip2(tmp_path, 'https://hf-mirror.com')
    assert not (tmp_path/'open_clip_model.safetensors').exists()
    assert len(list(tmp_path.glob('*.rejected-*'))) == 2
