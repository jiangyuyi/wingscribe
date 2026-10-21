"""Human-labelled, group-level evaluation. Unlabelled groups are never truth."""
import html
import json
from pathlib import Path


def evaluate_labels(report: dict, labels: dict) -> dict:
    if labels.get("report_id") != report["report_id"]:
        raise ValueError("Labels belong to a different report")
    groups = {g["group_id"]: g for g in report["groups"]}
    seen = set()
    judged = eligible = hits1 = hits3 = recommended = rejected_groups = 0
    larger_groups = larger_hits = no_best = 0
    schema = labels.get("schema_version", 1)
    if schema not in (1, 2):
        raise ValueError("Unsupported label schema")
    confidence_counts = dict(similar=0, uncertain=0, tentative=0, confident=0, none_acceptable=0)
    mode_counts = dict(safe=0, assist=0, relaxed=0)
    default_mode = labels.get("default_mode", "safe")
    if default_mode not in mode_counts or labels.get("mode_version", "focus-advice-v1") != "focus-advice-v1":
        raise ValueError("Invalid mode preferences")
    for label in labels.get("groups", []):
        key = label["group_id"]
        if key not in groups or key in seen:
            raise ValueError("Unknown or duplicate labelled group")
        seen.add(key)
        mode = label.get("mode", "safe")
        if mode not in mode_counts:
            raise ValueError("Invalid focus mode")
        if "mode_override" in label:
            override = label["mode_override"]
            if override not in (*mode_counts, "inherit") or mode != (default_mode if override == "inherit" else override):
                raise ValueError("Inconsistent mode selection")
        if mode != "safe" and mode not in groups[key].get("ranking_modes", {}):
            raise ValueError("Report does not contain this focus mode")
        if label.get("reviewed") is not True:
            continue
        valid = label.get("grouping")
        if valid not in ("correct", "incorrect", "uncertain"):
            raise ValueError("Invalid grouping judgement")
        best = label.get("best", [])
        if len(set(best)) != len(best) or not set(best) <= set(groups[key]["version_ids"]):
            raise ValueError("Best choices must be unique members of this group")
        confidence = label.get("certainty") if schema == 2 else "legacy"
        if schema == 2:
            if confidence not in confidence_counts:
                raise ValueError("Invalid selection certainty")
            if confidence == "confident" and not best:
                raise ValueError("Confident selection requires at least one photo")
            if confidence == "none_acceptable" and best:
                raise ValueError("No acceptable photos conflicts with selection")
            confidence_counts[confidence] += 1
        judged += 1
        mode_counts[mode] += 1
        if valid != "correct":
            rejected_groups += 1
            continue
        if not best:
            no_best += 1
        if schema == 2 and confidence != "confident":
            continue  # Similar/uncertain/tentative choices are not hard truth.
        if not best:
            continue
        eligible += 1
        picks = (groups[key]["ranking"] if mode == "safe" else
                 groups[key]["ranking_modes"][mode])["recommended"]
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
        "label_schema_version": schema,
        "reviewed_certainty_counts": confidence_counts,
        "reviewed_mode_counts": mode_counts,
        "scope": "exploratory single-session labels; not an independent test benchmark",
    }


def render_review(report: dict) -> str:
    """Offline review; no network, labels export locally, scores hidden initially."""
    cards = []
    has_modes = bool(report["groups"]) and all("ranking_modes" in g for g in report["groups"])
    for number, group in enumerate(report["groups"], 1):
        gid = html.escape(group["group_id"], quote=True)
        photos = []
        options = []
        for key in group["version_ids"]:
            item = report["items"][key]
            title = html.escape(item["filename"])
            preview = html.escape(item["preview"], quote=True)
            crop = html.escape(item["crop"], quote=True) if item["crop"] else ""
            if crop:
                options.append(f'<option value="{crop}">{title}</option>')
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
        compare = (
            '<div class="compare"><p>同步对比：两侧使用相同比例；滚动一侧同步相对位置。'
            '这是鸟体框内位置同步，并非眼部自动对齐，主体姿态不同可取消同步。</p>'
            '<label><input class="sync" type="checkbox" checked>同步位置</label> '
            '<label>像素比例 <select class="zoom"><option value="0.5">50%</option>'
            '<option value="1" selected>100%</option><option value="2">200%</option></select></label> '
            '<button type="button" class="blink">原位切换 A／B</button><span class="blink-label"></span>'
            '<div class="pair">' + ''.join(
                f'<div><label>{side} <select class="pick">{"".join(options)}</select></label>'
                '<div class="viewport"><img alt="主体细节"></div></div>' for side in ("A", "B")
            ) + '</div></div>' if options else '<p>本组无可用主体裁切，请查看完整测试副本。</p>'
        )
        mode_control = ('<label>本组模式 <select class="group-mode"><option value="inherit">跟随本页默认</option>'
                        '<option value="safe">稳妥推荐</option><option value="assist">辅助比较</option>'
                        '<option value="relaxed">宽松推荐（实验）</option></select></label>'
                        '<pre class="algorithm mode-result" hidden></pre>') if has_modes else ''
        cards.append(f'<section data-group="{gid}"><h2>第 {number} 组 · {len(photos)} 张</h2>' + mode_control +
                     '<label>分组是否合理？ <select class="grouping"><option value="uncertain">尚不确定</option>'
                     '<option value="correct">合理，是可比较的一组</option>'
                     '<option value="incorrect">不合理，需要拆分或合并</option></select></label> '
                     '<label>选择把握 <select class="certainty">'
                     '<option value="uncertain">不确定／看不清</option>'
                     '<option value="similar">差不多，难分高下</option>'
                     '<option value="tentative">仅初步偏好</option>'
                     '<option value="confident">有把握的最佳集合</option>'
                     '<option value="none_acceptable">全部不可接受</option></select></label> '
                     '<label><input type="checkbox" class="reviewed">本组已看完（可不选最佳照片）</label>'
                     f'{compare}<div class="grid">{"".join(photos)}</div>' +
                     ('' if has_modes else f'<pre class="algorithm" hidden>{ranking}</pre>') + '</section>')
    rid = json.dumps(report["report_id"]).replace("<", "\\u003c")
    return '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>WingScribe 选片探索标注</title>
