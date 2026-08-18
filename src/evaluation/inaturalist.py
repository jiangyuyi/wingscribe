from __future__ import annotations

import hashlib
import json
import random
import time
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from .datasets import DatasetFormatError, EvaluationDataset, EvaluationSample


API_URL = "https://api.inaturalist.org/v1/observations"
ALLOWED_LICENSES = frozenset({"cc0", "cc-by", "cc-by-sa"})
ALLOWED_IMAGE_HOSTS = frozenset({"inaturalist-open-data.s3.amazonaws.com"})
MANIFEST_SCHEMA_VERSION = 1


def _medium_photo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_IMAGE_HOSTS:
        raise ValueError(f"Unsupported iNaturalist image URL: {url}")
    filename = parsed.path.rsplit("/", 1)[-1]
    if "." not in filename:
        raise ValueError(f"Image URL does not contain an extension: {url}")
    extension = filename.rsplit(".", 1)[-1]
    return url.rsplit("/", 1)[0] + f"/medium.{extension}"


def _resolve_image_path(root: Path, raw_path: Any) -> Path:
    relative_path = Path(str(raw_path or ""))
    if not str(raw_path or "").strip() or relative_path.is_absolute():
        raise DatasetFormatError("Manifest image path must be relative and non-empty")
    resolved = (root / relative_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DatasetFormatError(f"Manifest image path escapes its root: {raw_path}") from exc
    return resolved


def _verify_image(path: Path) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Downloaded file is not a valid image: {path}") from exc


def _validate_sample_source(sample: dict[str, Any]) -> str:
    license_code = str(sample.get("license_code") or "").lower()
    if license_code not in ALLOWED_LICENSES:
        raise DatasetFormatError(f"Manifest photo license is not allowed: {license_code or 'missing'}")
    try:
        return _medium_photo_url(str(sample.get("image_url") or ""))
    except ValueError as exc:
        raise DatasetFormatError("Manifest contains an unsupported image URL") from exc


def _observation_record(observation: dict[str, Any]) -> dict[str, Any] | None:
    taxon = observation.get("taxon") or {}
    if taxon.get("rank") != "species" or not taxon.get("name"):
        return None

    geojson = observation.get("geojson") or {}
    coordinates = geojson.get("coordinates")
    if geojson.get("type") != "Point" or not isinstance(coordinates, list) or len(coordinates) < 2:
        return None

    photo = next(
        (
            item
            for item in observation.get("photos") or []
            if str(item.get("license_code") or "").lower() in ALLOWED_LICENSES
            and not item.get("hidden", False)
        ),
        None,
    )
    if photo is None:
        return None

    observation_id = int(observation["id"])
    photo_id = int(photo["id"])
    image_url = _medium_photo_url(str(photo["url"]))
    extension = Path(urlparse(image_url).path).suffix.lower() or ".jpg"
    sample_id = f"inat-{observation_id}-{photo_id}"
    return {
        "sample_id": sample_id,
        "observation_id": observation_id,
        "photo_id": photo_id,
        "taxon_id": int(taxon["id"]),
        "expected_label": str(taxon["name"]),
        "common_name": str(taxon.get("preferred_common_name") or ""),
        "observed_on": observation.get("observed_on"),
        "latitude": float(coordinates[1]),
        "longitude": float(coordinates[0]),
        "place_guess": str(observation.get("place_guess") or ""),
        "license_code": str(photo["license_code"]).lower(),
        "attribution": str(photo.get("attribution") or ""),
        "image_url": image_url,
        "image_path": f"images/{sample_id}{extension}",
        "sha256": None,
    }


def fetch_observation_pool(
    client: httpx.Client,
    *,
    place_id: int = 6903,
    taxon_id: int = 3,
    cutoff_date: str = "2025-12-31",
    max_api_records: int = 20_000,
    request_delay_seconds: float = 0.1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_api_records < 1:
        raise ValueError("max_api_records must be at least 1")
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must not be negative")

    records: list[dict[str, Any]] = []
    seen_observations: set[int] = set()
    cursor: int | None = None
    fetched = 0
    total_results: int | None = None

    while fetched < max_api_records:
        params: dict[str, Any] = {
            "place_id": place_id,
            "taxon_id": taxon_id,
            "quality_grade": "research",
            "photos": "true",
            "photo_license": ",".join(sorted(ALLOWED_LICENSES)),
            "d2": cutoff_date,
            "order_by": "id",
            "order": "asc",
            "locale": "en",
            "per_page": min(200, max_api_records - fetched),
        }
        if cursor is not None:
            params["id_above"] = cursor

        response = client.get(API_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        if total_results is None:
            total_results = int(payload.get("total_results") or 0)
        observations = payload.get("results") or []
        if not observations:
            break

        page_max_id = cursor or 0
        for observation in observations:
            observation_id = int(observation["id"])
            page_max_id = max(page_max_id, observation_id)
            if observation_id in seen_observations:
                continue
            seen_observations.add(observation_id)
            fetched += 1
            record = _observation_record(observation)
            if record is not None:
                records.append(record)
            if fetched >= max_api_records:
                break

        if cursor is not None and page_max_id <= cursor:
            raise RuntimeError("iNaturalist pagination cursor did not advance")
        cursor = page_max_id
        if len(observations) < int(params["per_page"]):
            break
        if request_delay_seconds:
            time.sleep(request_delay_seconds)

    metadata = {
        "api_url": API_URL,
        "place_id": place_id,
        "taxon_id": taxon_id,
        "quality_grade": "research",
        "locale": "en",
        "cutoff_date": cutoff_date,
        "allowed_photo_licenses": sorted(ALLOWED_LICENSES),
        "reported_total_results": total_results,
        "api_records_scanned": fetched,
        "eligible_species_records": len(records),
        "truncated": bool(total_results is not None and fetched < total_results),
    }
    return records, metadata


def select_balanced_records(
    records: Iterable[dict[str, Any]],
    *,
    sample_count: int,
    max_per_species: int,
    seed: int,
) -> list[dict[str, Any]]:
    if sample_count < 1:
        raise ValueError("sample_count must be at least 1")
    if max_per_species < 1:
        raise ValueError("max_per_species must be at least 1")

    rng = random.Random(seed)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["expected_label"])].append(record)

    labels = sorted(grouped)
    rng.shuffle(labels)
    queues: dict[str, deque[dict[str, Any]]] = {}
    for label in labels:
        candidates = grouped[label]
        rng.shuffle(candidates)
        queues[label] = deque(candidates[:max_per_species])

    selected: list[dict[str, Any]] = []
    while len(selected) < sample_count:
        added = False
        for label in labels:
            if queues[label]:
                selected.append(dict(queues[label].popleft()))
                added = True
                if len(selected) == sample_count:
                    break
        if not added:
            break
    return selected


def build_manifest(
    records: list[dict[str, Any]],
    source_metadata: dict[str, Any],
    *,
    sample_count: int = 600,
    max_per_species: int = 3,
    seed: int = 20260818,
) -> dict[str, Any]:
    selected = select_balanced_records(
        records,
        sample_count=sample_count,
        max_per_species=max_per_species,
        seed=seed,
    )
    candidate_labels = sorted({str(record["expected_label"]) for record in records})
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset": "iNaturalist-China-Birds",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_metadata,
        "selection": {
            "seed": seed,
            "requested_samples": sample_count,
            "selected_samples": len(selected),
            "selected_species": len({item["expected_label"] for item in selected}),
            "max_per_species": max_per_species,
            "candidate_species": len(candidate_labels),
        },
        "candidate_labels": candidate_labels,
        "samples": selected,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_manifest_images(
    manifest: dict[str, Any],
    manifest_path: str | Path,
    client: httpx.Client,
    *,
    max_attempts: int = 3,
) -> dict[str, int]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    root = Path(manifest_path).resolve().parent
    downloaded = 0
    reused = 0
    failed = 0

    for sample in manifest.get("samples") or []:
        destination = _resolve_image_path(root, sample.get("image_path"))
        image_url = _validate_sample_source(sample)
        destination.parent.mkdir(parents=True, exist_ok=True)

        expected_hash = sample.get("sha256")
        if destination.is_file():
            existing_hash = _sha256(destination)
            try:
                _verify_image(destination)
            except ValueError:
                pass
            else:
                if not expected_hash or existing_hash == expected_hash:
                    sample["sha256"] = existing_hash
                    reused += 1
                    continue

        temporary = destination.with_suffix(destination.suffix + ".part")
        for attempt in range(max_attempts):
            try:
                with client.stream("GET", image_url) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as file_obj:
                        for chunk in response.iter_bytes():
                            file_obj.write(chunk)
                _verify_image(temporary)
                temporary.replace(destination)
                sample["sha256"] = _sha256(destination)
                downloaded += 1
                break
            except (httpx.HTTPError, OSError, ValueError):
                temporary.unlink(missing_ok=True)
                if attempt + 1 == max_attempts:
                    failed += 1

    return {"downloaded": downloaded, "reused": reused, "failed": failed}


def write_manifest(manifest: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)


def load_inaturalist_manifest(
    path: str | Path,
    *,
    require_images: bool = True,
    observed_on_from: str | None = None,
) -> EvaluationDataset:
    manifest_path = Path(path).expanduser().resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetFormatError(f"Unable to read iNaturalist manifest: {manifest_path}") from exc
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise DatasetFormatError("Unsupported iNaturalist manifest schema version")

    candidates = tuple(str(item).strip() for item in manifest.get("candidate_labels") or [])
    if not candidates or any(not item for item in candidates):
        raise DatasetFormatError("Manifest candidate_labels must be non-empty")
    if len(candidates) != len(set(candidates)):
        raise DatasetFormatError("Manifest candidate_labels contains duplicates")
    candidate_set = set(candidates)
    samples: list[EvaluationSample] = []
    sample_ids: set[str] = set()
    root = manifest_path.parent.resolve()
    if observed_on_from:
        try:
            date.fromisoformat(observed_on_from)
        except ValueError as exc:
            raise ValueError("observed_on_from must be an ISO date") from exc
    for item in manifest.get("samples") or []:
        observed_on = str(item.get("observed_on") or "")
        if observed_on_from and observed_on < observed_on_from:
            continue
        _validate_sample_source(item)
        sample_id = str(item.get("sample_id") or "").strip()
        if not sample_id or sample_id in sample_ids:
            raise DatasetFormatError("Manifest sample_id must be non-empty and unique")
        sample_ids.add(sample_id)
        expected_label = str(item.get("expected_label") or "")
        if not expected_label or expected_label not in candidate_set:
            raise DatasetFormatError("Manifest sample label is missing from candidate_labels")
        image_path = _resolve_image_path(root, item.get("image_path"))
        if require_images and not image_path.is_file():
            raise DatasetFormatError(f"Missing manifest image: {image_path}")
        expected_hash = str(item.get("sha256") or "").lower()
        if require_images:
            if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
                raise DatasetFormatError("Manifest image SHA-256 is missing or invalid")
            if _sha256(image_path) != expected_hash:
                raise DatasetFormatError(f"Image checksum mismatch: {image_path}")
        samples.append(
            EvaluationSample(
                sample_id=sample_id,
                image_path=image_path,
                expected_label=expected_label,
                split="test",
                metadata={
                    "observed_on": observed_on,
                    "month": int(observed_on[5:7]) if len(observed_on) >= 7 else None,
                    "national": "CN",
                },
            )
        )

    if not samples:
        raise DatasetFormatError("iNaturalist manifest contains no samples")
    return EvaluationDataset(
        name=str(manifest.get("dataset") or "iNaturalist-China-Birds"),
        samples=tuple(samples),
        candidate_labels=candidates,
        metadata={
            "manifest_sha256": _sha256(manifest_path),
            "source": manifest.get("source") or {},
            "selection": manifest.get("selection") or {},
            "observed_on_from": observed_on_from,
            "license_notice": "Each photo retains the license and attribution stored in the manifest.",
        },
    )
