#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF図面向け インタラクティブ スタンプ／アノテーション配置アプリ (PoC)

macOS + Python 3.10+ / PySide6 + PyMuPDF で動作する単一ファイル プロトタイプ。

設計方針
--------
将来 Windows 上で DocuWorks SDK (xdwlib) へ出力先を差し替えられるよう、
以下の3層を明確に分離している。

    1. コア        : StampCatalog / Placement / AnnotationDocument
                     （スタンプ定義・相対座標・配置リストの管理）
    2. ジオメトリ  : build_primitives()
                     （相対座標 0.0-1.0 → 用紙絶対座標 pt への変換と図形化）
    3. Exporter    : BaseExporter → PyMuPDFExporter / DocuWorksExporter
                     （描画出力だけを担当。差し替え可能）

GUI (PySide6) はコア層の薄いラッパであり、同じ build_primitives() の結果を
画面プレビューにも PDF 出力にも使うため、見た目と出力が一致する。

使い方
------
    GUI:
        python app.py [図面.pdf]

    ヘッドレス（AI/JSON 連携の確認用。PySide6 不要）:
        python app.py --batch --input 図面.pdf --annotations ann.json --output 出力.pdf

    自己テスト（サンプルPDFを生成してスタンプを打つ）:
        python app.py --selftest --output /tmp/selftest.pdf

    目視確認用の PNG 書き出し（配置結果とスタンプ一覧）:
        python app.py --preview --out-dir out --dpi 200
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

# PyMuPDF 1.24 以降はパッケージ名が pymupdf。旧環境の fitz にもフォールバックする。
try:  # pragma: no cover - 環境差の吸収のみ
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

APP_NAME = "PDF Stamp Annotator (PoC)"
ANNOT_AUTHOR = "PDF Stamp PoC"

MM_TO_PT = 72.0 / 25.4          # 1mm = 2.8346pt
PT_TO_MM = 25.4 / 72.0

DEFAULT_CATALOG_PATH = Path(__file__).with_name("stamp_catalog.json")

RGB = tuple[float, float, float]


# =============================================================================
# 1. コア層 : 色・スタンプ定義・カタログ
# =============================================================================

def parse_color(value: Any, fallback: RGB = (0.0, 0.0, 0.0)) -> RGB:
    """"#RRGGBB" / [r,g,b](0-1) / [r,g,b](0-255) のいずれも 0.0-1.0 の RGB に正規化する。"""
    if value is None:
        return fallback
    if isinstance(value, str):
        s = value.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            raise ValueError(f"色指定を解釈できません: {value!r}")
        return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    if isinstance(value, (list, tuple)) and len(value) == 3:
        vals = [float(v) for v in value]
        if any(v > 1.0 for v in vals):       # 0-255 表記とみなす
            vals = [v / 255.0 for v in vals]
        return tuple(min(1.0, max(0.0, v)) for v in vals)  # type: ignore[return-value]
    raise ValueError(f"色指定を解釈できません: {value!r}")


@dataclass(frozen=True)
class StampDef:
    """stamp_catalog.json の 1 エントリ。"""

    id: str
    label: str
    shape: str                      # cross / rect / circle / arrow / text / cloud
    color: RGB = (1.0, 0.0, 0.0)
    size_mm: tuple[float, float] = (10.0, 10.0)
    line_width: float = 1.2
    font_size_pt: float = 9.0
    label_gap_mm: float = 1.5
    angle_deg: float = 225.0        # arrow の尾の向き（画面座標系・y下向き）
    default_text: str = ""
    show_label: bool = True

    SHAPES = ("cross", "rect", "circle", "arrow", "text", "cloud")

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: dict[str, Any] | None = None) -> "StampDef":
        d = dict(defaults or {})
        d.update(data)
        try:
            stamp_id = str(d["id"])
            label = str(d.get("label", d["id"]))
            shape = str(d.get("shape", "rect")).lower()
        except KeyError as exc:
            raise ValueError(f"スタンプ定義に必須キーがありません: {exc}") from exc
        if shape not in cls.SHAPES:
            raise ValueError(f"未知の描画種別 shape={shape!r} (id={stamp_id})")
        size = d.get("size_mm", (10.0, 10.0))
        if not (isinstance(size, (list, tuple)) and len(size) == 2):
            raise ValueError(f"size_mm は [幅mm, 高さmm] で指定してください (id={stamp_id})")
        return cls(
            id=stamp_id,
            label=label,
            shape=shape,
            color=parse_color(d.get("color"), (1.0, 0.0, 0.0)),
            size_mm=(float(size[0]), float(size[1])),
            line_width=float(d.get("line_width", 1.2)),
            font_size_pt=float(d.get("font_size_pt", 9.0)),
            label_gap_mm=float(d.get("label_gap_mm", 1.5)),
            angle_deg=float(d.get("angle_deg", 225.0)),
            default_text=str(d.get("default_text", "")),
            show_label=bool(d.get("show_label", True)),
        )


class StampCatalog:
    """スタンプ定義の集合。JSON から読み込み、ID で引く。"""

    def __init__(self, stamps: Sequence[StampDef]):
        self._stamps: list[StampDef] = list(stamps)
        self._by_id: dict[str, StampDef] = {s.id: s for s in self._stamps}

    def __len__(self) -> int:
        return len(self._stamps)

    def __iter__(self):
        return iter(self._stamps)

    def get(self, symbol_id: str) -> StampDef | None:
        return self._by_id.get(symbol_id)

    def require(self, symbol_id: str) -> StampDef:
        stamp = self._by_id.get(symbol_id)
        if stamp is None:
            raise KeyError(f"未登録のスタンプIDです: {symbol_id!r}（候補: {', '.join(self._by_id)}）")
        return stamp

    @classmethod
    def load(cls, path: str | os.PathLike[str] = DEFAULT_CATALOG_PATH) -> "StampCatalog":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, list):            # 配列だけの簡易フォーマットも許容
            entries, defaults = raw, {}
        else:
            entries = raw.get("stamps", [])
            defaults = raw.get("defaults", {})
        if not entries:
            raise ValueError(f"スタンプが1件も定義されていません: {path}")
        return cls([StampDef.from_dict(e, defaults) for e in entries])


# =============================================================================
# 2. コア層 : 配置（相対座標 0.0-1.0）とドキュメント
# =============================================================================

@dataclass
class Placement:
    """1 個のスタンプ配置。座標は用紙の幅・高さに対する比率 (0.0-1.0, 原点=左上)。"""

    page: int
    symbol_id: str
    norm_x: float
    norm_y: float
    text: str = ""
    scale: float = 1.0
    angle_deg: float | None = None      # None ならカタログ既定値
    color: RGB | None = None            # None ならカタログ既定値

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "page": self.page,
            "symbol_id": self.symbol_id,
            "norm_x": round(self.norm_x, 5),
            "norm_y": round(self.norm_y, 5),
        }
        if self.text:
            d["text"] = self.text
        if self.scale != 1.0:
            d["scale"] = self.scale
        if self.angle_deg is not None:
            d["angle_deg"] = self.angle_deg
        if self.color is not None:
            d["color"] = "#%02X%02X%02X" % tuple(int(round(c * 255)) for c in self.color)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Placement":
        if not isinstance(data, dict):
            raise ValueError(f"アノテーション要素は object である必要があります: {data!r}")
        missing = [k for k in ("symbol_id", "norm_x", "norm_y") if k not in data]
        if missing:
            raise ValueError(f"必須キーがありません: {', '.join(missing)} / {data!r}")
        return cls(
            page=int(data.get("page", 0)),
            symbol_id=str(data["symbol_id"]),
            norm_x=float(data["norm_x"]),
            norm_y=float(data["norm_y"]),
            text=str(data.get("text", "")),
            scale=float(data.get("scale", 1.0)),
            angle_deg=(float(data["angle_deg"]) if data.get("angle_deg") is not None else None),
            color=(parse_color(data["color"]) if data.get("color") is not None else None),
        )


