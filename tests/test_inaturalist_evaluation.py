import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image

from src.evaluation.datasets import DatasetFormatError
from src.evaluation.inaturalist import (
    _medium_photo_url,
    build_manifest,
    download_manifest_images,
    fetch_observation_pool,
    load_inaturalist_manifest,
    select_balanced_records,
    write_manifest,
)


def _image_bytes(color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(output, format="JPEG")
    return output.getvalue()


def _observation(
    observation_id: int,
    label: str,
    *,
    rank: str = "species",
    license_code: str = "cc-by",
    coordinates: list[float] | None = None,
) -> dict:
    photo_id = observation_id * 10
    return {
        "id": observation_id,
        "observed_on": "2025-01-01",
        "place_guess": "China",
        "geojson": {"type": "Point", "coordinates": coordinates or [116.4, 39.9]},
        "taxon": {
            "id": observation_id + 1000,
            "rank": rank,
            "name": label,
            "preferred_common_name": f"Common {label}",
        },
        "photos": [
            {
                "id": photo_id,
                "license_code": license_code,
                "attribution": "Test observer",
                "url": (
                    "https://inaturalist-open-data.s3.amazonaws.com/"
                    f"photos/{photo_id}/square.jpg"
                ),
            }
        ],
    }


def _record(index: int, label: str) -> dict:
    return {
        "sample_id": f"sample-{index}",
        "expected_label": label,
        "image_path": f"images/sample-{index}.jpg",
        "image_url": (
            "https://inaturalist-open-data.s3.amazonaws.com/"
            f"photos/{index}/medium.jpg"
        ),
        "license_code": "cc-by",
        "sha256": None,
    }


def test_medium_photo_url_rewrites_size_and_rejects_untrusted_urls():
    source = "https://inaturalist-open-data.s3.amazonaws.com/photos/7/square.JPG"

    assert _medium_photo_url(source).endswith("/medium.JPG")
    with pytest.raises(ValueError, match="Unsupported"):
        _medium_photo_url("https://example.com/photos/7/square.jpg")
    with pytest.raises(ValueError, match="Unsupported"):
        _medium_photo_url("http://inaturalist-open-data.s3.amazonaws.com/photos/7/square.jpg")


def test_fetch_observation_pool_paginates_and_filters_records():
    requests: list[httpx.Request] = []
    first_page = [_observation(index, f"Bird {index}") for index in range(1, 199)]
    first_page.extend(
        [_observation(199, "Beta", rank="subspecies"), _observation(200, "Gamma", license_code="cc-by-nc")]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            results = first_page
        else:
            results = [_observation(201, "Last Bird")]
        return httpx.Response(200, json={"total_results": 201, "results": results})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records, metadata = fetch_observation_pool(
            client,
            max_api_records=201,
            request_delay_seconds=0,
        )

    assert len(records) == 199
    assert records[-1]["expected_label"] == "Last Bird"
    assert requests[0].url.params["per_page"] == "200"
    assert requests[0].url.params["locale"] == "en"
    assert requests[1].url.params["id_above"] == "200"
    assert metadata["api_records_scanned"] == 201
    assert metadata["eligible_species_records"] == 199
    assert metadata["truncated"] is False


def test_fetch_observation_pool_rejects_a_stalled_cursor():
    repeated_page = [_observation(1, "Alpha")] * 200

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_results": 400, "results": repeated_page})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="did not advance"):
            fetch_observation_pool(client, max_api_records=400, request_delay_seconds=0)


def test_balanced_selection_is_deterministic_and_caps_each_species():
    records = [_record(index, label) for index, label in enumerate(["A"] * 5 + ["B"] * 2 + ["C"], 1)]

    first = select_balanced_records(records, sample_count=7, max_per_species=2, seed=7)
    second = select_balanced_records(records, sample_count=7, max_per_species=2, seed=7)

    assert first == second
    assert len(first) == 5
    assert all(sum(item["expected_label"] == label for item in first) <= 2 for label in {"A", "B", "C"})


def test_build_manifest_keeps_all_pool_labels_as_candidates():
    records = [_record(1, "A"), _record(2, "B"), _record(3, "C")]

    manifest = build_manifest(records, {"cutoff_date": "2025-12-31"}, sample_count=2, seed=3)

    assert manifest["candidate_labels"] == ["A", "B", "C"]
    assert manifest["selection"]["selected_samples"] == 2
    assert manifest["selection"]["candidate_species"] == 3


def test_download_manifest_images_downloads_valid_images_and_reuses_them(tmp_path: Path):
    image = _image_bytes()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=image, headers={"content-type": "image/jpeg"})

    manifest = build_manifest([_record(1, "A")], {}, sample_count=1)
    manifest_path = tmp_path / "manifest.json"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = download_manifest_images(manifest, manifest_path, client)
        second = download_manifest_images(manifest, manifest_path, client)

    assert first == {"downloaded": 1, "reused": 0, "failed": 0}
    assert second == {"downloaded": 0, "reused": 1, "failed": 0}
    assert calls == 1
    assert manifest["samples"][0]["sha256"] == hashlib.sha256(image).hexdigest()


def test_download_manifest_images_retries_invalid_content(tmp_path: Path):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"not an image")

    manifest = build_manifest([_record(1, "A")], {}, sample_count=1)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = download_manifest_images(manifest, tmp_path / "manifest.json", client, max_attempts=2)

    assert result == {"downloaded": 0, "reused": 0, "failed": 1}
    assert calls == 2
    assert not (tmp_path / "images" / "sample-1.jpg.part").exists()


