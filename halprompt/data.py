# -*- coding: utf-8 -*-
"""§1 データ定義

本ファイルは halprompt の唯一のデータ源である。
外部ファイル・ネットワーク・LLM API を一切参照しない（LOCAL SOVEREIGNTY）。
"""

# ── §1-1 柄クラス（PATTERN CLASS） ────────────────────────────
# unit_en は英語断片で使う寸法の言い方。
# 語彙に色名を含めてはならない。配色は §1-2 の明度差から独立に決まるため、
# 語彙側に色が埋まっていると "dot grid, deep crimson on ecru" のような矛盾が出る。
PATTERN_CLASSES = {
    "P1": {
        "name_ja": "円形",
        "meaning": "個体識別コード",
        "min_mm": 80,
        "max_mm": 150,
        "unit_ja": "直径",
        "unit_en": "dots",
        "large_mm": 100,          # これ以上を「大柄」とみなす
        "fg_ratio": 0.35,         # 前景（柄そのもの）が占める面積比
        "vocab": [
            "large scale polka dot",
            "oversized dot field",
            "dot grid",
        ],
    },
    "P2": {
        "name_ja": "直線",
        "meaning": "用途等級",
        "min_mm": 30,
        "max_mm": 80,
        "unit_ja": "幅",
        "unit_en": "stripe width",
        "large_mm": 60,
        "fg_ratio": 0.50,
        "vocab": [
            "wide stripe",
            "broad rib stripe",
            "narrow pinstripe",
        ],
    },
    "P3": {
        "name_ja": "格子",
        "meaning": "製造世代",
        "min_mm": 50,
        "max_mm": 100,
        "unit_ja": "升目",
        "unit_en": "check squares",
        "large_mm": 80,
        "fg_ratio": 0.45,
        "vocab": [
            "tartan",
            "houndstooth",
            "glen check",
            "oversized windowpane check",
        ],
    },
    "P4": {
        "name_ja": "無地",
        "meaning": "後補修理布",
        "min_mm": None,
        "max_mm": None,
        "unit_ja": None,
        "unit_en": None,
        "large_mm": None,
        "fg_ratio": 1.00,         # 無地は面全体が前景
        "vocab": [
            "plain wool",
            "coarse tweed",
            "raw canvas",
            "crushed velvet",
        ],
    },
}

# ── §1-2 色と明度（L値 0-1） ─────────────────────────────────
BASE_COLORS = {
    "black": 0.05,
    "charcoal": 0.20,
    "rust gold": 0.38,
    "brass": 0.45,
    "ecru": 0.78,
    "ivory": 0.85,
}

HIGH_VIS_COLORS = {
    "deep crimson": 0.25,
    "burnt orange": 0.45,
    "amber": 0.60,
}

# 禁止色（生成に用いない。仕様書に明示するためだけに保持する）
FORBIDDEN_COLOR_TERMS = [
    "blue", "navy", "indigo", "denim",          # 青系（デニムと混同）
    "green", "olive", "emerald",                # 緑系（自然物と混同）
    "pastel", "baby pink", "mint",              # パステル
    "pure white",                               # 純白
]

DELTA_L_MIN = 0.35   # §2-1 手順6

# ── §1-3 ゾーン ──────────────────────────────────────────────
ZONES = {
    "ZONE_A": {"label_ja": "主識別面（胴前面）", "area": 0.34},
    "ZONE_B": {"label_ja": "副識別面（下半身表層）", "area": 0.30},
    "ZONE_B_UNDER": {"label_ja": "下層", "area": 0.14},
    "ZONE_C": {"label_ja": "境界表示（衿・カフス）", "area": 0.12},
}
ZONE_ORDER = ["ZONE_A", "ZONE_B", "ZONE_B_UNDER", "ZONE_C"]

# ZONE_D 非遮蔽域。被覆禁止＝衣装記述に含めてはならない語。
ZONE_D_LABEL = "非遮蔽域（顔面・頸部・手首）"
ZONE_D_FORBIDDEN_TERMS = [
    "mask", "masked", "balaclava", "veil", "veiled", "hood", "hooded",
    "glove", "gloves", "gloved", "mitten", "scarf", "muffler",
    "helmet", "visor", "face covering", "neck brace", "choker",
]

# ── §1-4 シルエットと上着 ────────────────────────────────────
SILHOUETTES = ["balloon", "trapeze", "bell", "bubble hem"]

UPPER_CUTS = [
    "structured double breasted coat, oversized matte dome buttons",
    "asymmetric high collar jacket, exposed seam allowances",
    "boxy 1960s shift bodice, architectural shoulders",
    "elongated frock coat, raw cut lapels",
    "nipped waist peplum jacket, oversized matte dome buttons",
]

