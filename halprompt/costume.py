# -*- coding: utf-8 -*-
"""§2 衣装生成器

規格（§2-2 の6条件）に適合するまで再計算する方式。
美的判定は行わない。判定するのは「規格に適合しているか」だけである。
"""

import random

from . import data
from .util import cap, squeeze, word_count


class Zone(object):
    """1ゾーンの確定仕様。"""

    def __init__(self, key, pattern, vocab, dim_mm, fg, bg, fg_l, bg_l):
        self.key = key
        self.label_ja = data.ZONES[key]["label_ja"]
        self.area = data.ZONES[key]["area"]
        self.pattern = pattern
        self.vocab = vocab
        self.dim_mm = dim_mm
        self.fg = fg
        self.bg = bg
        self.fg_l = fg_l
        self.bg_l = bg_l

    @property
    def delta_l(self):
        return round(abs(self.fg_l - self.bg_l), 4)

    @property
    def is_large(self):
        large = data.PATTERN_CLASSES[self.pattern]["large_mm"]
        if large is None or self.dim_mm is None:
            return False
        return self.dim_mm >= large

    def dim_phrase(self):
        """英語断片で使う寸法句。無地は寸法を持たない。"""
        unit = data.PATTERN_CLASSES[self.pattern]["unit_en"]
        if unit is None or self.dim_mm is None:
            return ""
        return "%d millimetre %s" % (self.dim_mm, unit)

    def to_dict(self):
        return {
            "zone": self.key,
            "label_ja": self.label_ja,
            "area": self.area,
            "pattern": self.pattern,
            "pattern_name_ja": data.PATTERN_CLASSES[self.pattern]["name_ja"],
            "meaning": data.PATTERN_CLASSES[self.pattern]["meaning"],
            "vocab": self.vocab,
            "dim_mm": self.dim_mm,
            "fg": self.fg,
            "bg": self.bg,
            "delta_l": self.delta_l,
            "large": self.is_large,
        }


class Patch(object):
    def __init__(self, vocab, color, color_l):
        self.vocab = vocab
        self.color = color
        self.color_l = color_l

    def to_dict(self):
        return {"vocab": self.vocab, "color": self.color}


class Costume(object):
    def __init__(self, role, vintage, seed, zones, patches, accent, accent_area,
                 silhouette, upper_cut, attempts):
        self.role = role
        self.vintage = vintage
        self.seed = seed
        self.zones = zones                    # dict key -> Zone
        self.patches = patches                # list[Patch]
        self.accent = accent
        self.accent_area = accent_area
        self.silhouette = silhouette
        self.upper_cut = upper_cut
        self.attempts = attempts
        self.conformance = evaluate(self)

    # ── 参照補助 ──────────────────────────────────────────
    def zone(self, key):
        return self.zones[key]

    @property
    def vintage_spec(self):
        return data.VINTAGES[self.vintage]

    @property
    def classes_used(self):
        used = [z.pattern for z in self.zones.values()]
        if self.patches:
            used.append("P4")
        return sorted(set(used))

    @property
    def conforms(self):
        return all(c["ok"] for c in self.conformance["conditions"])

    # ── §2-3 出力 ────────────────────────────────────────
    def fragment(self, variant):
        return FRAGMENTS[variant](self)

    def fragments(self):
        return {v: self.fragment(v) for v in ("long", "mid", "short")}

    def to_dict(self):
        return {
            "seed": self.seed,
            "role": self.role,
            "vintage": self.vintage,
            "vintage_label_ja": self.vintage_spec["label_ja"],
            "layers": self.vintage_spec["layers"],
            "wear": self.vintage_spec["wear"],
            "silhouette": self.silhouette,
            "upper_cut": self.upper_cut,
            "accent": self.accent,
            "accent_area": self.accent_area,
            "attempts": self.attempts,
            "zones": [self.zones[k].to_dict() for k in data.ZONE_ORDER],
            "patches": [p.to_dict() for p in self.patches],
            "conformance": self.conformance,
            "fragments": self.fragments(),
        }


# ── §2-2 適合判定 ────────────────────────────────────────────

def id_score(costume):
    """ID_score = Σ(ゾーン面積 × ΔL × クラス一意性) × 2.2"""
    counts = {}
    for z in costume.zones.values():
        counts[z.pattern] = counts.get(z.pattern, 0) + 1
    total = 0.0
    for key in data.ZONE_ORDER:
        z = costume.zones[key]
        uniqueness = 1.0 if counts[z.pattern] == 1 else 0.6
        total += z.area * z.delta_l * uniqueness
    return round(total * 2.2, 4)


def human_distance(costume):
    """D = 0.25×(大柄使用) + 0.25×(3クラス以上) + 0.25 + 0.25"""
    large = any(z.is_large for z in costume.zones.values())
    three = len(set(z.pattern for z in costume.zones.values())) >= 3
    d = 0.25 * (1 if large else 0) + 0.25 * (1 if three else 0) + 0.25 + 0.25
    return round(d, 4)


