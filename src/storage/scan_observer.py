"""Persist a local JPEG attempt around the synchronous image pipeline."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4


def observe_image(pipeline, provider, entry, meta):
    catalogue = pipeline.catalogue
    # Validate the IO boundary before registering a logical relative path.
    path = Path(provider.get_local_path(entry.path))
    root = Path(provider.base_dir)
    relative = path.relative_to(root).as_posix()
    with catalogue.transaction() as tx:
        source = tx.register_source(str(root.absolute()))
        asset = tx.discover_asset(source, relative)
    session = getattr(pipeline, '_job_session', None)
    key = (pipeline.job_id + ':' if session else '') + uuid4().hex
    item_id = None
    version = None
    # Observation keys include job provenance; filenames must use only a UUID.
    state = {'outcome': 'failed', 'detections': [], 'attempt_key': key.rsplit(':', 1)[-1]}
    recognition = pipeline.config.get('recognition', {})
    parameters = {
        'processing': pipeline.config.get('processing', {}),
        'recognition': {name: recognition.get(name) for name in (
            'mode', 'region_filter', 'top_k', 'alternatives_threshold', 'low_confidence_threshold')},
        'model_type': recognition.get('local', {}).get('model_type'),
        'candidates_sha256': hashlib.sha256(json.dumps(
            pipeline._select_candidate_labels(meta.get('location_tag', 'Unknown')),
            ensure_ascii=False).encode()).hexdigest(),
        'output_root': str(pipeline.output_root),
        'output': pipeline.config.get('paths', {}).get('output', {}),
        'metadata': meta,
    }
    model = str(parameters['model_type'] or recognition.get('mode', 'local'))
    taxonomy = pipeline.taxonomy_version
    try:
        before = path.stat()
        with path.open('rb') as stream:
            fingerprint = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('Source changed while fingerprinting')
        with catalogue.transaction() as tx:
            registered = tx.register_asset(source, relative, size_bytes=after.st_size,
                mtime_ns=after.st_mtime_ns, fingerprint=fingerprint,
                captured_at=meta.get('captured_date'))
        version = registered['version_id']
        state['version_id'] = version
        state['reuse_context'] = hashlib.sha256(json.dumps([parameters, model, taxonomy],
            ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if session:
            item_id = session.enqueue(pipeline.job_id, version)
            if pipeline._should_stop():
                with catalogue.transaction() as tx:
                    tx.record_observation(asset, key, outcome='skipped', version_id=version,
                                          reason='stopped_before_execution')
                return
            if session.claim(pipeline.job_id, item_id) is None:
                # Overlapping selected folders must not execute the same item twice.
                with catalogue.transaction() as tx:
                    tx.record_observation(asset, key, outcome='skipped', version_id=version,
                                          reason='already_enqueued_in_this_job')
                return
        for previous in reversed(catalogue.list_analyses(version)):
            if (previous['outcome'] in {'succeeded', 'no_detection', 'quality_filtered'}
                    and previous['model'] == model and previous['taxonomy_version'] == taxonomy
                    and json.loads(previous['parameters_json']) == parameters):
                outputs = catalogue.list_detections(previous['id'])
                if all(not d['output_path'] or Path(d['output_path']).is_file() for d in outputs):
                    with catalogue.transaction() as tx:
                        tx.record_observation(asset, key, outcome='skipped', version_id=version,
                            analysis_id=previous['id'], reason='unchanged_version_and_parameters')
                    if session:
                        session.finish_item(item_id, 'skipped', reason='unchanged_version_and_parameters')
                    return
        pipeline._process_image(provider, entry, meta, state)
        final = path.stat()
        if (after.st_size, after.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
            raise RuntimeError('Source changed during processing')
    except Exception as exc:
        if version is None and isinstance(exc, OSError):
            with catalogue.transaction() as tx:
                tx.set_asset_availability(asset, 'unavailable' if isinstance(exc, FileNotFoundError) else 'unknown')
        _save(catalogue, asset, version, key, model, parameters, taxonomy, state, str(exc) or type(exc).__name__)
        if session and item_id:
            session.finish_item(item_id, 'failed', error=str(exc) or type(exc).__name__)
        raise
    _save(catalogue, asset, version, key, model, parameters, taxonomy, state)
    if session:
        session.finish_item(item_id, 'completed')


def _save(catalogue, asset, version, key, model, parameters, taxonomy, state, error=None):
    outcome = 'failed' if error else state['outcome']
    with catalogue.transaction() as tx:
        analysis = None
        if version:
            analysis = tx.record_analysis(version, key, model=model, parameters=parameters,
                taxonomy_version=taxonomy, outcome=outcome,
                detections=state['detections'], error=error)
        tx.record_observation(asset, key, outcome=outcome, version_id=version,
            analysis_id=analysis, error=error)