# =============================================================================
# 3. ジオメトリ層 : 相対座標 → 用紙絶対座標（pt）への変換と図形化
# =============================================================================

@dataclass
class Prim:
    """描画プリミティブ。座標は用紙絶対座標 pt（原点=左上, y は下向き）。

    画面プレビュー（QPainter）と PDF 出力（PyMuPDF）の双方が
    この同じプリミティブ列を描くため、見た目と成果物が一致する。
    """

    kind: str                                   # stroke / arrow / rect / ellipse / text
    color: RGB
    width: float = 1.0
    points: list[tuple[float, float]] = field(default_factory=list)   # stroke / arrow
    rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)    # rect / ellipse / text
    text: str = ""
    font_size: float = 9.0

    def bbox(self) -> tuple[float, float, float, float]:
        if self.points:
            xs = [p[0] for p in self.points]
            ys = [p[1] for p in self.points]
            return (min(xs), min(ys), max(xs), max(ys))
        return self.rect


def text_width_pt(text: str, font_size: float) -> float:
    """文字列の描画幅の概算 [pt]。全角は 1.0em、半角は 0.55em として見積もる。"""
    return font_size * sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in text)


def _cloud_points(x0: float, y0: float, x1: float, y1: float, bump: float) -> list[tuple[float, float]]:
    """矩形の外周に半円の膨らみを並べた「変更雲」のポリラインを作る。"""
    bump = max(2.0, min(bump, (x1 - x0) / 2, (y1 - y0) / 2))
    pts: list[tuple[float, float]] = []

    def edge(ax: float, ay: float, bx: float, by: float) -> None:
        length = math.hypot(bx - ax, by - ay)
        n = max(1, int(round(length / (bump * 2))))
        ux, uy = (bx - ax) / length, (by - ay) / length
        nx, ny = -uy, ux                       # 外向き法線（時計回りに辿る前提）
        step = length / n
        for i in range(n):
            sx, sy = ax + ux * step * i, ay + uy * step * i
            r = step / 2.0
            cx, cy = sx + ux * r, sy + uy * r
            for k in range(9):                 # 半円を 8 分割した折れ線で近似
                th = math.pi * k / 8.0
                px = cx - ux * r * math.cos(th) + nx * r * math.sin(th)
                py = cy - uy * r * math.cos(th) + ny * r * math.sin(th)
                pts.append((px, py))

    edge(x0, y0, x1, y0)
    edge(x1, y0, x1, y1)
    edge(x1, y1, x0, y1)
    edge(x0, y1, x0, y0)
    pts.append(pts[0])
    return pts


def build_primitives(
    stamp: StampDef,
    placement: Placement,
    page_rect: tuple[float, float, float, float],
) -> list[Prim]:
    """比率座標のスタンプ配置を、用紙絶対座標のプリミティブ列に展開する。

    page_rect は (x0, y0, x1, y1) [pt]。norm_x/norm_y はこの矩形に対する比率。
    スタンプの寸法は用紙上の実寸 (mm) で扱うため、A3/A1 など用紙サイズが
    変わっても図面上の見かけの大きさは一定になる。
    """
    px0, py0, px1, py1 = page_rect
    cx = px0 + placement.norm_x * (px1 - px0)
    cy = py0 + placement.norm_y * (py1 - py0)

    color = placement.color or stamp.color
    scale = max(0.05, placement.scale)
    w = stamp.size_mm[0] * MM_TO_PT * scale
    h = stamp.size_mm[1] * MM_TO_PT * scale
    lw = max(0.2, stamp.line_width * scale)
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2

    prims: list[Prim] = []
    shape = stamp.shape

    if shape == "cross":
        prims.append(Prim("stroke", color, lw, points=[(x0, y0), (x1, y1)]))
        prims.append(Prim("stroke", color, lw, points=[(x1, y0), (x0, y1)]))
    elif shape == "rect":
        prims.append(Prim("rect", color, lw, rect=(x0, y0, x1, y1)))
    elif shape == "circle":
        prims.append(Prim("ellipse", color, lw, rect=(x0, y0, x1, y1)))
    elif shape == "cloud":
        prims.append(Prim("stroke", color, lw,
                          points=_cloud_points(x0, y0, x1, y1, 4.0 * MM_TO_PT * scale)))
    elif shape == "arrow":
        angle = math.radians(placement.angle_deg if placement.angle_deg is not None else stamp.angle_deg)
        length = max(w, h)
        tail = (cx + length * math.cos(angle), cy + length * math.sin(angle))
        prims.append(Prim("arrow", color, lw, points=[tail, (cx, cy)]))
    elif shape == "text":
        prims.append(Prim("rect", color, lw, rect=(x0, y0, x1, y1)))
    else:  # pragma: no cover - StampDef.from_dict で弾かれる
        raise ValueError(f"未知の描画種別: {shape}")

    text = placement.text or stamp.default_text
    if text and stamp.show_label:
        fs = stamp.font_size_pt * scale
        if shape == "text":
            # 文字スタンプは枠の内側に描く
            prims.append(Prim("text", color, lw, rect=(x0, y0, x1, y1), text=text, font_size=fs))
        else:
            gap = stamp.label_gap_mm * MM_TO_PT * scale
            ly0 = y1 + gap
            lw_box = max(w, text_width_pt(text, fs) + fs)
            prims.append(Prim("text", color, lw,
                              rect=(cx - lw_box / 2, ly0, cx + lw_box / 2, ly0 + fs * 1.6),
                              text=text, font_size=fs))
    return prims


def primitives_bbox(prims: Iterable[Prim]) -> tuple[float, float, float, float] | None:
    boxes = [p.bbox() for p in prims]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


# =============================================================================
# 4. コア層 : ドキュメント（PDF + 配置リスト）
# =============================================================================

