import asyncio

import pytest

from src.web import location_service


def test_preview_locations_reports_dictionary_status_and_results(tmp_path):
    dictionary_dir = tmp_path / "config" / "dictionaries"
    dictionary_dir.mkdir(parents=True)
    (dictionary_dir / "china_admin_divisions.csv").write_text(
        "province,city,district,aliases\n浙江,杭州,临安,临安区\n",
        encoding="utf-8",
    )
    (dictionary_dir / "location_aliases.yaml").write_text(
        "aliases:\n  - match: 天目山\n    province: 浙江\n    city: 杭州\n    district: 临安\n",
        encoding="utf-8",
    )

    response = location_service.preview_locations(tmp_path, ["浙江_临安", "天目山"])

    assert response["dictionary"]["admin_available"] is True
    assert response["dictionary"]["aliases_available"] is True
    assert response["dictionary"]["admin_record_count"] == 1
    assert response["dictionary"]["alias_rule_count"] == 1
    assert len(response["dictionary"]["version"]) == 16
    assert response["results"][0]["source"] == "exact_admin"
    assert response["results"][1]["source"] == "exact_site_alias"


def test_preview_locations_is_safe_when_dictionaries_are_missing(tmp_path):
    response = location_service.preview_locations(tmp_path, ["未知地点"])

    assert response["dictionary"]["admin_available"] is False
    assert response["dictionary"]["aliases_available"] is False
    assert response["results"][0]["source"] == "unknown"


def test_location_preview_endpoint_delegates_to_service(monkeypatch, tmp_path):
    from src.web import app as web_app

    monkeypatch.setattr(web_app, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        web_app.location_service,
        "preview_locations",
        lambda base_dir, locations: {"base_dir": base_dir, "locations": locations},
    )

    result = asyncio.run(web_app.preview_locations(web_app.LocationPreviewRequest(locations=["北京"])))

    assert result == {"base_dir": tmp_path, "locations": ["北京"]}


@pytest.mark.parametrize("locations", [[], ["北京"] * 101, [""], ["x" * 501]])
def test_location_preview_endpoint_rejects_invalid_batches(locations):
    from src.web import app as web_app

    with pytest.raises(web_app.HTTPException) as exc_info:
        asyncio.run(web_app.preview_locations(web_app.LocationPreviewRequest(locations=locations)))

    assert exc_info.value.status_code == 400
