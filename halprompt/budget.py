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


def plan(variants, subject, budget, percept_words=0, fill=False):
    """配分・選択・超過処理・（任意）余剰の再配分までを行う。

    budget は目標ではなく**上限**である。下回るのは正常な出力であり、警告しない。
    percept_words は M4 の語数。総語数を上限内に収めるため先に差し引く。
    """
    module_budget = max(1, budget - percept_words)
    # 表現可能な語数の下限・上限。予算がこの外側にあると ±10% は原理的に満たせない。
    floor_words = sum(word_count(variants[m]["short"]) for m in MODULE_IDS) + percept_words
    ceiling_words = sum(word_count(variants[m]["long"]) for m in MODULE_IDS) + percept_words
    alloc = allocate(subject, module_budget)
    chosen = _select(variants, alloc)
    target = SUBJECT_MODULE.get(subject)
    notes = []

    # 超過処理: subject 以外を M3 → M2 → M1 (→ M0) の順に1段ずつ落とす。
    # subject のモジュールは「最後まで」落とさない ＝ 他が尽きた時だけ落とす。
    # budget は上限なので、最後の1段まで使い切って上限内に入れる。
    while _total(variants, chosen) > module_budget:
        order_down = [m for m in DEGRADE_ORDER if m != target] + ([target] if target else [])
        dropped = False
        for m in order_down:
            nxt = _STEP_DOWN[chosen[m]]
            if nxt is not None:
                notes.append("超過処理: %s %s→%s%s"
                             % (m, chosen[m], nxt, "（subject・最終手段）" if m == target else ""))
                chosen[m] = nxt
                dropped = True
                break
        if not dropped:
            notes.append("超過処理: 全モジュールが short。これ以上は落とせない")
            break

    # 任意: 余剰語数の再配分（既定は無効。--fill で明示的に有効化する）
    # 予算は上限なので、上限を超えない範囲でのみ1段ずつ上げる。
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

    # 配置順: subject を先頭に置く（原則1）。以降は M0 → M1 → M2 → M3。
    order = ([target] if target else []) + [m for m in MODULE_IDS if m != target]

    # 上限を超えた場合だけ警告する。下回るのは正常な出力であり、警告に値しない。
    final_total = _total(variants, chosen) + percept_words
    if final_total > budget:
        notes.append("警告: 上限 %d words に対し %d words。subject モジュールを残したままの"
                     "最短構成がこの長さのため、これ以上は縮められません（語彙の下限 %d words）"
                     % (budget, final_total, floor_words))

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
