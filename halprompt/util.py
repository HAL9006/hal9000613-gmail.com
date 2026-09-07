# -*- coding: utf-8 -*-
"""共通ユーティリティ。判断は含まない（計数と整形のみ）。"""

import re
import unicodedata


def word_count(text):
    """語数。空白区切りの素朴な計数を全モジュールで統一して使う。"""
    return len(text.split())


def squeeze(text):
    """改行・連続空白を1個の空白に潰す。テンプレートの折り返しを吸収する。"""
    return re.sub(r"\s+", " ", text).strip()


def cap(text):
    """文頭を大文字にする（先頭語のみ。以降は触らない）。"""
    if not text:
        return text
    return text[0].upper() + text[1:]


def tidy(text):
    """削除後に残る句読点の破片を整える。"""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;])", r"\1", text)
    text = re.sub(r"([,;])\s*([,.;])", r"\2", text)
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r"(^|\.\s)\s*,\s*", r"\1", text)
    return text.strip(" ,;")


def width(text):
    """端末上の表示幅。全角は2として数える。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text, n):
    """表示幅 n まで右側を空白で埋める。"""
    return text + " " * max(0, n - width(text))
