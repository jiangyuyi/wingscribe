"""Human-labelled, group-level evaluation. Unlabelled groups are never truth."""
import html
import json


def evaluate_labels(report: dict, labels: dict) -> dict:
    if labels.get("report_id") != report["report_id"]:
        raise ValueError("Labels belong to a different report")
    groups = {g["group_id"]: g for g in report["groups"]}
    seen = set()
    judged = eligible = hits1 = hits3 = recommended = rejected_groups = 0
    larger_groups = larger_hits = no_best = 0
    for label in labels.get("groups", []):
        key = label["group_id"]
        if key not in groups or key in seen:
            raise ValueError("Unknown or duplicate labelled group")
        seen.add(key)
        if label.get("reviewed") is not True:
            continue
        valid = label.get("grouping")
        if valid not in ("correct", "incorrect", "uncertain"):
            raise ValueError("Invalid grouping judgement")
        best = label.get("best", [])
        if len(set(best)) != len(best) or not set(best) <= set(groups[key]["version_ids"]):
            raise ValueError("Best choices must be unique members of this group")
        judged += 1
        if valid != "correct":
            rejected_groups += 1
            continue
        if not best:
            no_best += 1
            continue  # Empty selection is ambiguous, never a rejection or a miss.
        eligible += 1
        picks = groups[key]["ranking"]["recommended"]
        recommended += bool(picks)
        hits1 += bool(set(picks[:1]) & set(best))
        hits3 += bool(set(picks[:3]) & set(best))
        if len(groups[key]["version_ids"]) > 3:
            larger_groups += 1
            larger_hits += bool(set(picks[:3]) & set(best))
    return {
        "total_groups": len(groups), "reviewed_groups": judged,
        "incorrect_or_uncertain_groups": rejected_groups,
        "eligible_best_set_groups": eligible,
        "correct_groups_without_selection": no_best,
        "eligible_groups_over_three_photos": larger_groups,
        "top3_hit_rate_over_three_photos": larger_hits / larger_groups if larger_groups else None,
        "recommendation_coverage": recommended / eligible if eligible else None,
        "top1_best_set_hit_rate": hits1 / eligible if eligible else None,
        "top3_best_set_hit_rate": hits3 / eligible if eligible else None,
        "unreviewed_groups": len(groups) - judged,
        "scope": "exploratory single-session labels; not an independent test benchmark",
    }


def render_review(report: dict) -> str:
    """Offline review; no network, labels export locally, scores hidden initially."""
    cards = []
    for number, group in enumerate(report["groups"], 1):
        gid = html.escape(group["group_id"], quote=True)
        photos = []
        for key in group["version_ids"]:
            item = report["items"][key]
            title = html.escape(item["filename"])
            preview = html.escape(item["preview"], quote=True)
            crop = html.escape(item["crop"], quote=True) if item["crop"] else ""
            detail = (f'<details><summary>主体 100% 细节（可滚动）</summary>'
                      f'<div class="crop"><img src="{crop}"></div></details>' if crop
                      else '<p>没有有效主体框，请查看整图副本；这不表示失焦。</p>')
            reasons = {
                "no_valid_subject": "未找到可用鸟体，请人工检查",
                "subject_too_small": "主体像素不足",
                "insufficient_structure": "细节不足，无法可靠排序",
                "noise_or_fine_texture": "噪声或细密纹理影响判断",
                "severe_clipping": "曝光截断较严重",
            }
            result = item["evidence"]
            score = result.get("score")
            evidence = ("相对细节指标：" + f"{score:.3f}" + "（非合焦概率）"
                        if score is not None else "需人工复核")
            if result.get("reasons"):
                evidence += "；" + "；".join(reasons.get(r, "需人工复核") for r in result["reasons"])
            photos.append(f'<article><label><input type="checkbox" value="{html.escape(key, quote=True)}">'
                          f' 可接受的最佳照片：{title}</label><p>{html.escape(item["captured_at"] or "时间未知")}</p>'
                          f'<a href="{html.escape(item["original"], quote=True)}">打开完整测试副本</a>'
                          f'<img class="preview" src="{preview}" alt="{title}">{detail}'
                          f'<p class="algorithm" hidden>{html.escape(evidence)}</p></article>')
        ranking = "相对推荐：" + ("、".join(
            report["items"][key]["filename"] for key in group["ranking"]["recommended"]
        ) or "本组暂不推荐，请人工检查")
        if group["ranking"].get("tie_sets"):
            ranking += "\n分数接近，请对比：" + "；".join(
                "、".join(report["items"][key]["filename"] for key in tied)
                for tied in group["ranking"]["tie_sets"])
        ranking = html.escape(ranking + "\n推荐仅表示组内相对优先，不代表已经合焦。")
        cards.append(f'<section data-group="{gid}"><h2>第 {number} 组 · {len(photos)} 张</h2>'
                     '<label>分组是否合理？ <select><option value="uncertain">尚不确定</option>'
                     '<option value="correct">合理，是可比较的一组</option>'
                     '<option value="incorrect">不合理，需要拆分或合并</option></select></label> '
                     '<label><input type="checkbox" class="reviewed">本组已看完（可不选最佳照片）</label>'
                     f'<div class="grid">{"".join(photos)}</div><pre class="algorithm" hidden>{ranking}</pre></section>')
    rid = json.dumps(report["report_id"]).replace("<", "\\u003c")
    return '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>WingScribe 选片探索标注</title>
<style>body{font:16px system-ui;margin:24px;background:#f5f6f8;color:#17212b}
button,select{padding:10px}section{margin:30px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
article{background:white;padding:15px;min-width:0}.preview{display:block;width:100%;margin:10px 0}
.crop{overflow:auto;max-height:520px}.crop img{max-width:none}pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style><h1>连续拍摄组：先选照片，再看算法</h1>
<p>先判断分组，再勾选你认为可接受的最佳照片，可多选、并列，也可不选。看完请勾选“本组已看完”。
没有勾选的照片不会被删除。缩略图仅用于定位，清晰度请结合主体 100% 细节和完整副本判断。</p>
<p>算法推荐默认隐藏，以减少影响。导出标注保存在本地；刷新页面前请导出，页面不自动保存。</p>
<button onclick="document.querySelectorAll('.algorithm').forEach(e=>e.hidden=!e.hidden)">显示／隐藏算法结果</button>
<button onclick="saveLabels()">导出本地标注 JSON</button>
''' + "".join(cards) + '''
<script>
function saveLabels(){
 const groups=[...document.querySelectorAll('section')].map(s=>({
 group_id:s.dataset.group, reviewed:s.querySelector('.reviewed').checked,
 grouping:s.querySelector('select').value,
 best:[...s.querySelectorAll('article input:checked')].map(e=>e.value)}));
 const blob=new Blob([JSON.stringify({report_id:''' + rid + ''',groups},null,2)],{type:'application/json'});
 const url=URL.createObjectURL(blob), a=document.createElement('a');a.href=url;a.download='focus-labels.json';a.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
</script></html>'''