class AnnotationDocument:
    """開いている PDF と、そこに載せるスタンプ配置リストを保持する。

    PDF 本体には一切書き込まない（非破壊）。出力は Exporter が別ファイルへ行う。
    """

    def __init__(self, catalog: StampCatalog, pdf_path: str | os.PathLike[str] | None = None):
        self.catalog = catalog
        self.doc: Any | None = None
        self.path: Path | None = None
        self.placements: list[Placement] = []
        if pdf_path is not None:
            self.open(pdf_path)

    # -- PDF ---------------------------------------------------------------
    def open(self, pdf_path: str | os.PathLike[str]) -> None:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF が見つかりません: {path}")
        if self.doc is not None:
            self.doc.close()
        self.doc = fitz.open(path)
        self.path = path
        self.placements.clear()

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
            self.doc = None

    @property
    def page_count(self) -> int:
        return 0 if self.doc is None else self.doc.page_count

    def page_rect(self, page: int) -> tuple[float, float, float, float]:
        """ページ矩形 (x0, y0, x1, y1) [pt]。PyMuPDF の座標系は原点が左上。"""
        if self.doc is None:
            raise RuntimeError("PDF が開かれていません")
        r = self.doc[page].rect
        return (r.x0, r.y0, r.x1, r.y1)

    # -- 配置操作 ----------------------------------------------------------
    def add_placement(self, placement: Placement) -> Placement:
        self.catalog.require(placement.symbol_id)          # 未知IDはここで弾く
        if self.doc is not None and not (0 <= placement.page < self.page_count):
            raise ValueError(f"ページ番号が範囲外です: {placement.page} (0-{self.page_count - 1})")
        self.placements.append(placement)
        return placement

    def add_stamp(self, page: int, symbol_id: str, norm_x: float, norm_y: float,
                  text: str | None = None, **kwargs: Any) -> Placement:
        """パレットで選んだスタンプを指定の比率座標に置く（GUI クリック時の入口）。"""
        stamp = self.catalog.require(symbol_id)
        return self.add_placement(Placement(
            page=page,
            symbol_id=symbol_id,
            norm_x=min(1.0, max(0.0, float(norm_x))),
            norm_y=min(1.0, max(0.0, float(norm_y))),
            text=stamp.default_text if text is None else text,
            **kwargs,
        ))

    def placements_on(self, page: int) -> list[Placement]:
        return [p for p in self.placements if p.page == page]

    def primitives_for(self, placement: Placement) -> list[Prim]:
        stamp = self.catalog.require(placement.symbol_id)
        return build_primitives(stamp, placement, self.page_rect(placement.page))

    def hit_test(self, page: int, x_pt: float, y_pt: float, margin: float = 4.0) -> Placement | None:
        """用紙絶対座標 (pt) にあるスタンプを、後から置いたものを優先して返す。"""
        for placement in reversed(self.placements):
            if placement.page != page:
                continue
            box = primitives_bbox(self.primitives_for(placement))
            if box and (box[0] - margin <= x_pt <= box[2] + margin
                        and box[1] - margin <= y_pt <= box[3] + margin):
                return placement
        return None

    def remove(self, placement: Placement) -> bool:
        for i, p in enumerate(self.placements):
            if p is placement:
                del self.placements[i]
                return True
        return False

    def undo(self) -> Placement | None:
        return self.placements.pop() if self.placements else None

    def clear(self, page: int | None = None) -> int:
        before = len(self.placements)
        if page is None:
            self.placements.clear()
        else:
            self.placements = [p for p in self.placements if p.page != page]
        return before - len(self.placements)

    # -- AI / JSON 連携 ----------------------------------------------------
    def apply_json_annotations(self, json_data: Any, replace: bool = False) -> list[Placement]:
        """構造化 JSON を受け取り、一括でスタンプを配置する。

        受け付ける形式:
            * list[dict]                         … 仕様どおりの配列
            * {"annotations": [...]} / {"stamps": [...]}
            * 上記いずれかの JSON 文字列 / bytes
            * .json ファイルのパス

        例::

            [
              {"page": 0, "symbol_id": "STAMP_X",    "norm_x": 0.5, "norm_y": 0.3, "text": "削除"},
              {"page": 0, "symbol_id": "STAMP_RECT", "norm_x": 0.2, "norm_y": 0.4, "text": "要確認"}
            ]

        全件を検証してから一括適用する（1件でも不正なら何も変更しない）。
        戻り値は追加された Placement のリスト。
        """
        items = _coerce_annotation_items(json_data)
        staged = [Placement.from_dict(item) for item in items]
        for p in staged:                                    # 先に全件検証
            self.catalog.require(p.symbol_id)
            if self.doc is not None and not (0 <= p.page < self.page_count):
                raise ValueError(f"ページ番号が範囲外です: {p.page} (0-{self.page_count - 1})")
        if replace:
            self.placements.clear()
        self.placements.extend(staged)
        return staged

    def to_json(self, indent: int = 2) -> str:
        """配置リストを JSON 文字列へ（AI へ渡す／再読込みするための往復用）。"""
        payload = {
            "source_pdf": self.path.name if self.path else None,
            "annotations": [p.to_dict() for p in self.placements],
        }
        return json.dumps(payload, ensure_ascii=False, indent=indent)


def _coerce_annotation_items(json_data: Any) -> list[dict[str, Any]]:
    """list / dict / JSON文字列 / ファイルパス を、アノテーション dict の配列に揃える。"""
    data = json_data
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, Path):
        data = data.read_text(encoding="utf-8")
    if isinstance(data, str):
        stripped = data.strip()
        if not stripped.startswith(("[", "{")) and Path(stripped).exists():
            stripped = Path(stripped).read_text(encoding="utf-8")
        data = json.loads(stripped)
    if isinstance(data, dict):
        for key in ("annotations", "stamps", "items"):
            if key in data:
                data = data[key]
                break
        else:
            data = [data]                                  # 単体 dict も許容
    if not isinstance(data, list):
        raise ValueError("アノテーションは配列（list）である必要があります")
    return data


# =============================================================================
# 5. Exporter 層 : 描画出力（差し替え可能）
# =============================================================================

class BaseExporter:
    """描画出力の抽象基底。

    コア層（カタログ・比率座標・配置リスト）は Exporter の実装を知らない。
    Mac では PyMuPDFExporter、Windows では DocuWorksExporter（xdwlib）を
    差し込むだけで出力先を切り替えられる。
    """

    name = "base"
    suffix = ""

    def export(self, document: "AnnotationDocument", out_path: str | os.PathLike[str],
               **options: Any) -> Path:
        raise NotImplementedError


