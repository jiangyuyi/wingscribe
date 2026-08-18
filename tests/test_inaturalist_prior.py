import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import httpx
import pytest

from src.evaluation.datasets import DatasetFormatError
from src.evaluation.inaturalist_prior import (
    ProvinceRegion,
    build_province_annual_prior,
    build_national_month_prior,
    fetch_observation_province_assignments,
    fetch_species_province_counts,
    fetch_species_month_counts,
    load_manifest_candidate_labels,
    load_province_catalog,
    resolve_province_places,
    write_province_assignments,
    write_prior_file,
)
from src.recognition.prior import PriorFormatError, load_prior_provider


def _species_count(label: str, count: int) -> dict:
    return {"count": count, "taxon": {"rank": "species", "name": label}}


def test_fetch_species_month_counts_queries_monthly_aggregates():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        month = int(request.url.params["month"])
        results = (
            [_species_count("Alpha", 3), _species_count("Beta", 2)]
            if month == 5
            else [_species_count("Alpha", 4)]
        )
        return httpx.Response(200, json={"total_results": len(results), "results": results})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        counts, source = fetch_species_month_counts(
            client,
            max_api_records=10,
            request_delay_seconds=0,
            per_page=2,
            months=(5, 6),
        )

    assert counts == Counter({("Alpha", 6): 4, ("Alpha", 5): 3, ("Beta", 5): 2})
    assert requests[0].url.params["month"] == "5"
    assert requests[1].url.params["month"] == "6"
    assert requests[0].url.params["rank"] == "species"
    assert source["species_count_rows_scanned"] == 3
    assert source["observations_counted"] == 9
    assert source["reported_species_rows_by_month"] == {"5": 2, "6": 1}
    assert source["truncated"] is False


def test_fetch_species_month_counts_marks_truncated_limits():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"total_results": 2, "results": [_species_count("Alpha", 3)]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        _, source = fetch_species_month_counts(
            client,
            max_api_records=1,
            request_delay_seconds=0,
            per_page=1,
            months=(5,),
        )

    assert source["truncated"] is True


