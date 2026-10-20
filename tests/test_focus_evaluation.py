import pytest

from src.evaluation.focus import evaluate_labels, render_review


def report():
    return {"report_id": "study", "groups": [
        {"group_id": "g1", "version_ids": ["a", "b", "c", "d"],
         "ranking": {"recommended": ["a", "b", "c"]}},
        {"group_id": "g2", "version_ids": ["e", "f"],
         "ranking": {"recommended": []}},
    ]}


def label(key, best, grouping="correct", reviewed=True):
    return dict(group_id=key, best=best, grouping=grouping, reviewed=reviewed)


def test_unlabelled_has_no_accuracy():
    result = evaluate_labels(report(), {"report_id": "study", "groups": []})
    assert result["top3_best_set_hit_rate"] is None
    assert result["reviewed_groups"] == 0 and result["unreviewed_groups"] == 2


def test_abstention_counts_as_miss_and_coverage_is_separate():
    result = evaluate_labels(report(), {"report_id": "study", "groups": [
        label("g1", ["b", "d"]), label("g2", ["e"])]})
    assert result["top1_best_set_hit_rate"] == 0
    assert result["top3_best_set_hit_rate"] == 0.5
    assert result["recommendation_coverage"] == 0.5
    assert result["top3_hit_rate_over_three_photos"] == 1
    assert result["eligible_groups_over_three_photos"] == 1


def test_wrong_groups_and_empty_best_not_fabricated_truth():
    result = evaluate_labels(report(), {"report_id": "study", "groups": [
        label("g1", ["a"], grouping="incorrect"), label("g2", [])]})
    assert result["eligible_best_set_groups"] == 0
    assert result["incorrect_or_uncertain_groups"] == 1
    assert result["correct_groups_without_selection"] == 1
    assert "correct_groups_without_acceptable_best" not in result
    assert result["top3_best_set_hit_rate"] is None


@pytest.mark.parametrize("labels", [
    {"report_id": "wrong", "groups": []},
    {"report_id": "study", "groups": [label("unknown", [])]},
    {"report_id": "study", "groups": [label("g1", ["e"])]},
    {"report_id": "study", "groups": [label("g1", ["a", "a"])]},
    {"report_id": "study", "groups": [label("g1", []), label("g1", [])]},
    {"report_id": "study", "groups": [label("g1", [], grouping="invalid")]},
])
def test_invalid_labels_rejected(labels):
    with pytest.raises(ValueError):
        evaluate_labels(report(), labels)


def test_unreviewed_labels_do_not_count():
    result = evaluate_labels(report(), {"report_id": "study", "groups": [
        label("g1", ["a"], reviewed=False)]})
    assert result["eligible_best_set_groups"] == 0


def test_review_html_escapes_names_and_hides_algorithm():
    r = report()
    r["items"] = {key: dict(filename="<script>bad</script>.jpg", preview="media/a.jpg",
                            crop=None, evidence={}, captured_at=None, original="file:///a.jpg")
                  for key in ("a", "b", "c", "d", "e", "f")}
    output = render_review(r)
    assert "<script>bad</script>" not in output
    assert "&lt;script&gt;bad&lt;/script&gt;.jpg" in output
    assert 'class="algorithm" hidden' in output
    assert "fetch(" not in output
    assert "focus-labels.json" in output
    assert 'class="certainty"' in output
    assert 'schema_version:2' in output


@pytest.mark.parametrize("certainty", ["similar", "uncertain", "tentative", "none_acceptable"])
def test_v2_nonconfident_labels_never_become_ground_truth(certainty):
    best = [] if certainty == "none_acceptable" else ["a"]
    result = evaluate_labels(report(), {"report_id": "study", "schema_version": 2, "groups": [
        {**label("g1", best), "certainty": certainty}]})
    assert result["eligible_best_set_groups"] == 0
    assert result["top3_best_set_hit_rate"] is None
    assert result["reviewed_certainty_counts"][certainty] == 1


def test_v2_confident_set_counts_only_when_reviewed():
    labels = {"report_id": "study", "schema_version": 2, "groups": [
        {**label("g1", ["b"]), "certainty": "confident"},
        {**label("g2", ["e"], reviewed=False), "certainty": "confident"}]}
    result = evaluate_labels(report(), labels)
    assert result["eligible_best_set_groups"] == 1
    assert result["top3_best_set_hit_rate"] == 1
    assert result["reviewed_certainty_counts"]["confident"] == 1


@pytest.mark.parametrize("certainty,best", [
    ("confident", []), ("none_acceptable", ["a"]), ("invalid", []), (None, []),
])
def test_v2_contradictory_certainty_rejected(certainty, best):
    with pytest.raises(ValueError):
        evaluate_labels(report(), {"report_id": "study", "schema_version": 2,
                                  "groups": [{**label("g1", best), "certainty": certainty}]})


def test_unknown_label_schema_rejected():
    with pytest.raises(ValueError):
        evaluate_labels(report(), {"report_id": "study", "schema_version": 99, "groups": []})