<style>body{font:16px system-ui;margin:24px;background:#f5f6f8;color:#17212b}
button,select{padding:10px}section{margin:30px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}
article{background:white;padding:15px;min-width:0}.preview{display:block;width:100%;margin:10px 0}
.crop{overflow:auto;max-height:520px}.crop img{max-width:none}pre{white-space:pre-wrap;overflow-wrap:anywhere}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.pair>div{min-width:0}
.viewport{height:480px;overflow:auto;background:#26313b}.viewport img{display:block;max-width:none}
.compare{background:#e4eaf0;padding:16px;margin:12px 0}.blink-label{margin-left:12px}
@media(max-width:700px){.pair{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}
</style><h1>连续拍摄组：先选照片，再看算法</h1>
<p>先判断分组，再勾选你认为可接受的最佳照片，可多选、并列，也可不选。看完请勾选“本组已看完”。
没有勾选的照片不会被删除。缩略图仅用于定位，清晰度请结合主体 100% 细节和完整副本判断。</p>
<p>难以区分时请选择“差不多”或“不确定”，不用强行选最佳；粗略选择请选择“仅初步偏好”。
只有“有把握的最佳集合”参与命中率统计。</p>
<p>算法推荐默认隐藏。导出标注保存在本地；刷新页面前请导出，页面不自动保存。可导入此前导出的本页标注继续填写。</p>
<button onclick="document.querySelectorAll('.algorithm').forEach(e=>e.hidden=!e.hidden)">显示／隐藏算法结果</button>
<button onclick="saveLabels()">导出本地标注 JSON</button>
<label>恢复本页标注 <input type="file" id="import-labels" accept=".json"></label><p id="message" role="status"></p>
''' + ('''<label>本页默认模式 <select id="default-mode"><option value="safe">稳妥推荐</option>
<option value="assist">辅助比较</option><option value="relaxed">宽松推荐（实验）</option></select></label>
<p>单组可覆盖本页默认；切换不会改变人工勾选。模式随标注导出保存。宽松推荐仍需复核，不会删除照片。</p>''' if has_modes else '') + "".join(cards) + '''
<script>
const reportId = ''' + rid + ''';
''' + ('const modeData = ' + json.dumps({g['group_id']: {
    'modes': g['ranking_modes'], 'names': {k: report['items'][k]['filename'] for k in g['version_ids']}}
    for g in report['groups']}, ensure_ascii=False).replace('<', '\\u003c') + ';\n' +
    Path(__file__).with_name('focus_modes_review.js').read_text(encoding='utf-8') if has_modes else '') + '''
function saveLabels(){
 const groups=[...document.querySelectorAll('section')].map(s=>({
 group_id:s.dataset.group, reviewed:s.querySelector('.reviewed').checked,
 grouping:s.querySelector('.grouping').value,certainty:s.querySelector('.certainty').value,
 best:[...s.querySelectorAll('article input:checked')].map(e=>e.value),
 ...(typeof modeSelection==='function'?modeSelection(s):{})}));
 for(const g of groups){
  if(g.reviewed && ((g.certainty==='confident' && !g.best.length) ||
     (g.certainty==='none_acceptable' && g.best.length))){
   document.querySelector('#message').textContent='请检查选择把握：有把握的最佳集合需勾选照片，全部不可接受不能同时勾选最佳照片。';return;
  }
 }
 const blob=new Blob([JSON.stringify({schema_version:2,report_id:reportId,groups,
 ...(typeof modePreferences==='function'?modePreferences():{})},null,2)],{type:'application/json'});
 const url=URL.createObjectURL(blob), a=document.createElement('a');a.href=url;a.download='focus-labels.json';a.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
 document.querySelector('#message').textContent='已发起下载；请确认浏览器保存的文件。';
}
''' + Path(__file__).with_name("focus_review.js").read_text(encoding="utf-8") + '</script></html>'
