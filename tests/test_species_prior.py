import json
from pathlib import Path

import pytest

from src.recognition.prior import (
    PriorApplication,
    PriorFormatError,
    PriorRecord,
    SpeciesPriorProvider,
    load_prior_provider,
    rerank_visual_logits,
)


def _provider() -> SpeciesPriorProvider:
    return SpeciesPriorProvider(
        [
            PriorRecord("Alpha", "national", "CN", None, 0.4),
            PriorRecord("Beta", "national", "CN", None, 0.2),
            PriorRecord("Alpha", "province", "CN-11", None, 0.1),
            PriorRecord("Alpha", "province", "CN-11", 5, 0.6),
            PriorRecord("Beta", "province", "CN-11", 5, 0.3),
            PriorRecord("Alpha", "city", "CN-11-BJ", 5, 0.7),
        ],
        source={"name": "fixture"},
    )


def test_prior_provider_uses_region_and_month_fallbacks():
    provider = _provider()

    application = provider.build_application(
        ["Alpha", "Beta"],
        region_context={"city": "CN-11-BJ", "province": "CN-11", "national": "CN"},
        month=5,
        weight=1.0,
        location_confidence=1.0,
        max_adjustment=3.0,
    )

    assert application.applied is True
    assert application.matches[0].region_level == "city"
    assert application.matches[0].probability == 0.7
    assert application.matches[1].region_level == "province"
    assert application.matches[1].probability == 0.3
    assert application.adjustments[0] == 0.0
    assert application.adjustments[1] == pytest.approx(-0.84729786)


def test_prior_provider_falls_back_to_annual_then_national():
    provider = _provider()

    annual = provider.build_application(
        ["Alpha", "Beta"],
        region_context={"province": "CN-11", "national": "CN"},
        month=6,
        weight=1.0,
        location_confidence=1.0,
        max_adjustment=10.0,
    )

    assert annual.matches[0].region_level == "province"
    assert annual.matches[0].month is None
    assert annual.matches[1].region_level == "national"


def test_prior_provider_is_noop_without_context_match_or_weight():
    provider = _provider()

    missing = provider.build_application(
        ["Alpha", "Beta"],
        region_context={"province": "CN-99"},
        month=5,
        weight=1.0,
        location_confidence=1.0,
        max_adjustment=2.0,
    )
    disabled = provider.build_application(
        ["Alpha", "Beta"],
        region_context={"national": "CN"},
        month=5,
        weight=0.0,
        location_confidence=1.0,
        max_adjustment=2.0,
    )

    assert missing == PriorApplication((0.0, 0.0), (None, None), False)
    assert disabled.adjustments == (0.0, 0.0)
    assert disabled.applied is False


def test_prior_provider_scales_confidence_and_clips_adjustments():
    provider = _provider()

    application = provider.build_application(
        ["Alpha", "Missing"],
        region_context={"national": "CN"},
        month=None,
        weight=2.0,
        location_confidence=1.0,
        max_adjustment=1.5,
    )

    assert application.adjustments == (0.0, -1.5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"month": 13, "weight": 1.0, "location_confidence": 1.0, "max_adjustment": 1.0},
        {"month": 1, "weight": -1.0, "location_confidence": 1.0, "max_adjustment": 1.0},
        {"month": 1, "weight": 1.0, "location_confidence": 2.0, "max_adjustment": 1.0},
    ],
)
def test_prior_provider_validates_application_parameters(kwargs):
    with pytest.raises(ValueError):
        _provider().build_application(["Alpha"], region_context={"national": "CN"}, **kwargs)


def test_rerank_visual_logits_can_promote_prior_supported_species():
    provider = _provider()
    application = provider.build_application(
        ["Alpha", "Beta"],
        region_context={"national": "CN"},
        month=None,
        weight=1.0,
        location_confidence=1.0,
        max_adjustment=2.0,
    )

    results = rerank_visual_logits([1.0, 1.5], ["Alpha", "Beta"], application, top_k=2)

    assert [item["scientific_name"] for item in results] == ["Alpha", "Beta"]
    assert results[0]["visual_logit"] == 1.0
    assert results[0]["prior_source"]["region_level"] == "national"
    assert sum(item["confidence"] for item in results) == pytest.approx(1.0)


def test_rerank_visual_logits_preserves_visual_result_for_noop_application():
    application = PriorApplication((0.0, 0.0), (None, None), False)

    results = rerank_visual_logits([2.0, 1.0], ["Alpha", "Beta"], application)

    assert [item["scientific_name"] for item in results] == ["Alpha", "Beta"]
    assert all(item["prior_adjustment"] == 0.0 for item in results)


def test_load_prior_provider_reads_versioned_json(tmp_path: Path):
    path = tmp_path / "prior.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": {"name": "fixture"},
                "records": [
                    {
                        "scientific_name": "Alpha",
                        "region_level": "national",
                        "region_code": "CN",
                        "month": None,
                        "probability": 0.5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    provider = load_prior_provider(path)

    assert provider.source == {"name": "fixture"}


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2, "records": []},
        {"schema_version": 1, "records": []},
        {
            "schema_version": 1,
            "records": [
                {
                    "scientific_name": "Alpha",
                    "region_level": "unknown",
                    "region_code": "CN",
                    "probability": 0.5,
                }
            ],
        },
    ],
)
def test_load_prior_provider_rejects_invalid_files(tmp_path: Path, payload):
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PriorFormatError):
        load_prior_provider(path)


def test_prior_provider_rejects_duplicate_records():
    record = PriorRecord("Alpha", "national", "CN", None, 0.5)

    with pytest.raises(PriorFormatError, match="Duplicate"):
        SpeciesPriorProvider([record, record])
