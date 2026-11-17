import asyncio
import hashlib
import json

import pytest
from PIL import Image

from src.metadata.avilist import DEFAULT_CATALOGUE, VERSION, load_catalogue
from src.recognition.region_filter import DEFAULT_CHINA, RegionSelector, RegionFilterError


@pytest.fixture
def selector():
    rows, manifest = load_catalogue()
    return RegionSelector([row['scientific_name'] for row in rows], manifest['version'])


@pytest.mark.parametrize('mode,location,expected', [
    ('auto', '北京奥森', 'china'), ('auto', '', 'china'), ('auto', 'Unknown', 'china'),
    ('auto', '日本东京', 'global'), ('auto', '美国黄石', 'global'),
    ('china', '日本东京', 'china'), ('global', '北京', 'global'), (None, '', 'global'),
    ('null', '北京', 'global'),
])
def test_simple_rules_and_membership(selector, mode, location, expected):
    result = selector.select(mode, location)
    assert result.metadata['effective_region'] == expected
    assert result.metadata['candidate_count'] == len(result.labels)
    selected = set(result.labels)
    assert result.labels == tuple(name for name in selector.labels if name in selected)
    assert 'Passer montanus' in result.labels
    assert 'Schoeniclus aureolus' in result.labels
    assert 'Parus cinereus' in result.labels
    if expected == 'china':
        assert 'Cyanocitta cristata' not in result.labels
        assert 'Cissa jefferyi' not in result.labels
        assert 'Lophura swinhoii' in result.labels  # Taiwan scope is intentional.
        assert 1400 < len(result.labels) < 2000
        assert result.metadata['regional_list_sha256']
    else:
        assert len(result.labels) == 11172


@pytest.mark.parametrize('problem', ['missing', 'empty', 'checksum', 'version', 'unknown', 'duplicate'])
def test_bad_china_list_fails_closed(selector, tmp_path, problem):
    path = tmp_path / 'china.csv'
    manifest = json.loads(DEFAULT_CHINA.with_suffix('.json').read_text(encoding='utf-8'))
    data = DEFAULT_CHINA.read_bytes()
    if problem == 'empty':
        data = b'taxon_id,scientific_name\n'
        manifest['species_count'] = 0
    elif problem == 'version':
        manifest['taxonomy_version'] = 'AviList-v2025b'
    elif problem == 'unknown':
        data = b'taxon_id,scientific_name\navibase-00000000,Testus alpha\n'
        manifest['species_count'] = 1
    elif problem == 'duplicate':
        data += data.splitlines(keepends=True)[1]
        manifest['species_count'] += 1
    manifest['subset_sha256'] = hashlib.sha256(data).hexdigest()
    if problem == 'checksum':
        manifest['subset_sha256'] = '0' * 64
    if problem != 'missing':
        path.write_bytes(data)
        path.with_suffix('.json').write_text(json.dumps(manifest), encoding='utf-8')
    selector.china_path = path
    with pytest.raises(RegionFilterError, match='global'):
        selector.select('china')
    assert len(selector.select('global').labels) == 11172
    assert len(selector.select('auto', '日本').labels) == 11172


def test_missing_foreign_dictionary_is_not_silently_domestic(selector, tmp_path):
    selector.foreign_path = tmp_path / 'missing.txt'
    with pytest.raises(RegionFilterError, match='词典'):
        selector.select('auto', '日本')
    assert selector.select('china').metadata['effective_region'] == 'china'
    assert selector.select('global').metadata['effective_region'] == 'global'


def test_pinned_taxonomy_is_required_for_china():
    selector = RegionSelector(['Passer montanus'], 'AviList-v2026')
    with pytest.raises(RegionFilterError):
        selector.select('china')
    assert selector.select('global').labels == ('Passer montanus',)


def test_foreign_substring_rule_preserves_file_order_and_explicit_modes(tmp_path):
    words = tmp_path / 'foreign.txt'
    words.write_text('美国\n日本\n', encoding='utf-8')
    selector = RegionSelector(['bird'], 'test', foreign_path=words, china_path=tmp_path / 'absent.csv')
    result = selector.select('auto', '日本和美国')
    assert result.labels == ('bird',)
    assert result.metadata['matched_foreign_word'] == '美国'
    assert result.metadata['foreign_dictionary_sha256']
    for mode in (None, 'global', 'null'):
        assert selector.select(mode).metadata['effective_region'] == 'global'
    with pytest.raises(RegionFilterError):
        selector.select('auto', '北京')
    with pytest.raises(RegionFilterError):
        selector.select('typo')


def test_unfinished_capture_cannot_build(tmp_path):
    from scripts.build_china_catalogue import build
    snapshot = tmp_path / 'incomplete.json'
    snapshot.write_text(json.dumps({'regions': {'CN': {}}}), encoding='utf-8')
    with pytest.raises(ValueError, match='four regional'):
        build(snapshot, tmp_path / 'out.csv')
    assert not (tmp_path / 'out.csv').exists()


