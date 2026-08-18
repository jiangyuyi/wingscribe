from pathlib import Path

from src.metadata.location_resolver import LocationResolver


def _write_dictionaries(tmp_path: Path):
    admin_path = tmp_path / "admin.csv"
    admin_path.write_text(
        "province,city,district,aliases\n"
        "浙江,杭州,临安,临安区|临安市\n"
        "北京,北京,朝阳,朝阳区\n"
        "辽宁,朝阳,,朝阳市\n"
        "陕西,西安,长安,长安区\n",
        encoding="utf-8",
    )
    aliases_path = tmp_path / "aliases.yaml"
    aliases_path.write_text(
        """version: 1
aliases:
  - match: 天目山
    province: 浙江
    city: 杭州
    district: 临安
    site: 天目山
  - match: 朝阳公园
    parent_matches: [北京]
    province: 北京
    city: 北京
    district: 朝阳
    site: 朝阳公园
  - match: 山
    province: 错误省
""",
        encoding="utf-8",
    )
    return admin_path, aliases_path


def test_missing_dictionaries_return_unknown(tmp_path):
    resolver = LocationResolver(tmp_path / "missing.csv", tmp_path / "missing.yaml")

    result = resolver.resolve("20260101_未知观鸟点")

    assert result.resolved is False
    assert result.location_raw == "20260101_未知观鸟点"
    assert result.to_dict()["source"] == "unknown"


def test_site_alias_has_priority_and_uses_longest_match(tmp_path):
    admin_path, aliases_path = _write_dictionaries(tmp_path)
    resolver = LocationResolver(admin_path, aliases_path)

    result = resolver.resolve("20260101_浙江临安天目山")

    assert result.source == "exact_site_alias"
    assert (result.province, result.city, result.district, result.site) == (
        "浙江",
        "杭州",
        "临安",
        "天目山",
    )


def test_alias_parent_constraint_must_be_present(tmp_path):
    admin_path, aliases_path = _write_dictionaries(tmp_path)
    resolver = LocationResolver(admin_path, aliases_path)

    unresolved = resolver.resolve("朝阳公园")
    resolved = resolver.resolve("北京_朝阳公园")

    assert unresolved.resolved is False
    assert resolved.site == "朝阳公园"


def test_ambiguous_admin_name_returns_unknown(tmp_path):
    admin_path, aliases_path = _write_dictionaries(tmp_path)
    resolver = LocationResolver(admin_path, aliases_path)

    result = resolver.resolve("20260101_朝阳")

    assert result.resolved is False


def test_parent_context_resolves_ambiguous_admin_name(tmp_path):
    admin_path, aliases_path = _write_dictionaries(tmp_path)
    resolver = LocationResolver(admin_path, aliases_path)

    beijing = resolver.resolve("北京_朝阳")
    liaoning = resolver.resolve("辽宁_朝阳")

    assert (beijing.province, beijing.city, beijing.district) == ("北京", "北京", "朝阳")
    assert (liaoning.province, liaoning.city, liaoning.district) == ("辽宁", "朝阳", None)


def test_admin_alias_and_separator_normalization(tmp_path):
    admin_path, aliases_path = _write_dictionaries(tmp_path)
    resolver = LocationResolver(admin_path, aliases_path)

    result = resolver.resolve("2026-01-01 / 陕西省 / 西安市 / 长安区")

    assert result.source == "exact_admin"
    assert (result.province, result.city, result.district) == ("陕西", "西安", "长安")


def test_invalid_alias_yaml_is_ignored(tmp_path):
    admin_path, _ = _write_dictionaries(tmp_path)
    aliases_path = tmp_path / "invalid.yaml"
    aliases_path.write_text("aliases: [", encoding="utf-8")

    resolver = LocationResolver(admin_path, aliases_path)

    assert resolver.resolve("浙江杭州临安").source == "exact_admin"


def test_dictionary_content_changes_version(tmp_path):
    admin_path, aliases_path = _write_dictionaries(tmp_path)
    first = LocationResolver(admin_path, aliases_path)
    aliases_path.write_text(aliases_path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    second = LocationResolver(admin_path, aliases_path)

    assert first.dictionary_version != second.dictionary_version


def test_results_are_cached_by_normalized_location(tmp_path):
    admin_path, aliases_path = _write_dictionaries(tmp_path)
    resolver = LocationResolver(admin_path, aliases_path)

    first = resolver.resolve("浙江 / 杭州 / 临安")
    second = resolver.resolve("浙江_杭州_临安")

    assert first is second
