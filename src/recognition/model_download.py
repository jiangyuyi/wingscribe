"""Pinned BioCLIP2 download with direct mirror access and resumable staging."""
import hashlib
import logging
from uuid import uuid4
from filelock import FileLock, Timeout
from pathlib import Path

import requests

REVISION = '2957b322090f9cb17ae72c71981c7218a28d81e0'
WEIGHT_SHA256 = 'b7b2bf6fbc95799e42630e394cf95803892ab447c1a8ab629dbc82fbeaf7dfef'
WEIGHT_SIZE = 1710517724


def download_bioclip2(directory: Path, mirror: str | None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(directory / '.download.lock', timeout=1):
            target = directory / 'open_clip_model.safetensors'
            if target.exists():
                with target.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() == WEIGHT_SHA256:
                        return target
                raise OSError('Existing model checksum mismatch; preserve it for inspection')
            return _download(directory, mirror)
    except Timeout as exc:
        raise OSError('BioCLIP2 is already being downloaded by another task') from exc


def _download(directory: Path, mirror: str | None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'open_clip_model.safetensors'
    partial = target.with_suffix(target.suffix + '.part')
    endpoints = list(dict.fromkeys([mirror or 'https://huggingface.co', 'https://huggingface.co']))
    errors = []
    for endpoint in endpoints:
        try:
            with requests.Session() as session:
                session.trust_env = not bool(mirror and endpoint == mirror)
                offset = partial.stat().st_size if partial.exists() else 0
                if offset > WEIGHT_SIZE:
                    raise ValueError('Partial model exceeds expected size; preserve it for inspection')
                if offset < WEIGHT_SIZE:
                    url = endpoint.rstrip('/') + f'/imageomics/bioclip-2/resolve/{REVISION}/open_clip_model.safetensors'
                    headers = {'Range': f'bytes={offset}-'} if offset else {}
                    with session.get(url, headers=headers, stream=True, timeout=(15, 60)) as response:
                        response.raise_for_status()
                        append = offset > 0 and response.status_code == 206
                        if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                            raise ValueError('Download server returned an inconsistent byte range')
                        if not append:
                            offset = 0
                        progress = offset * 10 // WEIGHT_SIZE
                        with partial.open('ab' if append else 'wb') as stream:
                            for chunk in response.iter_content(1024 * 1024):
                                stream.write(chunk)
                                offset += len(chunk)
                                if offset > WEIGHT_SIZE:
                                    raise ValueError('Downloaded model exceeds expected size')
                                if offset * 10 // WEIGHT_SIZE > progress:
                                    progress = offset * 10 // WEIGHT_SIZE
                                    logging.warning('BioCLIP2 download %d%% (%d/%d bytes)', progress * 10, offset, WEIGHT_SIZE)
                with partial.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if partial.stat().st_size != WEIGHT_SIZE or digest != WEIGHT_SHA256:
                    partial.rename(partial.with_name(partial.name + '.rejected-' + uuid4().hex))
                    raise ValueError('BioCLIP2 integrity check failed; rejected file preserved')
                partial.replace(target)
                return target
        except (requests.RequestException, OSError, ValueError) as exc:
            errors.append(f'{endpoint}: {type(exc).__name__}: {exc}')
            logging.warning('BioCLIP2 download failed at %s; trying next configured source', endpoint)
    raise OSError('BioCLIP2 download failed. ' + '; '.join(errors))
