# -*- coding: utf-8 -*-
"""§5 残留検査（lint）

排他グループから2種類以上が検出されたら警告する。
ここで判定するのは「矛盾が残っていないか」だけである。良し悪しは判定しない。
"""

import re

from . import data

# ── 排他グループ ────────────────────────────────────────────
# 楽器のみスコープ判定を行う（主奏／伴奏）。
INSTRUMENT_GROUP = {
    "piano": ["grand piano", "upright piano", "piano", "keyboard", "the keys"],
    "guitar": ["electric guitar", "acoustic guitar", "guitar"],
    "bass": ["double bass", "upright bass", "bass"],
    "cello": ["cello"],
    "violin": ["violin"],
    "drums": ["drum kit", "brushed drums", "drums"],
    "synth": ["synthesizer", "synth"],
}

PLAIN_GROUPS = {
    "姿勢": {
        "seated": ["seated", "sitting"],
        "standing": ["standing at", "standing behind", "stands", "towering"],
    },
    "場所": {
        "studio": ["studio"],
        "street": ["street", "pavement", "shopfront"],
        "hall": ["hall"],
        "ruin": ["ruin", "ruins"],
    },
    "レンズ": {
        "wide": ["wide angle", "ultra wide"],
        "tele": ["telephoto"],
        "prime": ["prime lens"],
    },
    "髪色": {
        "blonde": ["blonde"],
        "platinum": ["platinum", "white hair"],
        "black": ["black hair"],
        "crimson": ["crimson hair"],
    },
    "色調": {
        "black-and-white": ["black-and-white", "monochrome image", "monochrome"],
        "full color": ["full color", "full colour"],
    },
    "画角": {
        "full": ["full body", "entire room", "pulled back"],
        "close": ["close-up", "bust"],
    },
}

# ── REDUNDANCY（冗長検査） ──────────────────────────────────
# 「重複が存在するか否か」だけを見る。文章の良し悪し・自然さは判定しない。
SYNONYM_PAIRS = [
    ("clear of her body", "leaned away"),
    ("seen from her open", "seen from the side"),
    ("played in a relaxed", "in a seasoned style"),
    ("strong backlighting", "backlit"),
    ("monochrome", "black and white"),
]

# 3-gram がこれだけで構成される場合は数えない。
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by", "with",
    "for", "from", "as", "is", "are", "was", "were", "be", "been", "it", "its",
    "her", "his", "she", "he", "they", "them", "their", "this", "that", "these",
    "those", "so", "then", "than", "not", "no", "one", "two", "up", "out",
}

N_GRAM = 3

PRIMARY_MARKERS = ["holding", "seated at", "hands on", "playing", "bow in the"]
ACCOMP_MARKERS = ["behind her", "flanking", "quartet", "trio", "band", "in the background"]


def _alt(words):
    """長い語句を先に当てる交替パターン。"""
    ordered = sorted(set(words), key=len, reverse=True)
    return r"\b(?:%s)\b" % "|".join(re.escape(w) for w in ordered)


def strip_params(text):
    """パラメータ部（`--` 以降）とコメント行を検査対象外にする。"""
    lines = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    body = "\n".join(lines)
    m = re.search(r"(?:^|\s)--", body)
    if m:
        body = body[:m.start()]
    return body


def _scan_plain(body):
    findings = []
    low = body.lower()
    for group, variants in PLAIN_GROUPS.items():
        hits = {}
        for variant, words in variants.items():
            found = [m.group(0) for m in re.finditer(_alt(words), low)]
            if found:
                hits[variant] = sorted(set(found))
        if len(hits) >= 2:
            findings.append({"group": group, "variants": sorted(hits), "matches": hits})
    return findings


def _scan_instruments(body):
    """伴奏マーカー以降は、次に主奏マーカーが現れるまで判定対象外。"""
    low = body.lower()
    word_to_group = {}
    for group, words in INSTRUMENT_GROUP.items():
        for w in words:
            word_to_group[w] = group
    inst_re = _alt(list(word_to_group))
    primary_re = _alt(PRIMARY_MARKERS)
    accomp_re = _alt(ACCOMP_MARKERS)

    events = []
    for m in re.finditer(inst_re, low):
        events.append((m.start(), "inst", m.group(0)))
    for m in re.finditer(primary_re, low):
        events.append((m.start(), "primary", m.group(0)))
    for m in re.finditer(accomp_re, low):
        events.append((m.start(), "accomp", m.group(0)))
    events.sort()

    in_scope = True
    hits = {}
    ignored = []
    for _pos, kind, text in events:
        if kind == "primary":
            in_scope = True
        elif kind == "accomp":
            in_scope = False
        else:
            group = word_to_group[text]
            if in_scope:
                hits.setdefault(group, set()).add(text)
            else:
                ignored.append(text)

    findings = []
    if len(hits) >= 2:
        findings.append({
            "group": "楽器",
            "variants": sorted(hits),
            "matches": {k: sorted(v) for k, v in hits.items()},
            "out_of_scope": sorted(set(ignored)),
        })
    return findings, {k: sorted(v) for k, v in hits.items()}, sorted(set(ignored))