class PyMuPDFExporter(BaseExporter):
    """PyMuPDF で PDF にスタンプを描き込み、別名保存する（元ファイルは無変更）。

    mode="annotation" : PDF 標準アノテーション（Ink/Line/Square/Circle/FreeText）。
                        ビューアで選択・削除・コメント参照ができる非破壊的な出力。
    mode="vector"     : ページ内容としてベクトル描画（アノテーション非対応の
                        下流ツールへ渡す場合や、確定版を作る場合に使う）。
    """

    name = "pymupdf"
    suffix = ".pdf"

    LINE_END_NONE = getattr(fitz, "PDF_ANNOT_LE_NONE", 0)
    LINE_END_ARROW = getattr(fitz, "PDF_ANNOT_LE_OPEN_ARROW", 4)

    def export(self, document: "AnnotationDocument", out_path: str | os.PathLike[str],
               mode: str = "annotation", **options: Any) -> Path:
        if document.path is None:
            raise RuntimeError("保存元の PDF が開かれていません")
        if mode not in ("annotation", "vector"):
            raise ValueError(f"mode は 'annotation' か 'vector' です: {mode!r}")

        out = Path(out_path)
        if out.resolve() == document.path.resolve():
            raise ValueError("元ファイルへの上書きは行いません。別名を指定してください。")

        # 元ファイルは開いたまま触らず、出力用に読み直す（非破壊）
        doc = fitz.open(document.path)
        try:
            for placement in document.placements:
                if not (0 <= placement.page < doc.page_count):
                    continue
                stamp = document.catalog.require(placement.symbol_id)
                page = doc[placement.page]
                prims = build_primitives(stamp, placement, tuple(page.rect))
                note = self._note(stamp, placement)
                if mode == "annotation":
                    self._draw_as_annots(page, prims, note)
                else:
                    self._draw_as_vector(page, prims)
            out.parent.mkdir(parents=True, exist_ok=True)
            doc.save(out, garbage=3, deflate=True)
        finally:
            doc.close()
        return out

    # -- 内部 --------------------------------------------------------------
    @staticmethod
    def _note(stamp: StampDef, placement: Placement) -> str:
        text = placement.text or stamp.default_text
        head = f"{stamp.label}" + (f" : {text}" if text else "")
        return f"{head}\n[{stamp.id}] p{placement.page + 1} " \
               f"(x={placement.norm_x:.3f}, y={placement.norm_y:.3f})"

    def _finish(self, annot: Any, color: RGB, width: float, note: str) -> None:
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
        annot.set_info(title=ANNOT_AUTHOR, content=note)
        annot.update(opacity=1.0)

    def _draw_as_annots(self, page: Any, prims: Sequence[Prim], note: str) -> None:
        # 同一スタンプの線分群はまとめて 1 つの Ink アノテーションにする
        strokes = [p for p in prims if p.kind == "stroke"]
        if strokes:
            annot = page.add_ink_annot([list(p.points) for p in strokes])
            self._finish(annot, strokes[0].color, strokes[0].width, note)

        for prim in prims:
            if prim.kind == "stroke":
                continue
            if prim.kind == "arrow":
                annot = page.add_line_annot(prim.points[0], prim.points[1])
                annot.set_line_ends(self.LINE_END_NONE, self.LINE_END_ARROW)
                self._finish(annot, prim.color, prim.width, note)
            elif prim.kind == "rect":
                annot = page.add_rect_annot(fitz.Rect(prim.rect))
                self._finish(annot, prim.color, prim.width, note)
            elif prim.kind == "ellipse":
                annot = page.add_circle_annot(fitz.Rect(prim.rect))
                self._finish(annot, prim.color, prim.width, note)
            elif prim.kind == "text":
                self._add_text_annot(page, prim, note)

    def _add_text_annot(self, page: Any, prim: Prim, note: str) -> None:
        rect = fitz.Rect(prim.rect)
        for fontname in ("japan", None):        # 日本語は CJK 組込みフォントで
            try:
                annot = page.add_freetext_annot(
                    rect, prim.text,
                    fontsize=prim.font_size,
                    fontname=fontname,
                    text_color=prim.color,
                    border_width=0,
                    align=1,                    # 中央寄せ
                )
                # FreeText の /Contents は表示文字そのものなので、
                # 注記は subject 側に入れて表示文字を壊さない。
                annot.set_info(title=ANNOT_AUTHOR, subject=note)
                annot.update()
                return
            except Exception:                   # pragma: no cover - 環境依存の保険
                continue
        # 最終手段: ページ内容として描画
        page.insert_textbox(rect, prim.text, fontname="japan",
                            fontsize=prim.font_size, color=prim.color, align=1)

    @staticmethod
    def _draw_as_vector(page: Any, prims: Sequence[Prim]) -> None:
        for prim in prims:
            if prim.kind == "text":
                page.insert_textbox(fitz.Rect(prim.rect), prim.text, fontname="japan",
                                    fontsize=prim.font_size, color=prim.color, align=1)
                continue
            shape = page.new_shape()
            if prim.kind == "stroke":
                for a, b in zip(prim.points, prim.points[1:]):
                    shape.draw_line(a, b)
            elif prim.kind == "arrow":
                tail, head = prim.points
                shape.draw_line(tail, head)
                ang = math.atan2(head[1] - tail[1], head[0] - tail[0])
                barb = max(4.0, prim.width * 5)
                for sign in (+1, -1):
                    th = ang + sign * math.radians(160)
                    shape.draw_line(head, (head[0] + barb * math.cos(th),
                                           head[1] + barb * math.sin(th)))
            elif prim.kind == "rect":
                shape.draw_rect(fitz.Rect(prim.rect))
            elif prim.kind == "ellipse":
                shape.draw_oval(fitz.Rect(prim.rect))
            shape.finish(color=prim.color, width=prim.width, closePath=False)
            shape.commit()


class DocuWorksExporter(BaseExporter):
    """Windows 版の出力先（将来実装）。

    コア層は比率座標 (0.0-1.0) と mm 実寸だけを扱うため、この Exporter を
    実装するだけで DocuWorks へ出力できる。実装時の対応表:

        build_primitives() の Prim      → xdwlib のアノテーション
        ------------------------------------------------------------
        stroke (折れ線)                 → XDW_AID_STRAIGHTLINE の連結 / FREEHAND
        arrow  (矢印)                   → XDW_AID_ARROW
        rect   (矩形)                   → XDW_AID_RECTANGLE
        ellipse(楕円)                   → XDW_AID_ARC (楕円)
        text   (文字)                   → XDW_AID_TEXT

    座標系の注意: Prim は pt（1/72 inch・原点左上）。DocuWorks の
    アノテーション座標は 1/100 mm 単位なので、pt * 25.4/72 * 100 で換算する。
    """

    name = "docuworks"
    suffix = ".xdw"

    @staticmethod
    def pt_to_xdw(value: float) -> int:
        """pt → DocuWorks 内部単位（1/100 mm）。"""
        return int(round(value * PT_TO_MM * 100))

    def export(self, document: "AnnotationDocument", out_path: str | os.PathLike[str],
               **options: Any) -> Path:
        raise NotImplementedError(
            "DocuWorks 出力は Windows + DocuWorks SDK (xdwlib) 環境で実装してください。"
            "コア層の Placement / build_primitives() はそのまま再利用できます。"
        )


EXPORTERS: dict[str, type[BaseExporter]] = {
    PyMuPDFExporter.name: PyMuPDFExporter,
    DocuWorksExporter.name: DocuWorksExporter,
}


def get_exporter(name: str = "pymupdf") -> BaseExporter:
    try:
        return EXPORTERS[name]()
    except KeyError as exc:
        raise KeyError(f"未知の Exporter: {name!r}（利用可能: {', '.join(EXPORTERS)}）") from exc


def save_pdf(document: "AnnotationDocument", out_path: str | os.PathLike[str],
             mode: str = "annotation", exporter: str | BaseExporter = "pymupdf") -> Path:
    """配置済みスタンプを描画した PDF を別名保存する（仕様の save_pdf）。

    元の PDF には一切書き込まない。戻り値は保存先パス。
    """
    exp = get_exporter(exporter) if isinstance(exporter, str) else exporter
    return exp.export(document, out_path, mode=mode)


# =============================================================================
# 6. GUI 層 (PySide6)
# =============================================================================
# PySide6 が無い環境でもコア層と Exporter を import / --batch 実行できるように、
# GUI のインポートは失敗を許容し、実際に使う段階でエラーを出す。

try:
    from PySide6.QtCore import Qt, QPointF, QRectF, Signal
    from PySide6.QtGui import (QAction, QColor, QFont, QImage, QKeySequence,
                               QPainter, QPen, QPixmap, QPolygonF)
    from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog,
                                   QHBoxLayout, QLabel, QLineEdit, QListWidget,
                                   QListWidgetItem, QMainWindow, QMessageBox, QScrollArea,
                                   QSplitter, QVBoxLayout, QWidget)
    HAS_QT = True
    QT_IMPORT_ERROR: Exception | None = None
except ImportError as _exc:                     # pragma: no cover - 環境差の吸収
    HAS_QT = False
    QT_IMPORT_ERROR = _exc

    class _QtMissing:                           # GUI クラス定義だけ通すためのダミー
        def __init__(self, *args: Any, **kwargs: Any):
            raise RuntimeError(
                "PySide6 がインストールされていません。`pip install -r requirements.txt` を実行してください。"
            )

    def Signal(*args: Any, **kwargs: Any):      # type: ignore[misc]
        return None

    QWidget = QMainWindow = QScrollArea = QListWidget = _QtMissing          # type: ignore[misc,assignment]