@pytest.mark.parametrize("image_path", ["", "../outside.jpg"])
def test_download_manifest_images_rejects_unsafe_paths(tmp_path: Path, image_path: str):
    manifest = build_manifest([_record(1, "A")], {}, sample_count=1)
    manifest["samples"][0]["image_path"] = image_path
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        with pytest.raises(DatasetFormatError, match="path"):
            download_manifest_images(manifest, tmp_path / "manifest.json", client)


def test_load_inaturalist_manifest_validates_and_loads_offline_dataset(tmp_path: Path):
    image_path = tmp_path / "images" / "sample-1.jpg"
    image_path.parent.mkdir()
    image_path.write_bytes(_image_bytes())
    manifest = build_manifest([_record(1, "A"), _record(2, "B")], {}, sample_count=1, seed=1)
    selected = manifest["samples"][0]
    selected_path = tmp_path / selected["image_path"]
    if selected_path != image_path:
        selected_path.write_bytes(image_path.read_bytes())
    selected["sha256"] = hashlib.sha256(selected_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest, manifest_path)

    dataset = load_inaturalist_manifest(manifest_path)

    assert dataset.name == "iNaturalist-China-Birds"
    assert dataset.candidate_labels == ("A", "B")
    assert dataset.samples[0].expected_label in {"A", "B"}
    assert len(dataset.metadata["manifest_sha256"]) == 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest.update(schema_version=99), "schema"),
        (lambda manifest: manifest.update(candidate_labels=[]), "candidate_labels"),
        (lambda manifest: manifest.update(candidate_labels=["A", "A"]), "duplicates"),
        (lambda manifest: manifest["samples"].append(dict(manifest["samples"][0])), "sample_id"),
        (lambda manifest: manifest["samples"][0].update(image_path="../outside.jpg"), "escapes"),
        (lambda manifest: manifest["samples"][0].update(license_code="cc-by-nc"), "license"),
        (lambda manifest: manifest["samples"][0].update(image_url="https://example.com/bird.jpg"), "URL"),
    ],
)
def test_load_inaturalist_manifest_rejects_invalid_manifests(tmp_path: Path, mutation, message: str):
    manifest = build_manifest([_record(1, "A")], {}, sample_count=1)
    mutation(manifest)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatasetFormatError, match=message):
        load_inaturalist_manifest(manifest_path, require_images=False)


def test_load_inaturalist_manifest_detects_checksum_mismatch(tmp_path: Path):
    manifest = build_manifest([_record(1, "A")], {}, sample_count=1)
    image_path = tmp_path / manifest["samples"][0]["image_path"]
    image_path.parent.mkdir()
    image_path.write_bytes(_image_bytes())
    manifest["samples"][0]["sha256"] = "0" * 64
    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest, manifest_path)

    with pytest.raises(DatasetFormatError, match="checksum mismatch"):
        load_inaturalist_manifest(manifest_path)


def test_load_inaturalist_manifest_requires_checksum(tmp_path: Path):
    manifest = build_manifest([_record(1, "A")], {}, sample_count=1)
    image_path = tmp_path / manifest["samples"][0]["image_path"]
    image_path.parent.mkdir()
    image_path.write_bytes(_image_bytes())
    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest, manifest_path)

    with pytest.raises(DatasetFormatError, match="SHA-256"):
        load_inaturalist_manifest(manifest_path)


def test_prepare_inaturalist_script_can_show_help():
    completed = subprocess.run(
        [sys.executable, "scripts/prepare_inaturalist_eval.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--sample-count" in completed.stdout
    assert "--skip-download" in completed.stdout