# ── §1-5 年式 ────────────────────────────────────────────────
VINTAGES = {
    1: {"label_ja": "新造個体", "layers": 2, "patches": 0, "wear": "raw cut hems only"},
    2: {"label_ja": "中古個体", "layers": 3, "patches": 3, "wear": "worn ridges, frayed hems"},
    3: {"label_ja": "放棄個体", "layers": 4, "patches": 6, "wear": "shredded hems, heavy abrasion"},
}

LAYER_WORDS = {2: "two", 3: "three", 4: "four"}
PATCH_WORDS = {3: "Three", 6: "Six"}

# ── §1-6 用途等級（role） ────────────────────────────────────
# instrument は原則2（楽器語は2語以内）を満たすこと。
ROLES = {
    "piano":  {"kind_ja": "演奏用（鍵盤）", "instrument": "upright piano",
               "player": "pianist",   "excludes": ["electric guitar", "drum kit", "amplifier"]},
    "bass":   {"kind_ja": "演奏用（弦）",   "instrument": "double bass",
               "player": "bassist",   "excludes": ["grand piano", "acoustic guitar"]},
    "guitar": {"kind_ja": "演奏用（弦）",   "instrument": "electric guitar",
               "player": "guitarist", "excludes": ["grand piano", "upright piano"]},
    "violin": {"kind_ja": "演奏用（弦）",   "instrument": "violin",
               "player": "violinist", "excludes": ["electric guitar", "drum kit"]},
    "synth":  {"kind_ja": "演奏用（電子）", "instrument": "synthesizer",
               "player": "synthesist", "excludes": ["grand piano", "acoustic guitar"]},
    "organ":  {"kind_ja": "演奏用（鍵盤）", "instrument": "Hammond organ",
               "player": "organist",  "excludes": ["electric guitar", "drum kit"]},
}

# M1 の二人目の奏者。role と重複する場合のみ差し替える（README に明記）。
SECOND_PLAYER_DEFAULT = "pianist"
SECOND_PLAYER_FALLBACK = "bassist"

# ── §3 M2 の場面候補 ─────────────────────────────────────────
SCENES = {
    "studio": "dimly lit underground rehearsal studio",
    "street": "on a London street corner",
    "ruin": "a derelict studio, plaster falling",
    "hall": "an empty concert hall",
}

# ── §3 M3 のレンズ候補（原則3: 6語以内） ─────────────────────
LENSES = {
    "wide": "Ultra wide angle, two meters back",
    "floor": "Low floor-level angle",
    "overhead": "Steep overhead view",
    "behind": "Seen from behind the instrument",
    "edge": "Off-centre framing, subject at the edge",
    "tilt": "Tilted frame",
    "none": "",
}
LENS_MAX_WORDS = 6

# ── §3 M4 PERCEPT LENS ───────────────────────────────────────
PERCEPT_LENSES = {
    "L1": {"axis_ja": "焦点", "text": "Everything sharp at once, foreground and far wall equally resolved."},
    "L2": {"axis_ja": "視野", "text": "The periphery sharp and the centre soft, the reverse of an eye."},
    "L3": {"axis_ja": "露光", "text": "One half frozen sharp, the other smeared, the same instant."},
    "L4": {"axis_ja": "視点", "text": "The viewpoint belongs to no one standing there."},
    "L5": {"axis_ja": "注意", "text": "Only the {accent} element correctly exposed, the illumination coming from her attention rather than the window."},
    "L6": {"axis_ja": "欠落", "text": "The background not blurred but absent, flat unrendered ground where the room should be."},
    "L7": {"axis_ja": "知識", "text": "The hidden side of the instrument drawn as if seen through it."},
    "L8": {"axis_ja": "時間", "text": "The same figure present twice in one frame, both solid, not motion blur."},
    "L9": {"axis_ja": "縁",   "text": "The image thinning out where attention ended, the border undefined."},
}
PERCEPT_MAX = 2

# 原則8: L6 採用時に排他する語
BLUR_TERMS = ["blur", "blurred", "bokeh", "soft focus"]
# L8 の本文は "not motion blur" を含むため、排他判定から除外する既知の例外。
BLUR_EXEMPT_PHRASES = ["not motion blur", "not blurred but absent"]

# ── 原則6: stylize 既定値 ────────────────────────────────────
# fashion / performance / none はパケット指定。scene は中間値として補間（README に明記）。
STYLIZE_DEFAULT = {"fashion": 300, "performance": 400, "scene": 500, "none": 600}

SUBJECTS = ["fashion", "performance", "scene", "none"]

DEFAULT_BUDGET = 150
