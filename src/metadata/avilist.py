"""Reproducible AviList species catalogue with explicitly sourced display names."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

VERSION = "AviList-v2025b"
SOURCE_URL = "https://www.avilist.org/wp-content/uploads/2026/06/AviList-v2025b-10Jun2026-extended.xlsx"
SOURCE_SHA256 = "2e1fd3374e23af732b04115b033dd9d97fc53ba275c312d02ef5d12cfb85c988"
SPECIES_COUNT = 11131
FIELDS = (
    "scientific_name", "chinese_name", "family_cn", "order_cn", "genus_cn",
    "genus_sci", "family_sci", "order_sci", "english_name", "taxon_id",
    "chinese_name_source",
)
DEFAULT_CATALOGUE = Path(__file__).resolve().parents[2] / "data/references/avilist-v2025b.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_species(workbook: Path) -> list[dict]:
    """Read species only; reject malformed or duplicate identifiers before import."""
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        rows = book.worksheets[0].iter_rows(values_only=True)
        headers = next(rows)
        required = {"Taxon_rank", "Scientific_name", "Order", "Family", "English_name_AviList", "AvibaseID"}
        if not required.issubset(headers):
            raise ValueError("Not an AviList workbook: required columns missing")
        result = []
        for cells in rows:
            row = dict(zip(headers, cells))
            if row["Taxon_rank"] != "species":
                continue
            name = str(row["Scientific_name"] or "").strip()
            result.append({
                "scientific_name": name,
                "chinese_name": name,
                "family_cn": row["Family"], "family_sci": row["Family"],
                "order_cn": row["Order"], "order_sci": row["Order"],
                "genus_cn": name.split()[0] if name else "",
                "genus_sci": name.split()[0] if name else "",
                "english_name": row["English_name_AviList"],
                "taxon_id": row["AvibaseID"],
                "chinese_name_source": "scientific-name fallback",
            })
        validate_species(result)
        return result
    finally:
        book.close()


def validate_species(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("Empty species catalogue")
    for field in ("scientific_name", "taxon_id"):
        values = [row.get(field) for row in rows]
        if any(not value for value in values) or len(set(values)) != len(values):
            raise ValueError(f"Missing or duplicate {field}")
    for row in rows:
        if len(row["scientific_name"].split()) != 2 or not row.get("family_sci") or not row.get("order_sci"):
            raise ValueError(f"Invalid species row: {row['scientific_name']}")


def build_catalogue(workbook: Path, ioc_names: Path, references: Path, output: Path) -> dict:
    if sha256(workbook) != SOURCE_SHA256:
        raise ValueError("Official AviList workbook checksum does not match the pinned release")
    rows = read_species(workbook)
    if len(rows) != SPECIES_COUNT:
        raise ValueError("Unexpected species count")
    names = {}
    book = load_workbook(ioc_names, read_only=True, data_only=True)
    try:
        values = book.worksheets[0].iter_rows(values_only=True)
        headers = next(values)
        if not {"IOC_15.1", "Chinese"}.issubset(headers):
            raise ValueError("Expected IOC 15.1 multilingual name source")
        for cells in values:
            row = dict(zip(headers, cells))
            if row.get("IOC_15.1") and row.get("Chinese"):
                names[row["IOC_15.1"]] = row["Chinese"]
    finally:
        book.close()
    sources = {ioc_names.name: sha256(ioc_names)}
    maps = {}
    for rank in ("order", "family", "genus"):
        source = references / f"bird_{rank}_mapping_complete.csv"
        with source.open(encoding="utf-8-sig", newline="") as stream:
            maps[rank] = {row[f"{rank.title()}_SCI"].casefold(): row[f"{rank.title()}_CN"] for row in csv.DictReader(stream)}
        sources[source.name] = sha256(source)
    for row in rows:
        name = row["scientific_name"]
        if name in names:
            row["chinese_name"] = names[name]
            # This is a display alias, NOT evidence of taxonomic equivalence.
            row["chinese_name_source"] = "IOC-15.1 Chinese; exact-name alias; concept unverified"
        for rank in maps:
            row[f"{rank}_cn"] = maps[rank].get(row[f"{rank}_sci"].casefold()) or row[f"{rank}_sci"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "version": VERSION, "species_count": len(rows), "source_url": SOURCE_URL,
        "source_sha256": SOURCE_SHA256, "catalogue_sha256": sha256(output),
        "citation": "AviList Core Team. 2026. AviList: The Global Avian Checklist, v2025b. https://doi.org/10.2173/avilist.v2025b",
        "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "name_sources_sha256": sources,
        "name_status_counts": dict(Counter(row["chinese_name_source"] for row in rows)),
        "transform": "species rows only; original order; IOC same-name Chinese display aliases; existing Chinese rank CSVs; no photo-label equivalence inferred",
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_catalogue(path: Path = DEFAULT_CATALOGUE) -> tuple[list[dict], dict]:
    manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    if manifest["version"] != VERSION or manifest["catalogue_sha256"] != sha256(path):
        raise ValueError("Catalogue version or checksum mismatch")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("Catalogue columns mismatch")
        rows = list(reader)
    validate_species(rows)
    if len(rows) != manifest["species_count"] or len(rows) != SPECIES_COUNT:
        raise ValueError("Catalogue species count mismatch")
    return rows, manifest