def _role_violations(body, role):
    """§1-6 の excludes に載る楽器が本文に出ていないか。"""
    if role is None:
        return []
    low = body.lower()
    bad = []
    for term in data.ROLES[role]["excludes"]:
        if re.search(_alt([term]), low):
            bad.append(term)
    return bad


def _blur_violations(body, percept_keys):
    """原則8: L6 採用時は blur / bokeh / soft focus を排他。"""
    if not percept_keys or "L6" not in percept_keys:
        return []
    low = body.lower()
    for exempt in data.BLUR_EXEMPT_PHRASES:
        low = low.replace(exempt, "")
    return [t for t in data.BLUR_TERMS if re.search(_alt([t]), low)]


def _redundancy(body):
    """楽器名の反復 / 同義句の同居 / 3-gram の重複 を検出する。"""
    norm = re.sub(r"\s+", " ", body.lower())
    findings = []

    for inst in sorted({spec["instrument"].lower() for spec in data.ROLES.values()}):
        n = len(re.findall(_alt([inst]), norm))
        if n >= 2:
            findings.append({"kind": "楽器名の反復", "detail": "%s ×%d" % (inst, n)})

    for a, b in SYNONYM_PAIRS:
        if a in norm and b in norm:
            findings.append({"kind": "同義句の同居", "detail": "%s ／ %s" % (a, b)})

    tokens = re.findall(r"[a-z0-9']+", norm)
    counts = {}
    for i in range(len(tokens) - N_GRAM + 1):
        gram = tuple(tokens[i:i + N_GRAM])
        if all(t in STOPWORDS for t in gram):
            continue
        counts[gram] = counts.get(gram, 0) + 1
    for gram in sorted(counts):
        if counts[gram] >= 2:
            findings.append({"kind": "%d-gramの重複" % N_GRAM,
                             "detail": "%s ×%d" % (" ".join(gram), counts[gram])})
    return findings


def redundancy_of(text):
    """本文の重複だけを検査する（生成器の再計算条件から呼ばれる）。"""
    return _redundancy(strip_params(text))


def lint(text, role=None, percept_keys=None):
    body = strip_params(text)
    inst_findings, inst_hits, ignored = _scan_instruments(body)
    findings = inst_findings + _scan_plain(body)
    role_bad = _role_violations(body, role)
    blur_bad = _blur_violations(body, percept_keys)
    redundancy = _redundancy(body)
    return {
        "ok": not findings and not role_bad and not blur_bad and not redundancy,
        "redundancy": redundancy,
        "conflicts": findings,
        "instruments_in_scope": inst_hits,
        "instruments_out_of_scope": ignored,
        "role_violations": role_bad,
        "blur_violations": blur_bad,
    }


def format_report(result):
    lines = []
    if result["ok"]:
        lines.append("✅ 競合なし（排他グループ・role除外語・原則8・冗長検査 すべて通過）")
    for f in result["conflicts"]:
        detail = " / ".join("%s: %s" % (k, ", ".join(v)) for k, v in sorted(f["matches"].items()))
        lines.append("⚠️ [%s] %d種類が同居しています → %s" % (f["group"], len(f["variants"]), detail))
        if f.get("out_of_scope"):
            lines.append("   （伴奏スコープとして除外: %s）" % ", ".join(f["out_of_scope"]))
    for t in result["role_violations"]:
        lines.append("⚠️ [role除外] この用途等級で禁止された楽器が本文にあります: %s" % t)
    for t in result["blur_violations"]:
        lines.append("⚠️ [原則8] L6 採用時に排他すべき語があります: %s" % t)
    for f in result.get("redundancy", []):
        lines.append("⚠️ [冗長] %s: %s" % (f["kind"], f["detail"]))
    return "\n".join(lines)