class PdfCanvas(QWidget):
    """PDF 1 ページのレンダリング表示 + スタンププレビュー + クリック入力。"""

    stampRequested = Signal(float, float)       # norm_x, norm_y
    deleteRequested = Signal(float, float)
    cursorMoved = Signal(float, float)

    def __init__(self, document: AnnotationDocument, parent: Any = None):
        super().__init__(parent)
        self.document = document
        self.page_index = 0
        self.zoom = 1.0
        self._pixmap: Any = None
        self._cache_key: tuple[int, float, int] | None = None
        self.selected: Placement | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TabletTracking, True)

    # -- レンダリング ------------------------------------------------------
    def refresh(self, force: bool = False) -> None:
        """現在のページ・ズームで PDF を再レンダリングする。"""
        if self.document.doc is None:
            self._pixmap = None
            self.setFixedSize(600, 400)
            self.update()
            return
        key = (self.page_index, round(self.zoom, 4), id(self.document.doc))
        if force or key != self._cache_key:
            page = self.document.doc[self.page_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride,
                           QImage.Format.Format_RGB888)
            self._pixmap = QPixmap.fromImage(image.copy())   # バッファから切り離す
            self._cache_key = key
            self.setFixedSize(self._pixmap.size())
        self.update()

    def set_page(self, index: int) -> None:
        self.page_index = max(0, min(index, max(0, self.document.page_count - 1)))
        self.selected = None
        self.refresh()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.1, min(8.0, zoom))
        self.refresh()

    def fit_to_width(self, width: int) -> None:
        if self.document.doc is None:
            return
        x0, _, x1, _ = self.document.page_rect(self.page_index)
        if x1 - x0 > 0:
            self.set_zoom((width - 24) / (x1 - x0))

    # -- 座標変換 ----------------------------------------------------------
    def _widget_to_norm(self, pos: Any) -> tuple[float, float]:
        x0, y0, x1, y1 = self.document.page_rect(self.page_index)
        px = x0 + pos.x() / self.zoom
        py = y0 + pos.y() / self.zoom
        return ((px - x0) / (x1 - x0), (py - y0) / (y1 - y0))

    # -- 描画 --------------------------------------------------------------
    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._pixmap is None:
            painter.fillRect(self.rect(), QColor("#3a3a3a"))
            painter.setPen(QColor("#dddddd"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "PDF を開いてください（⌘O / ツールバー「開く」）")
            return
        painter.drawPixmap(0, 0, self._pixmap)
        for placement in self.document.placements_on(self.page_index):
            try:
                prims = self.document.primitives_for(placement)
            except KeyError:
                continue
            self._paint_prims(painter, prims)
            if placement is self.selected:
                self._paint_selection(painter, prims)

    def _to_px(self, x_pt: float, y_pt: float) -> Any:
        x0, y0, _, _ = self.document.page_rect(self.page_index)
        return QPointF((x_pt - x0) * self.zoom, (y_pt - y0) * self.zoom)

    def _paint_prims(self, painter: Any, prims: Sequence[Prim]) -> None:
        for prim in prims:
            color = QColor.fromRgbF(*prim.color)
            pen = QPen(color, max(1.0, prim.width * self.zoom))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if prim.kind == "stroke":
                painter.drawPolyline(QPolygonF([self._to_px(*p) for p in prim.points]))
            elif prim.kind == "arrow":
                tail, head = (self._to_px(*p) for p in prim.points)
                painter.drawLine(tail, head)
                ang = math.atan2(head.y() - tail.y(), head.x() - tail.x())
                barb = max(5.0, prim.width * 5 * self.zoom)
                for sign in (+1, -1):
                    th = ang + sign * math.radians(160)
                    painter.drawLine(head, QPointF(head.x() + barb * math.cos(th),
                                                   head.y() + barb * math.sin(th)))
            elif prim.kind in ("rect", "ellipse"):
                x0, y0, x1, y1 = prim.rect
                p0, p1 = self._to_px(x0, y0), self._to_px(x1, y1)
                rect = QRectF(p0, p1)
                painter.drawRect(rect) if prim.kind == "rect" else painter.drawEllipse(rect)
            elif prim.kind == "text":
                x0, y0, x1, y1 = prim.rect
                p0, p1 = self._to_px(x0, y0), self._to_px(x1, y1)
                font = QFont()
                font.setPointSizeF(max(4.0, prim.font_size * self.zoom))
                painter.setFont(font)
                painter.drawText(QRectF(p0, p1), Qt.AlignmentFlag.AlignCenter, prim.text)

    def _paint_selection(self, painter: Any, prims: Sequence[Prim]) -> None:
        box = primitives_bbox(prims)
        if not box:
            return
        pen = QPen(QColor("#2080FF"), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        p0, p1 = self._to_px(box[0] - 2, box[1] - 2), self._to_px(box[2] + 2, box[3] + 2)
        painter.drawRect(QRectF(p0, p1))

    # -- 入力（マウス / ペンタブレット）------------------------------------
    def _is_synthesized(self, event: Any) -> bool:
        try:                                    # タブレットから合成されたマウスイベントは無視
            return event.source() != Qt.MouseEventSource.MouseEventNotSynthesized
        except Exception:
            return False

    def mousePressEvent(self, event: Any) -> None:
        if self.document.doc is None or self._is_synthesized(event):
            return
        nx, ny = self._widget_to_norm(event.position())
        if event.button() == Qt.MouseButton.LeftButton:
            self.stampRequested.emit(nx, ny)
        elif event.button() == Qt.MouseButton.RightButton:
            self.deleteRequested.emit(nx, ny)

    def mouseMoveEvent(self, event: Any) -> None:
        if self.document.doc is not None:
            self.cursorMoved.emit(*self._widget_to_norm(event.position()))

    def tabletEvent(self, event: Any) -> None:
        """ペンタブレット入力。ペン先＝配置、消しゴム側＝削除。"""
        if self.document.doc is None:
            event.ignore()
            return
        pos = event.position()
        if event.type() == event.Type.TabletPress:
            nx, ny = self._widget_to_norm(pos)
            eraser = getattr(event.pointerType(), "name", "") == "Eraser"
            (self.deleteRequested if eraser else self.stampRequested).emit(nx, ny)
        elif event.type() == event.Type.TabletMove:
            self.cursorMoved.emit(*self._widget_to_norm(pos))
        event.accept()

    def hit_test_widget(self, nx: float, ny: float) -> Placement | None:
        x0, y0, x1, y1 = self.document.page_rect(self.page_index)
        return self.document.hit_test(self.page_index, x0 + nx * (x1 - x0), y0 + ny * (y1 - y0))


class MainWindow(QMainWindow):
    """スタンプパレット（左）＋ PDF キャンバス（中央）の PoC ウィンドウ。"""

    def __init__(self, catalog: StampCatalog, pdf_path: str | os.PathLike[str] | None = None):
        super().__init__()
        self.catalog = catalog
        self.document = AnnotationDocument(catalog)
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 860)

        self.canvas = PdfCanvas(self.document)
        self.canvas.stampRequested.connect(self.place_stamp)
        self.canvas.deleteRequested.connect(self.delete_stamp_at)
        self.canvas.cursorMoved.connect(self._show_coords)

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidgetResizable(False)
        self._scroll = scroll

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_palette())
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 1000])
        self.setCentralWidget(splitter)

        self._build_actions()
        self.statusBar().showMessage("スタンプを選び、図面上をクリックして配置します。")
        if pdf_path:
            self.open_pdf(str(pdf_path))

    # -- UI 構築 -----------------------------------------------------------
    def _build_palette(self) -> Any:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QLabel("<b>スタンプパレット</b>"))
        self.palette = QListWidget()
        for stamp in self.catalog:
            item = QListWidgetItem(f"{stamp.label}")
            swatch = QPixmap(14, 14)
            swatch.fill(QColor.fromRgbF(*stamp.color))
            item.setIcon(swatch)
            item.setData(Qt.ItemDataRole.UserRole, stamp.id)
            item.setToolTip(f"ID: {stamp.id} / 種別: {stamp.shape} / "
                            f"寸法: {stamp.size_mm[0]:g}×{stamp.size_mm[1]:g} mm")
            self.palette.addItem(item)
        self.palette.setCurrentRow(0)
        self.palette.currentItemChanged.connect(self._on_stamp_changed)
        layout.addWidget(self.palette, 1)

        layout.addWidget(QLabel("注記テキスト（空ならカタログ既定値）"))
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("例: 削除 / 要確認")
        layout.addWidget(self.text_edit)

        row = QHBoxLayout()
        row.addWidget(QLabel("倍率"))
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.2, 5.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(1.0)
        row.addWidget(self.scale_spin)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("出力"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("PDF注釈（非破壊・編集可）", "annotation")
        self.mode_combo.addItem("ベクトル描画（確定版）", "vector")
        row2.addWidget(self.mode_combo, 1)
        layout.addLayout(row2)

        self.info_label = QLabel("配置数: 0")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        layout.addWidget(QLabel("<small>左クリック: 配置 / 右クリック: 削除<br>"
                                "ペンタブ: ペン先=配置, 消しゴム=削除</small>"))
        return panel

    def _act(self, text: str, slot: Any, shortcut: str | None = None) -> Any:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        return action

    def _build_actions(self) -> None:
        toolbar = self.addToolBar("main")
        toolbar.setMovable(False)
        actions = [
            self._act("開く", self.open_pdf_dialog, "Ctrl+O"),
            self._act("別名保存", self.save_pdf_dialog, "Ctrl+S"),
            None,
            self._act("前ページ", lambda: self.change_page(-1), "Ctrl+["),
            self._act("次ページ", lambda: self.change_page(+1), "Ctrl+]"),
            None,
            self._act("縮小", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.25), "Ctrl+-"),
            self._act("拡大", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.25), "Ctrl++"),
            self._act("幅に合わせる", self.fit_width, "Ctrl+0"),
            None,
            self._act("元に戻す", self.undo, "Ctrl+Z"),
            self._act("ページ内を消去", self.clear_page),
            None,
            self._act("JSON読込", self.import_json_dialog),
            self._act("JSON書出", self.export_json_dialog),
        ]
        for action in actions:
            toolbar.addSeparator() if action is None else toolbar.addAction(action)

        file_menu = self.menuBar().addMenu("ファイル")
        for action in actions:
            if action is not None:
                file_menu.addAction(action)

    # -- 状態表示 ----------------------------------------------------------
    def _current_symbol_id(self) -> str | None:
        item = self.palette.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_stamp_changed(self, current: Any, _previous: Any = None) -> None:
        if current is None:
            return
        stamp = self.catalog.get(current.data(Qt.ItemDataRole.UserRole))
        if stamp:
            self.statusBar().showMessage(f"選択中: {stamp.label} [{stamp.id}]")

    def _show_coords(self, nx: float, ny: float) -> None:
        page = self.canvas.page_index
        x0, y0, x1, y1 = self.document.page_rect(page)
        mm_x, mm_y = (nx * (x1 - x0)) * PT_TO_MM, (ny * (y1 - y0)) * PT_TO_MM
        self.statusBar().showMessage(
            f"p{page + 1}/{self.document.page_count}  "
            f"比率 ({nx:.3f}, {ny:.3f})  用紙 ({mm_x:.1f}mm, {mm_y:.1f}mm)  "
            f"ズーム {self.canvas.zoom * 100:.0f}%"
        )

    def _refresh_info(self) -> None:
        total = len(self.document.placements)
        here = len(self.document.placements_on(self.canvas.page_index))
        self.info_label.setText(f"配置数: {total}（このページ: {here}）")
        self.canvas.refresh()

    # -- 操作 --------------------------------------------------------------
    def place_stamp(self, nx: float, ny: float) -> None:
        symbol_id = self._current_symbol_id()
        if self.document.doc is None or symbol_id is None:
            return
        text = self.text_edit.text().strip()
        placement = self.document.add_stamp(
            page=self.canvas.page_index,
            symbol_id=symbol_id,
            norm_x=nx, norm_y=ny,
            text=text or None,
            scale=self.scale_spin.value(),
        )
        self.canvas.selected = placement
        self._refresh_info()

    def delete_stamp_at(self, nx: float, ny: float) -> None:
        hit = self.canvas.hit_test_widget(nx, ny)
        if hit is not None:
            self.document.remove(hit)
            if self.canvas.selected is hit:
                self.canvas.selected = None
            self._refresh_info()

    def undo(self) -> None:
        if self.document.undo() is not None:
            self.canvas.selected = None
            self._refresh_info()

    def clear_page(self) -> None:
        removed = self.document.clear(self.canvas.page_index)
        self.canvas.selected = None
        self._refresh_info()
        self.statusBar().showMessage(f"{removed} 件を消去しました。")

    def change_page(self, delta: int) -> None:
        self.canvas.set_page(self.canvas.page_index + delta)
        self._refresh_info()

    def fit_width(self) -> None:
        self.canvas.fit_to_width(self._scroll.viewport().width())

    # -- ファイル操作 ------------------------------------------------------
    def open_pdf_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "PDF図面を開く", "", "PDF (*.pdf)")
        if path:
            self.open_pdf(path)

    def open_pdf(self, path: str) -> None:
        try:
            self.document.open(path)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"PDF を開けませんでした:\n{exc}")
            return
        self.canvas.set_page(0)
        self.fit_width()
        self._refresh_info()
        self.setWindowTitle(f"{APP_NAME} — {Path(path).name}")

    def save_pdf_dialog(self) -> None:
        if self.document.doc is None or self.document.path is None:
            QMessageBox.information(self, APP_NAME, "先に PDF を開いてください。")
            return
        suggested = str(self.document.path.with_name(self.document.path.stem + "_stamped.pdf"))
        path, _ = QFileDialog.getSaveFileName(self, "別名で保存", suggested, "PDF (*.pdf)")
        if not path:
            return
        try:
            out = save_pdf(self.document, path, mode=self.mode_combo.currentData())
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"保存に失敗しました:\n{exc}")
            return
        QMessageBox.information(
            self, APP_NAME,
            f"{len(self.document.placements)} 件のスタンプを書き出しました。\n{out}"
        )

    def import_json_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "アノテーションJSONを読み込む", "", "JSON (*.json)")
        if not path:
            return
        try:
            added = self.apply_json_annotations(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"JSON を適用できませんでした:\n{exc}")
            return
        self.statusBar().showMessage(f"JSON から {len(added)} 件を配置しました。")

    def export_json_dialog(self) -> None:
        base = self.document.path.with_suffix(".json") if self.document.path else Path("annotations.json")
        path, _ = QFileDialog.getSaveFileName(self, "アノテーションJSONを書き出す", str(base), "JSON (*.json)")
        if path:
            Path(path).write_text(self.document.to_json(), encoding="utf-8")
            self.statusBar().showMessage(f"JSON を書き出しました: {path}")

    # -- AI / JSON 連携 API ------------------------------------------------
    def apply_json_annotations(self, json_data: Any, replace: bool = False) -> list[Placement]:
        """AI などが生成した構造化 JSON を受け取り、一括配置して再描画する。"""
        added = self.document.apply_json_annotations(json_data, replace=replace)
        if added:
            self.canvas.set_page(added[-1].page)
        self._refresh_info()
        return added