def zone_d_covered(costume):
    """ZONE_D 遮蔽率。衣装記述に頭部・顔・手袋の語が無ければ 0。"""
    body = " ".join(costume.fragment(v) for v in ("long", "mid", "short")).lower()
    hits = [t for t in data.ZONE_D_FORBIDDEN_TERMS if t in body]
    return (0.0 if not hits else 1.0), hits


def evaluate(costume):
    score = id_score(costume)
    classes = set(z.pattern for z in costume.zones.values())
    covered, hits = zone_d_covered(costume)
    distance = human_distance(costume)

    dim_ok = True
    dim_detail = []
    for key in data.ZONE_ORDER:
        z = costume.zones[key]
        spec = data.PATTERN_CLASSES[z.pattern]
        if spec["min_mm"] is None:
            dim_detail.append("%s %s 寸法規定なし" % (key, z.pattern))
            continue
        ok = z.dim_mm is not None and z.dim_mm >= spec["min_mm"]
        dim_ok = dim_ok and ok
        dim_detail.append("%s %s %dmm >= %dmm %s"
                          % (key, z.pattern, z.dim_mm, spec["min_mm"], "OK" if ok else "NG"))

    conditions = [
        {"id": 1, "label": "ID_score >= 0.60",
         "ok": score >= 0.60, "detail": "ID_score = %.4f" % score},
        {"id": 2, "label": "使用クラス数 >= 3",
         "ok": len(classes) >= 3, "detail": "使用クラス = %s" % ", ".join(sorted(classes))},
        {"id": 3, "label": "ZONE_D 遮蔽率 = 0",
         "ok": covered == 0.0,
         "detail": "遮蔽率 = %.1f%s" % (covered, ("／検出語: " + ", ".join(hits)) if hits else "")},
        {"id": 4, "label": "高視認色1色・面積 <= 0.10",
         "ok": costume.accent_area <= 0.10,
         "detail": "%s 面積 = %.3f" % (costume.accent, costume.accent_area)},
        {"id": 5, "label": "人間衣料との距離 D >= 0.60",
         "ok": distance >= 0.60, "detail": "D = %.2f" % distance},
        {"id": 6, "label": "各柄が最小寸法を満たす",
         "ok": dim_ok, "detail": " / ".join(dim_detail)},
    ]
    return {"id_score": score, "distance": distance, "conditions": conditions}


# ── §2-1 生成手順 ────────────────────────────────────────────

MAX_ATTEMPTS = 300


def _pick_pair(rnd, fg_fixed=None):
    """ΔL >= 0.35 を満たす (前景, 背景) 組だけを候補にして1組選ぶ。"""
    names = sorted(data.BASE_COLORS)
    if fg_fixed is None:
        pairs = [(a, b) for a in names for b in names
                 if abs(data.BASE_COLORS[a] - data.BASE_COLORS[b]) >= data.DELTA_L_MIN]
        fg, bg = rnd.choice(pairs)
        return fg, bg, data.BASE_COLORS[fg], data.BASE_COLORS[bg]
    fg_l = data.HIGH_VIS_COLORS[fg_fixed]
    cands = [b for b in names if abs(fg_l - data.BASE_COLORS[b]) >= data.DELTA_L_MIN]
    bg = rnd.choice(cands)
    return fg_fixed, bg, fg_l, data.BASE_COLORS[bg]


def _dim(rnd, pattern):
    spec = data.PATTERN_CLASSES[pattern]
    if spec["min_mm"] is None:
        return None
    return rnd.randrange(spec["min_mm"], spec["max_mm"] + 1, 5)


def _attempt(rnd, role, vintage, seed, attempt_no):
    # 1. 高視認色を1色選ぶ
    accent = rnd.choice(sorted(data.HIGH_VIS_COLORS))
    # 2. P1/P2/P3 から3クラスをサンプリング（重複なし）
    pool = rnd.sample(["P1", "P2", "P3"], 3)
    # 3. ZONE_A は P1 または P3
    a_class = rnd.choice([c for c in pool if c in ("P1", "P3")])
    rest = [c for c in pool if c != a_class]
    # 4. ZONE_B は A と異クラス、ZONE_B_UNDER は残り
    rnd.shuffle(rest)
    b_class, bu_class = rest[0], rest[1]
    # 5. ZONE_C は A と異クラス
    c_class = rnd.choice([c for c in ("P1", "P2", "P3", "P4") if c != a_class])

    zones = {}
    for key, cls in (("ZONE_A", a_class), ("ZONE_B", b_class), ("ZONE_B_UNDER", bu_class)):
        fg, bg, fl, bl = _pick_pair(rnd)
        zones[key] = Zone(key, cls, rnd.choice(data.PATTERN_CLASSES[cls]["vocab"]),
                          _dim(rnd, cls), fg, bg, fl, bl)
    fg, bg, fl, bl = _pick_pair(rnd, fg_fixed=accent)
    zones["ZONE_C"] = Zone("ZONE_C", c_class, rnd.choice(data.PATTERN_CLASSES[c_class]["vocab"]),
                           _dim(rnd, c_class), fg, bg, fl, bl)

    # 高視認色の面積 = ZONE_C 面積 × その柄の前景比
    accent_area = round(data.ZONES["ZONE_C"]["area"] * data.PATTERN_CLASSES[c_class]["fg_ratio"], 4)

    # 7. 年式に応じて P4 修理布を patches 個生成する
    n = data.VINTAGES[vintage]["patches"]
    patches = []
    for _ in range(n):
        v = rnd.choice(data.PATTERN_CLASSES["P4"]["vocab"])
        c = rnd.choice(sorted(data.BASE_COLORS))
        patches.append(Patch(v, c, data.BASE_COLORS[c]))

    return Costume(role, vintage, seed, zones, patches, accent, accent_area,
                   rnd.choice(data.SILHOUETTES), rnd.choice(data.UPPER_CUTS), attempt_no)


