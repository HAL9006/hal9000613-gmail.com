# -*- coding: utf-8 -*-
"""§2-3 A. 適合仕様書（日本語）と UI設定チェックリスト（§6）の整形。"""

from . import data
from .util import pad, width, word_count

RULE = "─" * 62


def _zone_block(z):
    spec = data.PATTERN_CLASSES[z["pattern"]]
    dim = "寸法規定なし" if z["dim_mm"] is None else "%s %dmm（規定 %d-%dmm）" % (
        spec["unit_ja"], z["dim_mm"], spec["min_mm"], spec["max_mm"])
    lines = [
        "%s  %s  面積 %.0f%%" % (z["zone"], z["label_ja"], z["area"] * 100),
        "    柄クラス : %s %s（意味=%s）" % (z["pattern"], spec["name_ja"], z["meaning"]),
        "    語彙     : %s" % z["vocab"],
        "    寸法     : %s%s" % (dim, "　※大柄" if z["large"] else ""),
        "    配色     : %s on %s   ΔL = %.2f%s" % (
            z["fg"], z["bg"], z["delta_l"], "" if z["delta_l"] >= data.DELTA_L_MIN else "　※基準未満"),
    ]
    return "\n".join(lines)


def format_design(c):
    """適合仕様書 + MJ断片3種。"""
    out = []
    out.append(RULE)
    out.append("適合仕様書  AWC-1 / seed=%s / role=%s / vintage=%d %s" % (
        c["seed"], c["role"], c["vintage"], c["vintage_label_ja"]))
    out.append(RULE)
    out.append("シルエット : %s" % c["silhouette"])
    out.append("上着       : %s" % c["upper_cut"])
    out.append("層数       : %d 層 ／ 摩耗: %s" % (c["layers"], c["wear"]))
    out.append("高視認色   : %s（面積 %.3f・ZONE_C 前景に固定）" % (c["accent"], c["accent_area"]))
    out.append("修理布     : %s" % (
        "なし" if not c["patches"] else
        "%d枚 " % len(c["patches"]) + ", ".join(
            "%s/%s" % (p["vocab"], p["color"]) for p in c["patches"])))
    out.append("再計算回数 : %d 回（上限300）" % c["attempts"])
    out.append("")
    for z in c["zones"]:
        out.append(_zone_block(z))
        out.append("")
    out.append("%s  %s" % ("ZONE_D", data.ZONE_D_LABEL))
    out.append("    被覆禁止。衣装記述に含めない。")
    out.append("")
    out.append(RULE)
    out.append("適合判定（§2-2 6条件）")
    out.append(RULE)
    for cond in c["conformance"]["conditions"]:
        out.append("  (%d) %s %s  %s" % (
            cond["id"], pad(cond["label"], 30),
            pad("適合" if cond["ok"] else "不適合", 8), cond["detail"]))
    ok = all(x["ok"] for x in c["conformance"]["conditions"])
    out.append("")
    out.append("  総合: %s" % ("✅ 規格適合" if ok else "❌ 規格不適合（300回の再計算で適合せず）"))
    out.append("")
    out.append(RULE)
    out.append("MJ断片（§2-3）")
    out.append(RULE)
    for key, label in (("long", "B. long"), ("mid", "C. mid"), ("short", "D. short")):
        text = c["fragments"][key]
        out.append("[%s / %d words]" % (label, word_count(text)))
        out.append(text)
        out.append("")
    return "\n".join(out)


UI_CHECKLIST = """# ── 貼る前に UI でこれを設定 ──────────────────
#   [ ] Moodboards で選択           : （ユーザーが指定）
#   [ ] Personalize > Select profile
#   [ ] Settings > House style
#   [ ] 恒常ネガティブ
# ─────────────────────────────────────────────"""


def format_allocation(plan_result, variants):
    from .modules import MODULE_LABELS
    out = []
    out.append(RULE)
    out.append("配分表  subject=%s / budget=%d words（上限）" % (
        plan_result["subject"], plan_result["budget"]))
    out.append(RULE)
    out.append("  %s %s %s %s %s" % (pad("", 4), pad("モジュール", 24),
                                      pad("割当語数", 10), pad("実語数", 8), "バリアント"))
    for row in plan_result["rows"]:
        out.append("  %s %s %s %s %s%s" % (
            pad(row["module"], 4), pad(MODULE_LABELS[row["module"]], 24),
            pad("%.1f" % row["allocated"], 10), pad(str(row["words"]), 8),
            pad(row["variant"], 6), "←subject" if row["is_subject"] else ""))
    if plan_result["percept_words"]:
        out.append("  %s %s %s %s %s" % (
            pad("M4", 4), pad("PERCEPT LENS", 24), pad("予約", 10),
            pad(str(plan_result["percept_words"]), 8), "-"))
    total = plan_result["total_words"]
    budget = plan_result["budget"]
    out.append("  " + "-" * 56)
    out.append("  合計 %d words / 上限 %d words%s" % (
        total, budget, "" if total <= budget else "　※上限超過"))
    for n in plan_result["notes"]:
        out.append("  ・%s" % n)
    return "\n".join(out)