# =============================================================================
# 7. エントリポイント（GUI / ヘッドレス / 自己テスト）
# =============================================================================

# 組込み CJK フォントで字形が出ない記号の代替（PDF ページに直接描く文字にのみ使う）。
# 注釈の本文や GUI のパレット表示はシステムフォントで描かれるため置換しない。
PDF_GLYPH_FALLBACK = {"\u2716": "\u00d7", "\u2715": "\u00d7", "\u2714": "\u2713"}


def pdf_safe_text(text: str) -> str:
    """PDF へ直接描画する文字列から、組込みフォントに字形が無い記号を置き換える。"""
    return "".join(PDF_GLYPH_FALLBACK.get(ch, ch) for ch in text)


def draw_pdf_text(page: Any, rect: Any, text: str, *, fontname: str = "japan",
                  fontsize: float = 10.0, color: RGB = (0.15, 0.15, 0.15),
                  align: int = 0) -> None:
    """ページに文字を描く。枠に収まらない場合は無言で消えるため例外にする。

    insert_textbox() は入り切らないと負値を返して何も描かない。プレビュー用の
    見出しが黙って消えるのを防ぐため、ここで必ず検出する。
    """
    overflow = page.insert_textbox(rect, pdf_safe_text(text), fontname=fontname,
                                   fontsize=fontsize, color=color, align=align)
    if overflow < 0:
        raise RuntimeError(f"テキストが枠に収まりません（不足 {-overflow:.1f}pt）: {text!r}")