def test_load_and_resolve_province_catalog(tmp_path: Path):
    catalog = tmp_path / "provinces.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": {"country_place_id": 6903},
                "regions": [
                    {
                        "region_code": "CN-ZJ",
                        "province": "浙江",
                        "query": "Zhejiang",
                        "expected_name": "Zhejiang",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source, regions = load_province_catalog(catalog)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "Zhejiang"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 53098,
                        "name": "Zhejiang",
                        "admin_level": 10,
                        "ancestor_place_ids": [97395, 6903, 53098],
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        resolved = resolve_province_places(client, source, regions, request_delay_seconds=0)

    assert resolved[0].place_id == 53098
    assert resolved[0].region_code == "CN-ZJ"


def test_bundled_province_catalog_has_mainland_provincial_divisions():
    _, regions = load_province_catalog(
        Path("data/references/inaturalist_china_provinces.json")
    )

    assert len(regions) == 31
    assert len({region.region_code for region in regions}) == 31
    ningxia = next(region for region in regions if region.region_code == "CN-NX")
    assert ningxia.query == "Ningxia"
    assert ningxia.expected_name == "Ningxia Hui"
    xinjiang = next(region for region in regions if region.region_code == "CN-XJ")
    assert xinjiang.query == "Xinjiang"
    assert xinjiang.expected_name == "Xinjiang Uygur"


def test_resolve_province_places_rejects_unverified_match():
    region = ProvinceRegion("CN-ZJ", "浙江", "Zhejiang", "Zhejiang")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 1,
                        "name": "Zhejiang",
                        "admin_level": 10,
                        "ancestor_place_ids": [999],
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DatasetFormatError, match="Expected one"):
            resolve_province_places(
                client,
                {"country_place_id": 6903},
                [region],
                request_delay_seconds=0,
            )


def test_fetch_species_province_counts_queries_annual_aggregates():
    regions = (
        ProvinceRegion("CN-ZJ", "浙江", "Zhejiang", "Zhejiang", 10),
        ProvinceRegion("CN-SC", "四川", "Sichuan", "Sichuan", 20),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "month" not in request.url.params
        place_id = int(request.url.params["place_id"])
        results = [_species_count("Alpha", 3 if place_id == 10 else 5)]
        return httpx.Response(200, json={"total_results": 1, "results": results})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        counts, source = fetch_species_province_counts(
            client,
            regions,
            request_delay_seconds=0,
        )

    assert counts == Counter({("Alpha", "CN-SC"): 5, ("Alpha", "CN-ZJ"): 3})
    assert source["observations_counted"] == 8
    assert source["truncated"] is False


def test_fetch_observation_province_assignments_uses_place_ids_only():
    regions = (ProvinceRegion("CN-ZJ", "浙江", "Zhejiang", "Zhejiang", 53098),)
    samples = [
        {"sample_id": "one", "observation_id": 1},
        {"sample_id": "two", "observation_id": 2},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": 1, "place_ids": [6903, 53098]},
                    {"id": 2, "place_ids": [6903]},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assignments, source = fetch_observation_province_assignments(
            client,
            samples,
            regions,
            request_delay_seconds=0,
        )

    assert assignments == {"one": "CN-ZJ"}
    assert source["assigned_observations"] == 1
    assert source["unassigned_observations"] == 1


def test_build_national_month_prior_normalizes_each_bucket():
    counts = Counter({("Alpha", 1): 3, ("Beta", 1): 1, ("Alpha", 2): 2, ("Outside", 1): 10})
    source = {"observations_counted": 16}

    payload = build_national_month_prior(counts, ["Alpha", "Beta"], source, smoothing_alpha=1.0)

    assert len(payload["records"]) == 26
    annual = [record for record in payload["records"] if record["month"] is None]
    january = [record for record in payload["records"] if record["month"] == 1]
    assert sum(record["probability"] for record in annual) == pytest.approx(1.0)
    assert sum(record["probability"] for record in january) == pytest.approx(1.0)
    assert payload["source"]["matched_candidate_observations"] == 6
    assert payload["source"]["excluded_taxonomy_observations"] == 10


def test_build_province_annual_prior_normalizes_without_month_records():
    regions = (
        ProvinceRegion("CN-ZJ", "浙江", "Zhejiang", "Zhejiang", 10),
        ProvinceRegion("CN-SC", "四川", "Sichuan", "Sichuan", 20),
    )
    counts = Counter(
        {
            ("Alpha", "CN-ZJ"): 3,
            ("Beta", "CN-ZJ"): 1,
            ("Beta", "CN-SC"): 2,
            ("Outside", "CN-ZJ"): 10,
        }
    )
    payload = build_province_annual_prior(
        counts,
        ["Alpha", "Beta"],
        regions,
        {"observations_counted": 16},
    )

    assert len(payload["records"]) == 6
    assert all(record["month"] is None for record in payload["records"])
    for code in ("CN", "CN-ZJ", "CN-SC"):
        bucket = [record for record in payload["records"] if record["region_code"] == code]
        assert sum(record["probability"] for record in bucket) == pytest.approx(1.0)
    assert payload["source"]["aggregation"] == "province_annual_species_frequency"
    assert payload["source"]["excluded_taxonomy_observations"] == 10


def test_write_province_assignments_creates_versioned_sidecar(tmp_path: Path):
    path = tmp_path / "assignments.json"
    write_province_assignments({"sample-1": "CN-ZJ"}, {"name": "fixture"}, "a" * 64, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["manifest_sha256"] == "a" * 64
    assert payload["assignments"] == {"sample-1": "CN-ZJ"}


def test_generated_prior_can_be_loaded(tmp_path: Path):
    payload = build_national_month_prior(Counter({("Alpha", 1): 1}), ["Alpha", "Beta"], {})
    path = tmp_path / "prior.json"
    write_prior_file(payload, path)

    provider = load_prior_provider(path)

    assert provider.source["candidate_species"] == 2


def test_load_manifest_candidate_labels_validates_manifest(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"candidate_labels": ["Alpha", "Beta"]}), encoding="utf-8")
    assert load_manifest_candidate_labels(path) == ("Alpha", "Beta")

    path.write_text(json.dumps({"candidate_labels": ["Alpha", "Alpha"]}), encoding="utf-8")
    with pytest.raises(DatasetFormatError, match="unique"):
        load_manifest_candidate_labels(path)


@pytest.mark.parametrize("labels,alpha", [([], 1.0), (["Alpha", "Alpha"], 1.0), (["Alpha"], 0.0)])
def test_build_national_month_prior_validates_inputs(labels, alpha):
    with pytest.raises((PriorFormatError, ValueError)):
        build_national_month_prior(Counter(), labels, {}, smoothing_alpha=alpha)


def test_prepare_inaturalist_prior_script_can_show_help():
    completed = subprocess.run(
        [sys.executable, "scripts/prepare_inaturalist_prior.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--candidate-manifest" in completed.stdout
    assert "--cutoff-date" in completed.stdout
    assert "--region-mode" in completed.stdout
    assert "--province-assignment-output" in completed.stdout
