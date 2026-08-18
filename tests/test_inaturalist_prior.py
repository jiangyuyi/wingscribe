import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import httpx
import pytest

from src.evaluation.datasets import DatasetFormatError
from src.evaluation.inaturalist_prior import (
    build_national_month_prior,
    fetch_species_month_counts,
    load_manifest_candidate_labels,
    write_prior_file,
)
from src.recognition.prior import PriorFormatError, load_prior_provider


def _observation(observation_id: int, label: str, observed_on: str = "2021-05-01") -> dict:
    return {
        "id": observation_id,
        "observed_on": observed_on,
        "taxon": {"rank": "species", "name": label},
    }


def test_fetch_species_month_counts_paginates_and_filters_dates():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        results = (
            [_observation(1, "Alpha"), _observation(2, "Beta", "2021-06-01")]
            if len(requests) == 1
            else [_observation(3, "Alpha", "invalid")]
        )
        return httpx.Response(200, json={"total_results": 3, "results": results})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        counts, source = fetch_species_month_counts(
            client,
            max_api_records=3,
            request_delay_seconds=0,
            per_page=2,
        )

    assert counts == Counter({("Alpha", 5): 1, ("Beta", 6): 1})
    assert requests[1].url.params["id_above"] == "2"
    assert requests[0].url.params["rank"] == "species"
    assert source["api_records_scanned"] == 3
    assert source["observations_counted"] == 2
    assert source["truncated"] is False


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
