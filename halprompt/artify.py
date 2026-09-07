# -*- coding: utf-8 -*-
"""§7 artify 仕様

説明語を削除し、不可解要素・素材の自律・未完了を注入する。
「この不可解要素を採用すべきか」は判定しない。選ぶのは seed であり、捨てるのは人間である。
"""

import random
import re

from .lint import strip_params
from .util import tidy

# 削除する語（長い表現を先に当てる）
REMOVE_PATTERNS = [
    r"for identification",
    r"identification",
    r"serial code",
    r"stenciled[^.,;]*glyphs?",
    r"every detail crisp",
    r"ultra high definition",
    r"high resolution",
    r"highly detailed",
    r"museum realism",
    r"photorealistic",
    r"sharp prime lens",
    r"magazine cover[^.,;]*",
    r"snapshot composition",
]

# ① 説明のない要素（1個・必須）
UNEXPLAINED = [
    "a single moth lying on the floor near her feet",
    "a chair turned to face the wall",
    "one shoe different from the other",
    "a fourth instrument standing untouched at the edge of the room",
    "a number chalked on the wall, four digits, no explanation",
    "a clock stopped at a specific time",
    "one figure in the room facing the wrong way",
    "a length of red thread tied around a table leg",
]

# ② 素材の自律（level >= 2）
MATERIAL = [
    "rendered as watercolour bleeding into damp paper, pigment pooling at the edges",
    "printed as a silkscreen with the colours misregistered by several millimetres",
    "shot on film with damaged emulsion, chemical stains eating into the frame",
    "degraded through repeated photocopying, blacks blocking up",
]

# ③ 未完了（level >= 3）
INCOMPLETE = [
    "one corner of the image left unresolved, bare ground showing through",
    "the lower third abandoned, only pencil underdrawing remaining",
    "the background stopping halfway, unpainted beyond that line",
]


def split_params(text):
    """本文とパラメータ部に分ける。パラメータ部は加工しない。"""
    lines = text.splitlines()
    body_lines = [l for l in lines if not l.lstrip().startswith("#")]
    comments = [l for l in lines if l.lstrip().startswith("#")]
    body = "\n".join(body_lines)
    m = re.search(r"(?:^|\s)--", body)
    if m:
        return body[:m.start()].strip(), body[m.start():].strip(), comments
    return body.strip(), "", comments


def artify(text, level=1, seed=0):
    body, params, comments = split_params(text)
    removed = []
    for pat in REMOVE_PATTERNS:
        found = re.findall(pat, body, flags=re.IGNORECASE)
        if found:
            removed.extend(found if isinstance(found[0], str) else [pat])
            body = re.sub(pat, "", body, flags=re.IGNORECASE)
    body = tidy(body)
    if body and not body.endswith("."):
        body += "."

    rnd = random.Random("halprompt/artify/%s/%s" % (seed, level))
    injected = []
    injected.append(rnd.choice(UNEXPLAINED))
    if level >= 2:
        injected.append(rnd.choice(MATERIAL))
    if level >= 3:
        injected.append(rnd.choice(INCOMPLETE))

    body = " ".join([body] + [inj[0].upper() + inj[1:] + "." for inj in injected])
    out = body
    if params:
        out = out + " " + params
    return {
        "text": out,
        "removed": removed,
        "injected": injected,
        "level": level,
        "seed": seed,
        "comments": comments,
    }


def format_report(result):
    lines = ["削除した説明語 : %s" % (", ".join(result["removed"]) if result["removed"] else "なし")]
    lines.append("注入した要素   :")
    for i in result["injected"]:
        lines.append("  ・%s" % i)
    return "\n".join(lines)
