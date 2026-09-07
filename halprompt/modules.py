# -*- coding: utf-8 -*-
"""§3 モジュール合成

プロンプトは M0..M3 の連結で構成する。各モジュールが long / mid / short を持つ。
M4 PERCEPT LENS は任意（0〜2個）で末尾に付く。
"""

from . import data
from .util import cap, squeeze, word_count

MODULE_IDS = ["M0", "M1", "M2", "M3"]
MODULE_LABELS = {
    "M0": "FASHION",
    "M1": "PERFORMANCE",
    "M2": "ANDROID + ENVIRONMENT",
    "M3": "FINISH",
}
VARIANTS = ["long", "mid", "short"]


def second_player(role):
    """M1 の二人目。role と同一楽器になる場合だけ差し替える（README に明記）。"""
    if data.ROLES[role]["player"] == data.SECOND_PLAYER_DEFAULT:
        return data.SECOND_PLAYER_FALLBACK
    return data.SECOND_PLAYER_DEFAULT


# ── M1 PERFORMANCE ──────────────────────────────────────────
def m1(role, variant):
    spec = data.ROLES[role]
    player, inst, second = spec["player"], spec["instrument"], second_player(role)
    if variant == "long":
        t = """
        Humanoid female {player} and a humanoid {second}, two players only. She
        stands with the {inst} leaned away to her right so her body stays clear
        of it, seen from her open left side. Played in a relaxed, seasoned style.
        """
    elif variant == "mid":
        t = """
        Humanoid female {player}, a second player behind her, {inst} held clear
        of her body.
        """
    else:
        t = "Humanoid female {player}."
    return squeeze(t.format(player=player, second=second, inst=inst))


# ── M2 ANDROID + ENVIRONMENT ────────────────────────────────
def m2(scene, variant):
    if variant == "long":
        t = """
        A thick voluminous blunt fringed wig, cap seam visible at the hairline.
        Western appearance, defiant expression, round musician glasses, stylized
        facial markings. Porcelain skin with mechanical seams; wrist and neck
        joints glow with bioluminescent circuits. {scene}, strong backlighting
        through a single window with soft fill from the front.
        """
    elif variant == "mid":
        t = """
        A thick voluminous blunt fringed wig, blunt bangs, round musician
        glasses, stylized facial markings. Porcelain skin with mechanical seams,
        glowing wrist and neck joints. {scene}, backlit with soft fill.
        """
    else:
        t = """
        Blunt fringed wig, round glasses, porcelain skin with mechanical seams,
        glowing joints. {scene}.
        """
    return squeeze(t.format(scene=cap(scene)))


# ── M3 FINISH ───────────────────────────────────────────────
def m3(lens, accent, variant):
    if variant == "long":
        t = """
        {lens}Monochrome with one vivid {accent} focal point at her lips. Helmut
        Newton and Man Ray aesthetics, museum realism, existential distance.
        """
    elif variant == "mid":
        t = """
        {lens}Monochrome with one vivid {accent} focal point at her lips. Helmut
        Newton and Man Ray aesthetics.
        """
    else:
        t = "{lens}Monochrome, one {accent} accent at her lips."
    lens_part = ("%s. " % lens.rstrip(". ")) if lens.strip() else ""
    return squeeze(t.format(lens=lens_part, accent=accent))


# ── M4 PERCEPT LENS ─────────────────────────────────────────
def m4(keys, accent):
    if not keys:
        return ""
    parts = [data.PERCEPT_LENSES[k]["text"].format(accent=accent) for k in keys]
    return squeeze(" ".join(parts))


def build_variants(costume, role, scene, lens, accent):
    """M0..M3 × long/mid/short の全断片を作る。ここに判断は無い。"""
    return {
        "M0": {v: costume.fragment(v) for v in VARIANTS},
        "M1": {v: m1(role, v) for v in VARIANTS},
        "M2": {v: m2(scene, v) for v in VARIANTS},
        "M3": {v: m3(lens, accent, v) for v in VARIANTS},
    }


def word_table(variants):
    return {m: {v: word_count(t) for v, t in d.items()} for m, d in variants.items()}