def make_sample_drawing(path: str | os.PathLike[str]) -> Path:
    """PDF が手元に無いときの動作確認用に、A3 横のダミー図面を作る。"""
    out = Path(path)
    doc = fitz.open()
    page = doc.new_page(width=1190.55, height=841.89)        # A3 横 (420×297mm)
    shape = page.new_shape()
    r = page.rect + (20, 20, -20, -20)
    shape.draw_rect(r)
    for i in range(1, 10):                                   # 通り芯のような格子
        x = r.x0 + (r.x1 - r.x0) * i / 10
        shape.draw_line((x, r.y0), (x, r.y1))
    for i in range(1, 7):
        y = r.y0 + (r.y1 - r.y0) * i / 7
        shape.draw_line((r.x0, y), (r.x1, y))
    shape.draw_rect(fitz.Rect(r.x1 - 260, r.y1 - 110, r.x1, r.y1))   # 表題欄
    shape.finish(color=(0.35, 0.35, 0.35), width=0.7)
    shape.commit()
    # 組込み CJK フォントは ASCII も全角で描くため、日本語行と ASCII 行で font を分ける
    draw_pdf_text(page, fitz.Rect(r.x1 - 250, r.y1 - 98, r.x1 - 10, r.y1 - 74),
                  "サンプル図面", fontsize=13, color=(0.2, 0.2, 0.2))
    draw_pdf_text(page, fitz.Rect(r.x1 - 250, r.y1 - 70, r.x1 - 10, r.y1 - 14),
                  "PDF Stamp Annotator (PoC)\nA3 landscape  420 x 297 mm",
                  fontname="helv", fontsize=10, color=(0.35, 0.35, 0.35))
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    doc.close()
    return out


SAMPLE_ANNOTATIONS: list[dict[str, Any]] = [
    {"page": 0, "symbol_id": "STAMP_X", "norm_x": 0.5, "norm_y": 0.3, "text": "削除"},
    {"page": 0, "symbol_id": "STAMP_RECT", "norm_x": 0.2, "norm_y": 0.4, "text": "要確認"},
    {"page": 0, "symbol_id": "STAMP_ARROW", "norm_x": 0.72, "norm_y": 0.55, "text": "配管ルート変更"},
    {"page": 0, "symbol_id": "STAMP_CIRCLE", "norm_x": 0.35, "norm_y": 0.68, "text": "弁番号"},
    {"page": 0, "symbol_id": "STAMP_CLOUD", "norm_x": 0.6, "norm_y": 0.2, "text": "改訂A"},
    {"page": 0, "symbol_id": "STAMP_CHECK", "norm_x": 0.15, "norm_y": 0.85, "text": "要確認"},
]


def render_pdf_to_png(pdf_path: str | os.PathLike[str],
                      out_pattern: str | os.PathLike[str],
                      dpi: int = 200) -> list[Path]:
    """PDF の各ページを PNG 画像にする（注釈を含めてレンダリングする）。

    out_pattern に "{page}" があればページ番号（1 始まり）に置換し、
    無ければ 2 ページ目以降に "_page2" のような接尾辞を付ける。
    """
    zoom = dpi / 72.0
    doc = fitz.open(pdf_path)
    written: list[Path] = []
    try:
        for index in range(doc.page_count):
            pattern = str(out_pattern)
            if "{page}" in pattern:
                target = Path(pattern.format(page=index + 1))
            else:
                target = Path(pattern)
                if index:
                    target = target.with_name(f"{target.stem}_page{index + 1}{target.suffix}")
            target.parent.mkdir(parents=True, exist_ok=True)
            # annots=True で PDF 標準注釈の外観も含めて焼き込む
            doc[index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False,
                                  annots=True).save(target)
            written.append(target)
    finally:
        doc.close()
    return written


