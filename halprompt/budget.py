# -*- coding: utf-8 -*-
"""§4 語数予算配分【本タスクの中核】

この処理に判断は一切含まれない。全て決定論。
"""

from . import data
from .modules import MODULE_IDS, VARIANTS
from .util import word_count

SUBJECT_MODULE = {"fashion": "M0", "performance": "M1", "scene": "M2"}
DEGRADE_ORDER = ["M3", "M2", "M1", "M0"]   # 仕様の M3→M2→M1。M0 は最後の保険。
_STEP_DOWN = {"long": "mid", "mid": "short", "short": None}
_STEP_UP = {"short": "mid", "mid": "long", "long": None}


def allocate(subject, budget):
    """配分: subject モジュールに budget×0.45、残り3モジュールに残余を均等。"""
    if subject == "none":
        share = budget / 4.0
        return {m: share for m in MODULE_IDS}
    target = SUBJECT_MODULE[subject]
    alloc = {target: budget * 0.45}
    rest = (budget - alloc[target]) / 3.0
    for m in MODULE_IDS:
        if m != target:
            alloc[m] = rest
    return alloc


def _select(variants, alloc):
    """割当語数を超えない最長のバリアント。全て超える場合は short。"""
    chosen = {}
    for m in MODULE_IDS:
        pick = "short"
        for v in VARIANTS:                      # long > mid > short の順に試す
            if word_count(variants[m][v]) <= alloc[m]:
                pick = v
                break
        chosen[m] = pick
    return chosen


def _total(variants, chosen):
    return sum(word_count(variants[m][chosen[m]]) for m in MODULE_IDS)


def plan(variants, subject, budget, percept_words=0, fill=True):
    """配分・選択・超過処理・（拡張）余剰の再配分までを行う。

    percept_words は M4 の語数。総語数を予算内に収めるため先に差し引く。
    """
    module_budget = max(1, budget - percept_words)
    # 表現可能な語数の下限・上限。予算がこの外側にあると ±10% は原理的に満たせない。
    floor_words = sum(word_count(variants[m]["short"]) for m in MODULE_IDS) + percept_words
    ceiling_words = sum(word_count(variants[m]["long"]) for m in MODULE_IDS) + percept_words
    alloc = allocate(subject, module_budget)
    chosen = _select(variants, alloc)
    target = SUBJECT_MODULE.get(subject)
    notes = []

    # 超過処理: subject 以外を M3 → M2 → M1 (→ M0) の順に1段ずつ落とす
    while _total(variants, chosen) > module_budget:
        dropped = False
        for m in DEGRADE_ORDER:
            if m == target:
                continue
            nxt = _STEP_DOWN[chosen[m]]
            if nxt is not None:
                notes.append("超過処理: %s %s→%s" % (m, chosen[m], nxt))
                chosen[m] = nxt
                dropped = True
                break
        if not dropped:
            notes.append("超過処理: これ以上落とせるモジュールが無い")
            break

    # 拡張: 余剰語数の再配分（予算 ±10% を満たすため。--no-fill で無効化）
    # 第1段: 予算内に収まる範囲で1段ずつ上げる。
    # 第2段: それでも下限90%に届かない場合のみ、上限110%を超えない範囲で1段上げる。
    if fill:
        order = ([target] if target else []) + [m for m in MODULE_IDS if m != target]

        def _upgrade_pass(cap, tag):
            for m in order:
                nxt = _STEP_UP[chosen[m]]
                if nxt is None:
                    continue
                trial = dict(chosen)
                trial[m] = nxt
                if _total(variants, trial) <= cap:
                    notes.append("%s: %s %s→%s" % (tag, m, chosen[m], nxt))
                    chosen[m] = nxt
                    return True
            return False

        while _upgrade_pass(module_budget, "余剰再配分"):
            pass
        upper = budget * 1.10 - percept_words
        while (_total(variants, chosen) + percept_words) < budget * 0.90:
            if not _upgrade_pass(upper, "下限充足"):
                break

    # 配置順: subject を先頭に置く（原則1）。以降は M0 → M1 → M2 → M3。
    order = ([target] if target else []) + [m for m in MODULE_IDS if m != target]

    # 予算 ±10% に収まらない場合、その理由を必ず添える（黙って外さない）。
    final_total = _total(variants, chosen) + percept_words
    if final_total > budget * 1.10:
        notes.append("警告: 予算 %d に対し %d words。subject モジュールを残したままの"
                     "最短構成が %d words のため、これ以上は縮められません（表現可能下限 %d words）"
                     % (budget, final_total, final_total, floor_words))
    elif final_total < budget * 0.90:
        notes.append("警告: 予算 %d に対し %d words。語彙の最長構成が %d words のため、"
                     "これ以上は伸ばせません（M4 予約 %d words を含む）"
                     % (budget, final_total, ceiling_words, percept_words))

    rows = []
    for m in order:
        rows.append({
            "module": m,
            "allocated": round(alloc[m], 1),
            "words": word_count(variants[m][chosen[m]]),
            "variant": chosen[m],
            "is_subject": m == target,
        })
    return {
        "subject": subject,
        "budget": budget,
        "module_budget": module_budget,
        "percept_words": percept_words,
        "order": order,
        "chosen": chosen,
        "rows": rows,
        "floor_words": floor_words,
        "ceiling_words": ceiling_words,
        "module_words": _total(variants, chosen),
        "total_words": _total(variants, chosen) + percept_words,
        "notes": notes,
    }


def stylize_for(subject):
    return data.STYLIZE_DEFAULT[subject]
