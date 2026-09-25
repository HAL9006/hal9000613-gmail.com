#!/usr/bin/env python3
"""TOS-EXEC-KD2-001: KD再設計のための一次データ収集（読み取り専用）.

使い方:
    python kd_inventory.py --root <TrinityOSのパス>
    （--out 省略時は <root>/_analysis/kd_redesign_20260925/ に出力）

- 対象ファイルは一切変更しない（open は読み取りのみ）。
- ネットワーク通信は行わない（標準ライブラリ + PyYAML のみ）。
- field_stats.csv / drift_report.md / inventory.csv / parse_errors.csv /
  spec_lineage.md は同一入力に対して同一出力（時刻・乱数を含めない）。
  実行時刻は run_meta.json にのみ書く。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fnmatch
import hashlib
import io
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML が必要です: pip install pyyaml （ローカルで実行）")

SCRIPT_VERSION = "1.0.0"
OUT_REL = Path("_analysis") / "kd_redesign_20260925"

# --- 対象パターン（ファイル名に対して大文字小文字無視で照合） ---------------
NAME_PATTERNS = [
    ("KD_yaml", ["KD_*.yaml", "KD_*.yml"]),
    ("Consolidated_KD", ["Consolidated_KD*"]),
    ("Master_Index", ["Master_Index*"]),
    ("SPEC_Knowledge_Distillate", ["SPEC_Knowledge_Distillate*"]),
    ("KD-DOC", ["*KD-DOC*"]),
    ("SPEC_UCA_ALS", ["SPEC_UCA_ALS*"]),
    ("圧縮言語カタログ", ["圧縮言語カタログ*"]),
]
# CRL・SMCL・SCF・ICS 関連仕様: ファイル名を英数字以外で区切ったトークンに一致
PROTO_TOKENS = ["CRL", "SMCL", "SCF", "ICS"]
TEXT_EXT = {".yaml", ".yml", ".md", ".txt", ".json", ".markdown"}

# KD 仕様フィールド（パケット記載の8項目）と既知カテゴリ
SPEC_FIELDS = ["id", "type", "status", "title", "content", "source_ref", "why", "tags"]
KNOWN_CATEGORIES = ["ARCH", "TECH", "OPS", "PROTO", "INS", "WARN", "SESS"]
PROFILE_KEY_RE = re.compile(r"(profile|schema|format|spec|version|kd_version|variant)", re.I)
WHY_BUCKETS = [(1, 20), (21, 50), (51, 100), (101, 200), (201, 500), (501, None)]


# ---------------------------------------------------------------------------
# 基本ユーティリティ
# ---------------------------------------------------------------------------
def rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(data: bytes) -> tuple[str | None, str]:
    for enc in ("utf-8-sig", "cp932"):
        try:
            label = enc if enc != "utf-8-sig" else ("utf-8-bom" if data.startswith(b"\xef\xbb\xbf") else "utf-8")
            return data.decode(enc), label
        except UnicodeDecodeError:
            continue
    return None, "unknown"


def estimate_tokens(text: str | None, size: int) -> int:
    """推定token数（ヒューリスティック・ローカル計算のみ）.

    ASCII 文字: 4文字=1token / 非ASCII 文字: 1文字=1token。
    デコード不能ファイルは bytes/4。
    """
    if text is None:
        return (size + 3) // 4
    ascii_n = sum(1 for c in text if ord(c) < 128)
    return (ascii_n + 3) // 4 + (len(text) - ascii_n)


def match_patterns(name: str) -> list[str]:
    low = name.lower()
    hits = []
    for label, pats in NAME_PATTERNS:
        if any(fnmatch.fnmatchcase(low, p.lower()) for p in pats):
            hits.append(label)
    stem_tokens = {t.upper() for t in re.split(r"[^A-Za-z0-9]+", Path(name).stem) if t}
    for tok in PROTO_TOKENS:
        if tok in stem_tokens:
            hits.append(tok)
    return hits


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


# ---------------------------------------------------------------------------
# YAML ローダ: 全スカラを文字列で保持・未知タグも保持・重複キーを記録
# ---------------------------------------------------------------------------
class KDLoader(yaml.BaseLoader):
    pass


def _make_loader(dups: list, tags: Counter):
    class _L(KDLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        seen = {}
        for knode, _ in node.value:
            k = loader.construct_object(knode, deep=deep)
            if isinstance(k, str) and k in seen:
                dups.append((k, knode.start_mark.line + 1))
            seen[k] = True
        return yaml.BaseLoader.construct_mapping(loader, node, deep=deep)

    def unknown_tag(loader, suffix, node):
        if not node.tag.startswith("tag:yaml.org,2002:"):
            tags[node.tag] += 1
        if isinstance(node, yaml.MappingNode):
            return construct_mapping(loader, node, deep=True)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node, deep=True)
        return loader.construct_scalar(node)

    _L.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
    _L.add_multi_constructor("", unknown_tag)
    return _L


FENCE_RE = re.compile(r"^```(?:ya?ml)\s*\n(.*?)^```", re.M | re.S)


def parse_yaml_text(text: str, is_md: bool):
    """戻り値: (docs, mode, dups, tags, error)"""
    dups: list = []
    tags: Counter = Counter()
    Loader = _make_loader(dups, tags)
    if is_md:
        chunks = FENCE_RE.findall(text)
        mode = f"md_fenced_yaml({len(chunks)})"
        if not chunks:
            return [], mode, dups, tags, None
    else:
        chunks = [text]
        mode = "yaml"
    docs = []
    for i, chunk in enumerate(chunks):
        try:
            docs.extend(d for d in yaml.load_all(chunk, Loader=Loader) if d is not None)
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            loc = f"line {mark.line + 1} col {mark.column + 1}" if mark else "line ?"
            where = f"fence#{i + 1} " if is_md else ""
            msg = f"{where}{loc}: {getattr(e, 'problem', None) or str(e).splitlines()[0]}"
            return docs, mode, dups, tags, (type(e).__name__, msg)
    return docs, mode, dups, tags, None


# ---------------------------------------------------------------------------
# KD ブロック抽出
# ---------------------------------------------------------------------------
def is_block(d: dict, in_list: bool) -> bool:
    """ブロック判定: 'id' キーを持つ mapping、または
    リスト要素で仕様フィールドを2つ以上持つ mapping。"""
    keys = set(d.keys())
    if "id" in keys:
        return True
    return in_list and len(keys & set(SPEC_FIELDS)) >= 2


def collect_blocks(node, path="$", in_list=False, out=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        if is_block(node, in_list):
            out.append((path, node))
            return out  # ブロック内部の入れ子はブロックとして数えない
        for k, v in node.items():
            collect_blocks(v, f"{path}.{k}", False, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            collect_blocks(v, f"{path}[{i}]", True, out)
    return out


def is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() in ("", "~", "null", "Null", "NULL")
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def text_len(v) -> int:
    """値に含まれる文字列スカラの総文字数（再帰）."""
    if isinstance(v, str):
        return len(v)
    if isinstance(v, dict):
        return sum(text_len(k) + text_len(x) for k, x in v.items())
    if isinstance(v, list):
        return sum(text_len(x) for x in v)
    return 0


def scalar_str(v) -> str | None:
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return None


ID_TOKEN_RE = re.compile(r"[A-Za-z]+")


def id_tokens(block_id: str) -> list[str]:
    return [t.upper() for t in ID_TOKEN_RE.findall(block_id)]


def pct(n, d):
    return f"{(n / d):.4f}" if d else ""


def quantiles(vals: list[int]) -> dict:
    if not vals:
        return {}
    s = sorted(vals)
    q = statistics.quantiles(s, n=4, method="inclusive") if len(s) > 1 else [s[0]] * 3
    return {
        "n": len(s), "min": s[0], "p25": f"{q[0]:.1f}", "median": f"{q[1]:.1f}",
        "p75": f"{q[2]:.1f}", "max": s[-1], "mean": f"{statistics.fmean(s):.2f}",
    }


# ---------------------------------------------------------------------------
# スペック系譜
# ---------------------------------------------------------------------------
DATE_RES = [
    re.compile(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"),
]
VER_RE = re.compile(r"(?<![A-Za-z])[vV](\d+(?:\.\d+)*)")
CONTENT_DATE_RE = re.compile(
    r"^\s*(?:date|created|updated|last_updated|作成日|更新日)\s*[:：]\s*['\"]?"
    r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", re.M | re.I)
CONTENT_VER_RE = re.compile(r"^\s*(?:version|ver|版)\s*[:：]\s*['\"]?v?([0-9][0-9A-Za-z._-]*)", re.M | re.I)


def find_date(s: str):
    for r in DATE_RES:
        m = r.search(s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def family_of(name: str) -> str:
    stem = Path(name).stem
    s = DATE_RES[0].sub("", stem)
    s = VER_RE.sub("", s)
    s = re.sub(r"[-_. ]+", "_", s).strip("_")
    return s or stem


def ver_key(v: str | None):
    if not v:
        return ()
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[._-]", v))


def spec_items(text: str | None, ext: str) -> tuple[list[str], str]:
    """比較用の「項目」を抽出。YAML: 全キーパス / その他: 見出し行."""
    if text is None:
        return [], "undecodable"
    if ext in (".yaml", ".yml"):
        docs, _, _, _, err = parse_yaml_text(text, False)
        if err is None:
            paths: set[str] = set()

            def walk(n, p):
                if isinstance(n, dict):
                    for k, v in n.items():
                        kp = f"{p}.{k}" if p else str(k)
                        paths.add(kp)
                        walk(v, kp)
                elif isinstance(n, list):
                    for v in n:
                        walk(v, f"{p}[]")

            for d in docs:
                walk(d, "")
            return sorted(paths), "yaml_keypaths"
    heads = []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            heads.append(f"{m.group(1)} {m.group(2)}")
    return heads, "md_headings"


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="TrinityOS ルートディレクトリ")
    ap.add_argument("--out", help="出力先（既定: <root>/_analysis/kd_redesign_20260925）")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    if not root.is_dir():
        sys.exit(f"root が見つかりません: {root}")
    out = Path(a.out).resolve() if a.out else root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)

    # ---- 1. README_AI.md / _state/ -------------------------------------
    state_lines = ["# state_snapshot（README_AI.md と _state/ の読み取り記録）", ""]
    readme_ai = root / "README_AI.md"
    if readme_ai.is_file():
        b = readme_ai.read_bytes()
        t, _ = decode(b)
        state_lines += [f"- README_AI.md: sha256={sha256(b)} size={len(b)}", "",
                        "## README_AI.md 本文", "", "```", (t or "(デコード不能)").rstrip(), "```", ""]
    else:
        state_lines += ["- README_AI.md: 不在", ""]
    state_dir = root / "_state"
    state_lines.append("## _state/ ファイル一覧")
    state_lines.append("")
    if state_dir.is_dir():
        for p in sorted(state_dir.rglob("*")):
            if p.is_file():
                b = p.read_bytes()
                mt = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
                state_lines.append(f"- {rel(p, root)} size={len(b)} sha256={sha256(b)[:16]} mtime={mt}")
        state_lines += ["", "## _state/ 本文（テキストのみ）", ""]
        for p in sorted(state_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in TEXT_EXT:
                t, _ = decode(p.read_bytes())
                state_lines += [f"### {rel(p, root)}", "", "```", (t or "(デコード不能)").rstrip(), "```", ""]
    else:
        state_lines.append("- _state/: 不在")
    (out / "state_snapshot.md").write_text("\n".join(state_lines) + "\n", encoding="utf-8")

    # ---- 2. inventory ----------------------------------------------------
    targets = []  # (relpath, Path, labels)
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d != ".git" and (dp / d).resolve() != out)
        for fn in sorted(filenames):
            labels = match_patterns(fn)
            if labels:
                p = dp / fn
                targets.append((rel(p, root), p, labels))
    targets.sort(key=lambda x: x[0])

    inv_rows = []
    texts: dict[str, str | None] = {}
    meta: dict[str, dict] = {}
    for rp, p, labels in targets:
        b = p.read_bytes()
        t, enc = decode(b)
        texts[rp] = t
        st = p.stat()
        mt = dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
        meta[rp] = {"mtime": mt, "labels": labels, "ext": p.suffix.lower(), "name": p.name}
        inv_rows.append([rp, len(b), sha256(b), mt, estimate_tokens(t, len(b)), "|".join(labels), enc])
    write_csv(out / "inventory.csv",
              ["path", "size", "sha256", "mtime", "est_tokens", "matched_patterns", "encoding"], inv_rows)

    # ---- 3/6. KD パース ---------------------------------------------------
    kd_files = [rp for rp, _, labels in targets
                if ({"KD_yaml", "Consolidated_KD"} & set(labels))
                and meta[rp]["ext"] in (".yaml", ".yml", ".md", ".markdown")]
    err_rows = []
    per_file = {}  # rp -> dict
    for rp in kd_files:
        t = texts[rp]
        if t is None:
            err_rows.append([rp, "error", "UnicodeDecodeError", "utf-8/cp932 でデコード不能"])
            continue
        docs, mode, dups, tags, err = parse_yaml_text(t, meta[rp]["ext"] in (".md", ".markdown"))
        for k, line in dups:
            err_rows.append([rp, "warning", "DuplicateKey", f"line {line}: key '{k}' 重複（後勝ちで読込）"])
        if err:
            err_rows.append([rp, "error", err[0], err[1]])
            continue
        blocks = []
        top_keys = Counter()
        for d in docs:
            if isinstance(d, dict):
                top_keys.update(str(k) for k in d.keys())
            blocks.extend(collect_blocks(d))
        if not blocks:
            err_rows.append([rp, "warning", "NoBlocks", f"mode={mode}: ブロック判定条件に一致する mapping なし"])
        per_file[rp] = {"docs": docs, "blocks": blocks, "mode": mode, "tags": tags, "top_keys": top_keys}
    err_rows.sort()
    write_csv(out / "parse_errors.csv", ["path", "severity", "error_type", "detail"], err_rows)

    # 集計
    all_blocks = [(rp, bp, b) for rp in sorted(per_file) for bp, b in per_file[rp]["blocks"]]
    N = len(all_blocks)
    fs = []  # section, key, value, count, ratio, note

    fs.append(["overview", "kd_files_targeted", "", len(kd_files), "", ""])
    fs.append(["overview", "kd_files_parsed", "", len(per_file), pct(len(per_file), len(kd_files)), ""])
    fs.append(["overview", "kd_files_failed", "", len(kd_files) - len(per_file), pct(len(kd_files) - len(per_file), len(kd_files)), ""])
    fs.append(["overview", "blocks_total", "", N, "", ""])
    bpf = [len(per_file[rp]["blocks"]) for rp in sorted(per_file)]
    fs.append(["overview", "blocks_per_file_mean", "", f"{statistics.fmean(bpf):.2f}" if bpf else "", "", "解析成功ファイル基準"])
    for k, v in quantiles(bpf).items():
        fs.append(["blocks_per_file", k, "", v, "", ""])
    blens = [text_len(b) for _, _, b in all_blocks]
    for k, v in quantiles(blens).items():
        fs.append(["block_chars", k, "", v, "", "ブロック内文字列スカラ（キー含む）の総文字数"])

    # フィールド使用率
    for f in SPEC_FIELDS:
        present = sum(1 for _, _, b in all_blocks if f in b)
        nonempty = sum(1 for _, _, b in all_blocks if f in b and not is_empty(b[f]))
        fs.append(["field_usage", f, "present", present, pct(present, N), ""])
        fs.append(["field_usage", f, "nonempty", nonempty, pct(nonempty, N), ""])

    # 分布: type / status / category フィールド / id トークン
    def dist(field):
        c = Counter()
        for _, _, b in all_blocks:
            if field not in b:
                c["(欠落)"] += 1
            else:
                s = scalar_str(b[field])
                c[s if s is not None else ("(空)" if is_empty(b[field]) else "(非スカラ)")] += 1
        return c

    for field in ("type", "status", "category"):
        for val, n in sorted(dist(field).items(), key=lambda x: (-x[1], x[0])):
            fs.append([f"dist_{field}", field, val, n, pct(n, N), ""])
    idtok = Counter()
    idtok_known = Counter()
    for _, _, b in all_blocks:
        s = scalar_str(b.get("id"))
        toks = set(id_tokens(s)) if s else set()
        for t in toks:
            idtok[t] += 1
        hit = sorted(toks & set(KNOWN_CATEGORIES))
        idtok_known["|".join(hit) if hit else "(既知カテゴリ語なし)"] += 1
    for val, n in sorted(idtok_known.items(), key=lambda x: (-x[1], x[0])):
        fs.append(["dist_id_known_category_tokens", "id", val, n, pct(n, N),
                   "id 内の英字トークンが既知カテゴリ語に一致したもの（完全一致のみ）"])
    for val, n in sorted(idtok.items(), key=lambda x: (-x[1], x[0])):
        fs.append(["dist_id_alpha_tokens", "id", val, n, pct(n, N), "id 内英字トークン（ブロック単位で重複除去）"])

    # why
    why_missing = sum(1 for _, _, b in all_blocks if "why" not in b)
    why_empty = sum(1 for _, _, b in all_blocks if "why" in b and is_empty(b["why"]))
    fs.append(["why", "missing_key", "", why_missing, pct(why_missing, N), ""])
    fs.append(["why", "empty_value", "", why_empty, pct(why_empty, N), ""])
    fs.append(["why", "missing_or_empty", "", why_missing + why_empty, pct(why_missing + why_empty, N), ""])
    wl = [text_len(b["why"]) for _, _, b in all_blocks if "why" in b and not is_empty(b["why"])]
    for k, v in quantiles(wl).items():
        fs.append(["why_chars", k, "", v, "", "非空 why のみ"])
    for lo, hi in WHY_BUCKETS:
        n = sum(1 for x in wl if x >= lo and (hi is None or x <= hi))
        label = f"{lo}-{hi}" if hi is not None else f"{lo}+"
        fs.append(["why_chars_hist", label, "", n, pct(n, len(wl)), "非空 why のみ"])

    # ファイル別
    for rp in sorted(per_file):
        blocks = per_file[rp]["blocks"]
        n = len(blocks)
        fs.append(["per_file", rp, "blocks", n, "", per_file[rp]["mode"]])
        if n:
            fs.append(["per_file", rp, "block_chars_mean", f"{statistics.fmean(text_len(b) for _, b in blocks):.2f}", "", ""])
            e = sum(1 for _, b in blocks if "why" not in b or is_empty(b["why"]))
            fs.append(["per_file", rp, "why_missing_or_empty", e, pct(e, n), ""])

    write_csv(out / "field_stats.csv", ["section", "key", "value", "count", "ratio", "note"], fs)

    # ---- 4. drift_report ---------------------------------------------------
    dr = ["# drift_report", "",
          f"基準: 仕様フィールド = {', '.join(SPEC_FIELDS)} / 既知カテゴリ = {', '.join(KNOWN_CATEGORIES)}",
          "（出現ファイルと件数のみを記録）", ""]

    def section(title, counter_by_key: dict[str, Counter], note=""):
        dr.append(f"## {title}")
        dr.append("")
        if note:
            dr.extend([note, ""])
        if not counter_by_key:
            dr.extend(["該当なし", ""])
            return
        dr.extend(["| 項目 | 総件数 | ファイル数 | 出現ファイル(件数) |", "|---|---:|---:|---|"])
        for key in sorted(counter_by_key, key=lambda k: (-sum(counter_by_key[k].values()), k)):
            c = counter_by_key[key]
            files = "<br>".join(f"{f} ({n})" for f, n in sorted(c.items()))
            dr.append(f"| `{md_esc(key)}` | {sum(c.values())} | {len(c)} | {md_esc(files)} |")
        dr.append("")

    extra_fields: dict[str, Counter] = defaultdict(Counter)
    for rp, _, b in all_blocks:
        for k in b.keys():
            if str(k) not in SPEC_FIELDS:
                extra_fields[str(k)][rp] += 1
    section("仕様外フィールド（ブロック直下のキー）", extra_fields)

    cat_vals: dict[str, Counter] = defaultdict(Counter)
    for rp, _, b in all_blocks:
        for f in ("category", "type"):
            s = scalar_str(b.get(f))
            if s is not None and s.upper() not in KNOWN_CATEGORIES:
                cat_vals[f"{f}={s}"][rp] += 1
    section("独自カテゴリ値（category / type フィールド値が既知カテゴリ語と完全一致しないもの）", cat_vals,
            "type の値がカテゴリを表すかどうかは判定していない（両フィールドとも機械的に列挙）。")

    idt: dict[str, Counter] = defaultdict(Counter)
    for rp, _, b in all_blocks:
        s = scalar_str(b.get("id"))
        if s:
            m = re.match(r"^([A-Za-z]+(?:[-_][A-Za-z]+)*)", s)
            if m:
                idt[m.group(1)][rp] += 1
    section("id 英字プレフィックス（数字より前の英字部）", idt)

    tk: dict[str, Counter] = defaultdict(Counter)
    prof: dict[str, Counter] = defaultdict(Counter)
    for rp in sorted(per_file):
        for k in per_file[rp]["top_keys"]:
            tk[k][rp] += per_file[rp]["top_keys"][k]
        for d in per_file[rp]["docs"]:
            if isinstance(d, dict):
                for k, v in d.items():
                    if PROFILE_KEY_RE.search(str(k)):
                        s = scalar_str(v)
                        prof[f"{k}={s if s is not None else '(非スカラ/空)'}"][rp] += 1
                    if isinstance(v, dict):
                        for k2, v2 in v.items():
                            if PROFILE_KEY_RE.search(str(k2)):
                                s = scalar_str(v2)
                                prof[f"{k}.{k2}={s if s is not None else '(非スカラ/空)'}"][rp] += 1
    section("ファイル最上位キー", tk)
    section("派生プロファイル候補（profile/schema/format/spec/version/variant を含むキーの値）", prof,
            f"抽出条件: 最上位および2階層目のキー名が正規表現 `{PROFILE_KEY_RE.pattern}` に一致。")

    tagc: dict[str, Counter] = defaultdict(Counter)
    for rp in sorted(per_file):
        for tg, n in per_file[rp]["tags"].items():
            tagc[tg][rp] += n
    section("YAML 独自タグ（!xxx）", tagc)

    modes: dict[str, Counter] = defaultdict(Counter)
    for rp in sorted(per_file):
        modes[per_file[rp]["mode"].split("(")[0]][rp] += 1
    section("解析モード（yaml ファイル / md 内 ```yaml フェンス）", modes)
    (out / "drift_report.md").write_text("\n".join(dr) + "\n", encoding="utf-8")

    # ---- 5. spec_lineage ---------------------------------------------------
    spec_labels = {"SPEC_Knowledge_Distillate", "KD-DOC", "SPEC_UCA_ALS", "圧縮言語カタログ", *PROTO_TOKENS}
    fams: dict[str, list] = defaultdict(list)
    for rp, p, labels in targets:
        if not (spec_labels & set(labels)):
            continue
        name = meta[rp]["name"]
        t = texts[rp]
        d_name = find_date(name)
        m_c = CONTENT_DATE_RE.search(t) if t else None
        d_content = f"{m_c.group(1)}-{int(m_c.group(2)):02d}-{int(m_c.group(3)):02d}" if m_c else None
        vm = VER_RE.search(Path(name).stem)
        v_name = vm.group(1) if vm else None
        vc = CONTENT_VER_RE.search(t) if t else None
        v_content = vc.group(1) if vc else None
        if d_name:
            date, dsrc = d_name, "filename"
        elif d_content:
            date, dsrc = d_content, "content"
        else:
            date, dsrc = meta[rp]["mtime"][:10], "mtime"
        fams[family_of(name)].append({
            "path": rp, "date": date, "date_src": dsrc, "ver": v_name or v_content,
            "ver_src": "filename" if v_name else ("content" if v_content else "不明"),
            "labels": labels, "text": t, "ext": meta[rp]["ext"]})

    sl = ["# spec_lineage", "",
          "並び順: 日付（filename > content(date/created/updated 行) > mtime の優先で採用）→ 版番号 → パス。",
          "項目: YAML はキーパス、それ以外は Markdown 見出し行。家系(family)はファイル名から日付・vX.Y を除いた文字列で機械的にまとめたもの。",
          "日付ソースが mtime のものはコピー等で変わりうる。", ""]
    if not fams:
        sl += ["該当なし", ""]
    for fam in sorted(fams):
        vs = sorted(fams[fam], key=lambda x: (x["date"], ver_key(x["ver"]), x["path"]))
        sl += [f"## {fam}", "", "| # | 日付 | 日付ソース | 版 | 版ソース | パス |", "|---:|---|---|---|---|---|"]
        for i, v in enumerate(vs, 1):
            sl.append(f"| {i} | {v['date']} | {v['date_src']} | {v['ver'] or '不明'} | {v['ver_src']} | {md_esc(v['path'])} |")
        sl.append("")
        prev = None
        for i, v in enumerate(vs, 1):
            items, kind = spec_items(v["text"], v["ext"])
            sl.append(f"### {i}. {md_esc(v['path'])}  （項目抽出: {kind}, {len(items)}件）")
            sl.append("")
            if prev is None:
                sl.append("- 初出版（比較対象なし）。項目一覧:")
                sl += [f"  - `{md_esc(x)}`" for x in items] or ["  - (なし)"]
            else:
                pitems, pkind = prev
                if pkind != kind:
                    sl.append(f"- 前版と項目抽出方式が異なる（{pkind} → {kind}）。差分は機械比較のまま記載。")
                ps, cs = set(pitems), set(items)
                add = [x for x in items if x not in ps]
                rem = [x for x in pitems if x not in cs]
                sl.append(f"- 追加 ({len(add)}):")
                sl += [f"  - `{md_esc(x)}`" for x in add] or ["  - (なし)"]
                sl.append(f"- 削除 ({len(rem)}):")
                sl += [f"  - `{md_esc(x)}`" for x in rem] or ["  - (なし)"]
            sl.append("")
            prev = (items, kind)
    (out / "spec_lineage.md").write_text("\n".join(sl) + "\n", encoding="utf-8")

    # ---- run_meta（唯一の非決定的出力） ----------------------------------
    (out / "run_meta.json").write_text(json.dumps({
        "script_version": SCRIPT_VERSION,
        "run_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "root": str(root), "out": str(out),
        "python": sys.version.split()[0], "pyyaml": yaml.__version__,
        "counts": {"inventory": len(inv_rows), "kd_files": len(kd_files), "kd_parsed": len(per_file),
                   "blocks": N, "parse_errors_rows": len(err_rows), "spec_families": len(fams)},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"done: {out}")
    print(f"  inventory={len(inv_rows)} kd_files={len(kd_files)} parsed={len(per_file)} "
          f"blocks={N} parse_errors_rows={len(err_rows)} spec_families={len(fams)}")
    return 0


def md_esc(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    sys.exit(main())