def make_catalog_sheet(catalog: StampCatalog, path: str | os.PathLike[str],
                       columns: int = 3) -> tuple[Path, list[dict[str, Any]]]:
    """カタログ全種を並べる下敷き図面と、その各セル中央に置く配置 JSON を作る。

    プレビュー専用の特別扱いはしない。戻り値の JSON をそのまま
    apply_json_annotations() → save_pdf() に流すので、
    出来上がる画像は通常の配置パイプラインの実物になる。
    """
    rows = math.ceil(len(catalog) / columns)
    out = Path(path)
    doc = fitz.open()
    page = doc.new_page(width=1190.55, height=841.89)            # A3 横
    margin, header = 28.0, 76.0
    grid = fitz.Rect(margin, header, page.rect.x1 - margin, page.rect.y1 - margin)
    cell_w = (grid.x1 - grid.x0) / columns
    cell_h = (grid.y1 - grid.y0) / rows

    shape = page.new_shape()
    shape.draw_rect(page.rect + (12, 12, -12, -12))
    shape.finish(color=(0.35, 0.35, 0.35), width=0.8)
    shape.commit()

    annotations: list[dict[str, Any]] = []
    for i, stamp in enumerate(catalog):
        col, row = i % columns, i // columns
        cell = fitz.Rect(grid.x0 + col * cell_w, grid.y0 + row * cell_h,
                         grid.x0 + (col + 1) * cell_w, grid.y0 + (row + 1) * cell_h)
        cell_shape = page.new_shape()
        cell_shape.draw_rect(cell + (6, 6, -6, -6))
        cell_shape.finish(color=(0.78, 0.78, 0.78), width=0.6, dashes="[3 3] 0")
        cell_shape.commit()
        # 組込み CJK フォントは ASCII も全角で描くため、日本語行と ASCII 行で font を分ける
        draw_pdf_text(page, fitz.Rect(cell.x0 + 14, cell.y0 + 10, cell.x1 - 14, cell.y0 + 32),
                      f"{i + 1}. {stamp.label}", fontsize=11)
        draw_pdf_text(page, fitz.Rect(cell.x0 + 14, cell.y0 + 34, cell.x1 - 14, cell.y0 + 54),
                      f"id={stamp.id}  /  shape={stamp.shape}  /  "
                      f"{stamp.size_mm[0]:g} x {stamp.size_mm[1]:g} mm",
                      fontname="helv", fontsize=9, color=(0.42, 0.42, 0.42))
        center = fitz.Point((cell.x0 + cell.x1) / 2, cell.y0 + cell_h * 0.55)
        annotations.append({
            "page": 0,
            "symbol_id": stamp.id,
            "norm_x": center.x / page.rect.width,
            "norm_y": center.y / page.rect.height,
        })

    draw_pdf_text(page, fitz.Rect(margin, 16, page.rect.x1 - margin, 46),
                  f"スタンプカタログ プレビュー（全 {len(catalog)} 種）",
                  fontsize=16, color=(0.1, 0.1, 0.1))
    draw_pdf_text(page, fitz.Rect(margin, 48, page.rect.x1 - margin, 70),
                  "stamp_catalog.json  /  A3 landscape 420 x 297 mm  /  "
                  "PDF standard annotations",
                  fontname="helv", fontsize=10, color=(0.42, 0.42, 0.42))
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    doc.close()
    return out, annotations


def run_preview(args: argparse.Namespace) -> int:
    """iPad などで目視確認するためのプレビュー PNG 一式を書き出す。"""
    out_dir = Path(args.out_dir)
    dpi = args.dpi
    catalog = StampCatalog.load(args.catalog)

    # 1) サンプル図面にスタンプを配置した PDF → ページごとの PNG
    sample = (Path(args.input) if args.input
              else make_sample_drawing(out_dir / "sample_drawing.pdf"))
    document = AnnotationDocument(catalog, sample)
    data: Any = Path(args.annotations) if args.annotations else SAMPLE_ANNOTATIONS
    document.apply_json_annotations(data)
    stamped = save_pdf(document, out_dir / "stamped.pdf", mode=args.mode)
    pages = render_pdf_to_png(stamped, out_dir / "preview_stamped_page{page}.png", dpi)
    for png in pages:
        print(f"[preview] {png}  ({dpi}dpi)")
    document.close()

    # 2) カタログ全種を並べた一覧プレビュー
    sheet, annotations = make_catalog_sheet(catalog, out_dir / "catalog_sheet.pdf")
    sheet_doc = AnnotationDocument(catalog, sheet)
    sheet_doc.apply_json_annotations(annotations)
    sheet_pdf = save_pdf(sheet_doc, out_dir / "stamp_catalog_preview.pdf", mode=args.mode)
    for png in render_pdf_to_png(sheet_pdf, out_dir / "stamp_catalog_preview.png", dpi):
        print(f"[preview] {png}  ({dpi}dpi, {len(catalog)} 種)")
    sheet_doc.close()
    return 0


def run_batch(args: argparse.Namespace) -> int:
    """GUI を使わず、JSON からスタンプを一括配置して PDF を書き出す。"""
    catalog = StampCatalog.load(args.catalog)
    document = AnnotationDocument(catalog, args.input)
    data: Any = SAMPLE_ANNOTATIONS if args.annotations is None else Path(args.annotations)
    added = document.apply_json_annotations(data)
    out = save_pdf(document, args.output, mode=args.mode, exporter=args.exporter)
    print(f"[batch] {args.input} + {len(added)} stamps -> {out} (mode={args.mode})")
    document.close()
    return 0


def run_selftest(args: argparse.Namespace) -> int:
    """サンプル図面を生成し、仕様例の JSON を適用して両モードで書き出す。"""
    out_path = Path(args.output or "stamped_sample.pdf")
    sample = make_sample_drawing(out_path.with_name("sample_drawing.pdf"))
    catalog = StampCatalog.load(args.catalog)
    document = AnnotationDocument(catalog, sample)

    print(f"[selftest] カタログ: {len(catalog)} 種 / サンプル: {sample} "
          f"({document.page_rect(0)[2]:.1f} x {document.page_rect(0)[3]:.1f} pt)")
    added = document.apply_json_annotations(SAMPLE_ANNOTATIONS)
    print(f"[selftest] JSON 一括配置: {len(added)} 件")

    for mode in ("annotation", "vector"):
        target = out_path.with_name(f"{out_path.stem}_{mode}{out_path.suffix}")
        save_pdf(document, target, mode=mode)
        check = fitz.open(target)
        n_annots = sum(len(list(check[i].annots())) for i in range(check.page_count))
        print(f"[selftest] {mode:10s} -> {target}  注釈数={n_annots}")
        check.close()

    round_trip = json.loads(document.to_json())["annotations"]
    assert len(round_trip) == len(SAMPLE_ANNOTATIONS), "JSON 往復で件数が一致しません"
    print("[selftest] JSON 往復 OK / 元 PDF は無変更（別名保存のみ）")
    document.close()
    return 0


def run_gui(args: argparse.Namespace) -> int:
    if not HAS_QT:
        print("PySide6 が見つかりません。`pip install -r requirements.txt` を実行してください。",
              file=sys.stderr)
        print(f"  詳細: {QT_IMPORT_ERROR}", file=sys.stderr)
        return 2
    catalog = StampCatalog.load(args.catalog)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    window = MainWindow(catalog, args.pdf)
    window.show()
    return app.exec()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PDF図面向け インタラクティブ スタンプ配置アプリ (PoC)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("使い方")[-1],
    )
    parser.add_argument("pdf", nargs="?", help="起動時に開く PDF")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH),
                        help="スタンプカタログ JSON (既定: stamp_catalog.json)")
    parser.add_argument("--batch", action="store_true", help="GUI を使わず JSON から一括処理")
    parser.add_argument("--selftest", action="store_true", help="サンプル図面で一連の動作を確認")
    parser.add_argument("--preview", action="store_true",
                        help="目視確認用の PNG（配置結果とスタンプ一覧）を書き出す")
    parser.add_argument("--out-dir", default="out", help="--preview の出力先 (既定: out)")
    parser.add_argument("--dpi", type=int, default=200, help="--preview の解像度 (既定: 200)")
    parser.add_argument("--input", help="--batch の入力 PDF")
    parser.add_argument("--annotations", help="--batch のアノテーション JSON")
    parser.add_argument("--output", help="出力 PDF")
    parser.add_argument("--mode", default="annotation", choices=("annotation", "vector"),
                        help="annotation: PDF注釈 / vector: ベクトル描画")
    parser.add_argument("--exporter", default="pymupdf", choices=sorted(EXPORTERS),
                        help="出力モジュール（将来 docuworks を追加）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            return run_selftest(args)
        if args.preview:
            return run_preview(args)
        if args.batch:
            if not args.input or not args.output:
                parser.error("--batch には --input と --output が必要です")
            return run_batch(args)
        return run_gui(args)
    except Exception as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