def test_http_cloud_scope_rejected_before_provider_creation(monkeypatch):
    from fastapi.testclient import TestClient
    from src.recognition_service import create_app
    from src.recognition.cloud.factory import RecognizerFactory
    monkeypatch.setattr(RecognizerFactory, 'create', lambda *args, **kwargs: pytest.fail('Must not create provider'))
    with TestClient(create_app(config_override={})) as client:
        response = client.post('/api/recognize', json={
            'platform': 'huggingface', 'image_path': 'not-uploaded.jpg', 'region_filter': 'china'})
    assert response.status_code == 400
    assert '候选限定' in response.json()['detail']


def test_batch_cloud_scope_rejected_without_losing_global_sibling(monkeypatch):
    from src.recognition.batch import BatchRecognitionService
    from src.recognition.protocol import BatchRecognizeRequest, RecognizeResponse
    requests = BatchRecognizeRequest(images=[
        {'platform': 'huggingface', 'image_path': 'restricted.jpg', 'region_filter': 'china'},
        {'platform': 'huggingface', 'image_path': 'global.jpg'},
    ])
    seen = []
    class Backend:
        async def recognize_batch(self, images, **kwargs):
            seen.extend(image.image_path for image in images)
            return [RecognizeResponse(success=True, platform='huggingface', image_path=i.image_path,
                                      processing_time_ms=0) for i in images]
    class Factory:
        @staticmethod
        def create(platform):
            return Backend()
    service = BatchRecognitionService(recognizer_factory=Factory)
    batch = service.create_batch(requests)
    job = service.jobs[batch.batch_id]
    asyncio.run(service._process_batch(job))
    assert seen == ['global.jpg']
    assert not job.results[0].success
    assert job.results[1].success


def test_offline_rebuild_is_identical(tmp_path):
    from scripts.build_china_catalogue import build
    path = tmp_path / 'rebuilt.csv'
    build(output=path)
    assert path.read_bytes() == DEFAULT_CHINA.read_bytes()
    assert path.with_suffix('.json').read_bytes() == DEFAULT_CHINA.with_suffix('.json').read_bytes()


def test_real_database_uses_same_candidate_order_as_api(tmp_path, selector):
    from src.metadata.ioc_manager import IOCManager
    from src.pipeline_runner import WingScribePipeline
    pipeline = WingScribePipeline.__new__(WingScribePipeline)
    pipeline.config = {'recognition': {'region_filter': 'auto'}}
    pipeline.db = IOCManager(str(tmp_path / 'actual.db'))
    try:
        pipeline.all_labels = pipeline._get_taxonomy_labels()
        assert pipeline.all_labels == list(selector.labels)
        assert pipeline._select_candidates('北京') == selector.select('auto', '北京')
        assert pipeline._select_candidates('日本') == selector.select('auto', '日本')
    finally:
        pipeline.db.close()


def test_local_api_uses_same_restricted_candidates_and_reports_scope(selector, tmp_path):
    from src.recognition.local_adapter import LocalRecognitionAdapter
    from src.recognition.protocol import RecognizeRequest
    path = tmp_path / 'bird.jpg'
    Image.new('RGB', (16, 16), 'white').save(path)
    calls = []
    class Backend:
        def predict(self, image, labels, top_k):
            calls.append(labels)
            return [{'scientific_name': 'Passer montanus', 'confidence': .8}]
    adapter = LocalRecognitionAdapter()
    adapter._backend = Backend()
    request = RecognizeRequest(platform='local', image_path=str(path), region_filter='auto', location_tag='北京')
    result = asyncio.run(adapter.recognize(request))
    assert result.success
    assert calls == [list(selector.select('auto', '北京').labels)]
    assert result.region_selection == selector.select('auto', '北京').metadata
    adapter._backend.predict = lambda *args, **kwargs: [{'scientific_name': 'Cyanocitta cristata', 'confidence': .9}]
    assert not asyncio.run(adapter.recognize(request)).success


def test_pipeline_and_api_share_selection_and_cloud_is_explicit(selector):
    from src.pipeline_runner import WingScribePipeline
    from src.recognition.cloud.factory import RecognizerFactory
    from src.recognition.protocol import RecognizeRequest
    pipeline = WingScribePipeline.__new__(WingScribePipeline)
    pipeline.config = {'recognition': {'region_filter': 'auto'}}
    pipeline.all_labels = list(selector.labels)
    pipeline.taxonomy_version = VERSION
    for location in ('北京', '日本东京', '', '台湾'):
        assert pipeline._select_candidates(location) == selector.select('auto', location)
    pipeline.config['recognition']['mode'] = 'dongniao'
    with pytest.raises(RegionFilterError, match='不支持'):
        pipeline._select_candidate_labels('北京')
    request = RecognizeRequest(platform='huggingface', image_path='not-uploaded.jpg', region_filter='china')
    with pytest.raises(ValueError, match='候选限定'):
        RecognizerFactory.create_from_request(request)
