"""Pure regrouping of saved evidence; no photo IO or inference."""
import copy
import hashlib
import json

from src.core.focus_modes import report_modes


def regroup(report: dict, parent_id: str, action: str, group_ids: list[str],
            item_keys: list[str]) -> tuple[dict, dict[str, list[str]]]:
    """Return a derived report and each group's immediate source groups."""
    groups = report['groups']
    by_id = {g['group_id']: g for g in groups}
    if len(set(group_ids)) != len(group_ids) or not set(group_ids) <= by_id.keys():
        raise ValueError('组不存在或重复')
    if len(set(item_keys)) != len(item_keys):
        raise ValueError('照片选择重复')
    selected = set(group_ids)
    if action == 'split':
        if len(group_ids) != 1 or not set(item_keys) < set(by_id[group_ids[0]]['version_ids']) or not item_keys:
            raise ValueError('拆分须选择一个组中的部分照片')
    elif action == 'merge':
        if len(group_ids) < 2 or item_keys:
            raise ValueError('合并须选择至少两个组，不接受照片列表')
    else:
        raise ValueError('未知分组操作')

    result = copy.deepcopy(report)
    result['groups'] = []
    parents = {}
    affected = [g for g in groups if g['group_id'] in selected]
    source_ids = [g['group_id'] for g in affected]
    merged = False

    def append_group(keys: list[str], sources: list[str]) -> None:
        gid = hashlib.sha256(json.dumps([parent_id, action, keys]).encode()).hexdigest()
        group = {'group_id': gid, 'version_ids': keys, 'reason': 'manual_' + action,
                 'ranking': affected[0]['ranking']}
        modes = report_modes(group, result['items'])
        group['ranking'] = modes['safe']
        group['ranking_modes'] = modes
        result['groups'].append(group)
        parents[gid] = sources

    for group in groups:
        gid = group['group_id']
        if gid not in selected:
            result['groups'].append(copy.deepcopy(group))
            parents[gid] = [gid]
        elif action == 'split':
            keys = group['version_ids']
            append_group([k for k in keys if k in item_keys], [gid])
            append_group([k for k in keys if k not in item_keys], [gid])
        elif not merged:
            append_group([k for g in affected for k in g['version_ids']], source_ids)
            merged = True
    result['revision'] = {'parent_snapshot_id': parent_id,
                          'root_snapshot_id': report.get('revision', {}).get('root_snapshot_id', parent_id),
                          'action': action, 'group_ids': sorted(group_ids),
                          'item_keys': sorted(item_keys), 'group_parents': parents}
    result.pop('report_id', None)
    result['report_id'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result, parents