def generate(role="bass", vintage=2, seed=0):
    """規格適合するまで再計算する。最大300回。300回超なら最後の案を返す。"""
    if role not in data.ROLES:
        raise ValueError("未知の role: %s" % role)
    if vintage not in data.VINTAGES:
        raise ValueError("未知の vintage: %s" % vintage)
    rnd = random.Random("halprompt/%s/%s/%s" % (seed, role, vintage))
    last = None
    for i in range(1, MAX_ATTEMPTS + 1):
        last = _attempt(rnd, role, vintage, seed, i)
        if last.conforms:
            return last
    return last


# ── §2-3 MJ断片 ──────────────────────────────────────────────

def _join(items):
    """英語の列挙。1個ならそのまま、2個以上は最後だけ and で繋ぐ。"""
    if len(items) == 1:
        return items[0]
    return "%s and %s" % (", ".join(items[:-1]), items[-1])


def _patch_sentence(c):
    n = len(c.patches)
    if n == 0:
        return "No repairs yet, the cloth still first generation."
    word = data.PATCH_WORDS.get(n, str(n))
    kinds = sorted(set(p.vocab for p in c.patches))
    colors = sorted(set(p.color for p in c.patches))
    return "%s repair patches of %s in %s are stitched flat over the worn ridges." % (
        word, _join(kinds), _join(colors))


def fragment_long(c):
    a, b, bu, cc = (c.zone("ZONE_A"), c.zone("ZONE_B"),
                    c.zone("ZONE_B_UNDER"), c.zone("ZONE_C"))
    text = """
    A {sil} silhouette, {upper}. The chest front is {a_vocab}, {a_dim}, {a_fg}
    on {a_bg}. The lower body carries {b_vocab}, {b_dim}, {b_fg} on {b_bg}, worn
    open over an under layer of {bu_vocab}, {bu_fg} on {bu_bg}. Collar and cuffs
    are {c_vocab}, {accent} on {c_bg}, the only saturated colour in the garment.
    {patches} The garment shows {wear}. Built in {layers} layers, unlined, cut
    edges left exposed. Face, neck and wrists stay bare.
    """.format(
        sil=c.silhouette, upper=c.upper_cut,
        a_vocab=a.vocab, a_dim=a.dim_phrase(), a_fg=a.fg, a_bg=a.bg,
        b_vocab=b.vocab, b_dim=b.dim_phrase(), b_fg=b.fg, b_bg=b.bg,
        bu_vocab=bu.vocab, bu_fg=bu.fg, bu_bg=bu.bg,
        c_vocab=cc.vocab, accent=c.accent, c_bg=cc.bg,
        patches=_patch_sentence(c), wear=c.vintage_spec["wear"],
        layers=data.LAYER_WORDS[c.vintage_spec["layers"]])
    return squeeze(text)


def fragment_mid(c):
    a, b, cc = c.zone("ZONE_A"), c.zone("ZONE_B"), c.zone("ZONE_C")
    text = """
    A {sil} silhouette, {upper}. The chest front is {a_vocab}, {a_dim}, {a_fg} on
    {a_bg}. The lower body is {b_vocab}, {b_dim}, {b_fg} on {b_bg}. Collar and
    cuffs are {c_vocab}, {accent} on {c_bg}, the only saturated colour.
    {wear}, cut edges left exposed. Face, neck and wrists bare.
    """.format(
        sil=c.silhouette, upper=c.upper_cut,
        a_vocab=a.vocab, a_dim=a.dim_phrase(), a_fg=a.fg, a_bg=a.bg,
        b_vocab=b.vocab, b_dim=b.dim_phrase(), b_fg=b.fg, b_bg=b.bg,
        c_vocab=cc.vocab, accent=c.accent, c_bg=cc.bg,
        wear=cap(c.vintage_spec["wear"]))
    return squeeze(text)


def fragment_short(c):
    a, b, bu = c.zone("ZONE_A"), c.zone("ZONE_B"), c.zone("ZONE_B_UNDER")
    text = ("{a}, {b} and {bu} on one body, three pattern classes and none repeating, "
            "{sil} silhouette, {wear}, cut edges left exposed.").format(
        a=cap(a.vocab), b=b.vocab, bu=bu.vocab,
        sil=c.silhouette, wear=c.vintage_spec["wear"])
    return squeeze(text)


FRAGMENTS = {"long": fragment_long, "mid": fragment_mid, "short": fragment_short}
