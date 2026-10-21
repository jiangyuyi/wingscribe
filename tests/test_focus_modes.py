from dataclasses import asdict
import json

import pytest

from src.core.culling import CaptureGroup
from src.core.focus import FocusEvidence, FocusPolicy, rank_group
from src.core.focus_modes import rank_with_mode, report_modes
from src.evaluation.focus import evaluate_labels, render_review


def sample():
    group = CaptureGroup('g', ('a', 'b', 'c'), 'time_candidate')
    rows = [FocusEvidence(k, 'sha', 'v', FocusPolicy(), status, (), None, bounds, {}, score)
            for k, status, bounds, score in [
                ('a', 'rankable', (0, 0, 100, 300), 1),
                ('b', 'rankable', (0, 0, 300, 100), 1.02),
                ('c', 'review', None, None)]]
    return group, rows


def test_modes_preserve_guard_ties_and_unknowns():
    g, rows = sample()
    before = [asdict(e) for e in rows]
    safe = rank_with_mode(g, rows)
    assist = rank_with_mode(g, rows, mode='assist')
    relaxed = rank_with_mode(g, rows, mode='relaxed')
    assert safe['recommended'] == ()
    assert assist['ranked'] == ('a', 'b') and assist['recommended'] == ()
    assert relaxed['recommended'] == ('a', 'b') and relaxed['unranked'] == ('c',)
    assert relaxed['tie_sets'] == (('a', 'b'),)
    for result in (safe, assist, relaxed):
        assert result['scale_guard_triggered']
        assert 'subject_scale_mismatch' in result['warnings']
        assert result['max_side_ratio'] == 2
    assert before == [asdict(e) for e in rows]
    with pytest.raises(ValueError):
        rank_with_mode(g, rows, mode='unknown')


@pytest.mark.parametrize('mode', ['safe', 'assist', 'relaxed'])
def test_modes_never_fill_unknown_subjects(mode):
    g, rows = sample()
    result = rank_with_mode(g, [rows[-1]], mode=mode)
    assert result['recommended'] == () and result['ranked'] == ()


def test_report_render_and_mode_specific_evaluation():
    g, rows = sample()
    items = {r.version_id: dict(filename=r.version_id, evidence=asdict(r), crop=None,
             preview='x.jpg', original='file:///x.jpg', captured_at=None) for r in rows}
    group = {**asdict(g), 'ranking': asdict(rank_group(g, rows))}
    group['ranking_modes'] = report_modes(group, items)
    report = json.loads(json.dumps(dict(report_id='r', items=items, groups=[group])))
    output = render_review(report)
    assert 'id="default-mode"' in output and 'class="group-mode"' in output
    assert '宽松推荐' in output and 'mode_override' in output
    for mode, coverage in [('safe', 0), ('assist', 0), ('relaxed', 1)]:
        labels = dict(report_id='r', schema_version=2, groups=[dict(group_id='g',
                      reviewed=True, grouping='correct', certainty='confident', best=['a'], mode=mode)])
        result = evaluate_labels(report, labels)
        assert result['recommendation_coverage'] == coverage
        assert result['reviewed_mode_counts'][mode] == 1
    labels['groups'][0]['mode_override'] = 'safe'
    with pytest.raises(ValueError, match='Inconsistent'):
        evaluate_labels(report, labels)


def test_safe_mode_matches_original_for_comparable_subjects():
    from dataclasses import replace
    g, rows = sample()
    rows[1] = replace(rows[1], bounds=rows[0].bounds)
    baseline = asdict(rank_group(g, rows))
    safe = rank_with_mode(g, rows)
    for key, value in baseline.items():
        assert safe[key] == value
    assist = rank_with_mode(g, rows, mode='assist')
    assert assist['recommended'] == () and assist['ranked'] == baseline['ranked']
