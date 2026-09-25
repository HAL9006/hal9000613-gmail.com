#!/usr/bin/env python3
"""KD / TASK パケットのチェッカ（AI間通信仕様 v2.0 / v2.1 のチェックリストを実装）.

使い方:
    python check_packet.py --rules 2.0 packet.yaml [...]
    python check_packet.py --rules 2.1 packet.yaml [...]
    python check_packet.py --rules 2.1 --embedded example spec.yaml   # 仕様書内の例を検査

--rules 2.0 は原本 7節・14節の記載を**文字どおり**実装する。
  「欠けている」= キーが存在しない、と読む（値が空でもキーがあれば欠けていない）。
  14節 warning の主観語は、原本に列挙された語（適切・十分・高品質）と ambiguous_words の ng 句に限る。
--rules 2.1 は改訂案 v2.1 の 7節・14節を実装する。

標準ライブラリ + PyYAML のみ。ネットワーク通信なし。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

KD_META = ["kind", "kd", "id", "date", "from", "to", "purpose"]
BLOCK_REQ = ["id", "type", "status", "title", "content", "why", "sources"]
TASK_META = ["kind", "kd", "id", "date", "from", "to", "operation"]
TYPES = {"OBSERVATION", "INSIGHT", "DECISION", "RULE", "PROCEDURE", "WARNING", "DEFINITION", "QUESTION"}
STATUSES = {"CONFIRMED", "TENTATIVE", "SUPERSEDED", "DEPRECATED"}
BASES = {"OBSERVED", "DOCUMENT", "EXPERT", "DERIVED", "UNKNOWN"}
OPERATIONS = {"execute", "review", "research"}
AI_WORDS = re.compile(r"(AI|ChatGPT|Claude|Gemini|Copilot|GPT|UNKNOWN)", re.I)

# 2.0: 14節 warning に列挙された主観語と ambiguous_words の ng 句
SUBJ_20 = ["適切", "十分", "高品質"]
AMBIG_20 = ["適切に処理する", "必要に応じて", "品質を確保する", "最適化する", "確認する"]
# 2.1: 例示を追加（改訂案 14節）
SUBJ_21 = SUBJ_20 + ["正確", "わかりやすい", "問題ない"]
AMBIG_21 = AMBIG_20
MUTATE_WORDS = ["上書き", "削除", "書き換え", "置き換え", "修正して保存", "消す", "移動する", "リネーム"]

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
KD_ID_RE = re.compile(r"^KD-\d{8}-[a-z0-9-]{3,40}$")
TASK_ID_RE = re.compile(r"^TASK-\d{8}-[a-z0-9-]{3,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BID_RE = re.compile(r"^B\d{3,}$")
REF_RE = re.compile(r"^(?P<pid>(?:KD|TASK)-\d{8}-[a-z0-9-]+)#(?P<bid>[A-Za-z0-9]+)$")


# ---------------------------------------------------------------------------
# 読み込み: 重複キー・アンカー/エイリアス・タグを記録する
# ---------------------------------------------------------------------------
def load(text: str):
    """戻り値: (data, parse_error, dup_keys, anchors_or_tags)"""
    dups, marks = [], []
    try:
        for ev in yaml.parse(text):
            if isinstance(ev, yaml.AliasEvent):
                marks.append(f"alias *{ev.anchor} (line {ev.start_mark.line + 1})")
            elif getattr(ev, "anchor", None):
                marks.append(f"anchor &{ev.anchor} (line {ev.start_mark.line + 1})")
            # 明示タグ（!xxx / !!str など）があるときだけ event.tag が入る
            tag = getattr(ev, "tag", None)
            if tag and isinstance(ev, (yaml.ScalarEvent, yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                marks.append(f"tag {tag} (line {ev.start_mark.line + 1})")
    except yaml.YAMLError as e:
        return None, _err(e), dups, marks

    class L(yaml.SafeLoader):
        pass

    def cm(loader, node, deep=False):
        seen = set()
        for kn, _ in node.value:
            k = loader.construct_object(kn, deep=deep)
            if k in seen:
                dups.append(f"{k} (line {kn.start_mark.line + 1})")
            seen.add(k)
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    L.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, cm)
    try:
        return yaml.load(text, Loader=L), None, dups, marks
    except yaml.YAMLError as e:
        return None, _err(e), dups, marks


def _err(e):
    m = getattr(e, "problem_mark", None)
    return f"{type(e).__name__} line {m.line + 1 if m else '?'}: {getattr(e, 'problem', '') or e}"


def empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def text(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return "\n".join(text(x) for x in v)
    if isinstance(v, dict):
        return "\n".join(text(x) for x in v.values())
    return "" if v is None else str(v)


def walk_keys(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, k
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_keys(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------
# KD
# ---------------------------------------------------------------------------
def check_kd(d, rules: str, raw_len: int):
    E, W = [], []
    v21 = rules == "2.1"
    meta = d.get("meta") if isinstance(d, dict) else None
    meta = meta if isinstance(meta, dict) else {}

    def missing(obj, k):
        return (k not in obj) or (v21 and empty(obj.get(k)))

    for k in KD_META:
        if missing(meta, k):
            E.append(f"meta.{k} が欠けている")
    if v21:
        if "kind" in meta and meta.get("kind") != "KD":
            E.append(f"meta.kind が KD ではない: {meta.get('kind')!r}")
        if meta.get("id") and not KD_ID_RE.match(str(meta["id"])):
            E.append(f"meta.id が KD-YYYYMMDD-<slug> の形式でない: {meta['id']!r}")
        if meta.get("date") and not DATE_RE.match(str(meta["date"])):
            E.append(f"meta.date が YYYY-MM-DD でない: {meta['date']!r}")

    blocks = d.get("blocks") if isinstance(d, dict) else None
    if "blocks" not in (d or {}):
        # 2.0 の7節には blocks 自体の欠落を示す項目がない（ブロック必須項目の欠落として数えようがない）
        if v21:
            E.append("blocks が欠けている")
    blocks = blocks if isinstance(blocks, list) else []
    if v21 and not blocks:
        E.append("blocks が空（1件以上必要）")

    pid = str(meta.get("id", ""))
    ids = [b.get("id") for b in blocks if isinstance(b, dict)]
    idset = set(ids)
    for b in blocks:
        if not isinstance(b, dict):
            E.append("ブロックが mapping でない")
            continue
        bid = b.get("id", "?")
        for k in BLOCK_REQ:
            if missing(b, k):
                E.append(f"{bid}: 必須項目 {k} が欠けている")
        if v21 and b.get("id") and not BID_RE.match(str(b["id"])):
            E.append(f"{bid}: block.id が B001 形式でない")
        if b.get("type") is not None and b.get("type") not in TYPES:
            E.append(f"{bid}: type が語彙外: {b.get('type')!r}")
        if b.get("status") is not None and b.get("status") not in STATUSES:
            E.append(f"{bid}: status が語彙外: {b.get('status')!r}")
        srcs = b.get("sources")
        if v21 and "sources" in b and isinstance(srcs, list) and not srcs:
            pass  # missing() で既に error
        srcs = srcs if isinstance(srcs, list) else ([] if srcs is None else [srcs])
        for s in srcs:
            if not isinstance(s, dict) or missing(s, "ref") or missing(s, "basis"):
                E.append(f"{bid}: sources の要素に ref か basis がない")
                continue
            if s.get("basis") not in BASES:
                E.append(f"{bid}: basis が語彙外: {s.get('basis')!r}")
            if v21 and "page" in s and not (isinstance(s["page"], int) and not isinstance(s["page"], bool) and s["page"] >= 1):
                E.append(f"{bid}: page が1以上の整数でない: {s['page']!r}")
        # 参照（同一パケット内）
        refs = [str(s.get("ref")) for s in srcs if isinstance(s, dict)]
        sup = b.get("supersedes") or []
        sup = sup if isinstance(sup, list) else [sup]
        for r in refs + [str(x) for x in sup]:
            m = REF_RE.match(r.strip())
            if m and m.group("pid") == pid and m.group("bid") not in idset:
                E.append(f"{bid}: 同一パケット内参照の参照先がない: {r}")
            elif m and m.group("pid") != pid:
                W.append(f"{bid}: 別パケットへの参照（手元で確認できない場合は要注意）: {r}")
        for x in sup:
            m = REF_RE.match(str(x).strip())
            if m and m.group("pid") == pid and m.group("bid") == bid:
                E.append(f"{bid}: supersedes が自分自身を指している")
        # warning
        if str(b.get("why", "")).strip() == "UNKNOWN":
            W.append(f"{bid}: why が UNKNOWN")
        if any(isinstance(s, dict) and s.get("basis") == "UNKNOWN" for s in srcs):
            W.append(f"{bid}: basis が UNKNOWN")
        ab = b.get("asserted_by")
        if isinstance(ab, str) and ab.strip() and not AI_WORDS.search(ab):
            # 人（名前 / 役職）と判定: AI名・UNKNOWN 以外
            person_src = [s for s in srcs if isinstance(s, dict) and s.get("basis") in ("EXPERT", "DOCUMENT")]
            if not person_src:
                W.append(f"{bid}: asserted_by が人なのに、その発言を指す sources がない")
        if v21:
            bases = {s.get("basis") for s in srcs if isinstance(s, dict)}
            if bases and bases <= {"DERIVED", "UNKNOWN"}:
                if b.get("type") == "OBSERVATION":
                    W.append(f"{bid}: OBSERVATION なのに根拠が DERIVED/UNKNOWN だけ（P2）")
                if b.get("status") == "CONFIRMED":
                    W.append(f"{bid}: CONFIRMED なのに根拠が DERIVED/UNKNOWN だけ（5節: 未検証を CONFIRMED にしない）")
            for k in b:
                if k not in BLOCK_REQ + ["asserted_by", "supersedes", "unverified", "tags", "note"]:
                    W.append(f"{bid}: 仕様にないキー {k!r}")
    if len(ids) != len(idset):
        E.append("ブロックの id がパケット内で重複している")
    # 循環（同一パケット内）
    graph = {}
    for b in blocks:
        if isinstance(b, dict):
            sup = b.get("supersedes") or []
            sup = sup if isinstance(sup, list) else [sup]
            graph[b.get("id")] = [REF_RE.match(str(x).strip()).group("bid") for x in sup
                                   if REF_RE.match(str(x).strip()) and REF_RE.match(str(x).strip()).group("pid") == pid]
    for start in graph:
        seen, stack = set(), list(graph[start])
        while stack:
            n = stack.pop()
            if n == start and graph[start] != [start]:
                E.append(f"{start}: supersedes が循環している")
                break
            if n in seen:
                continue
            seen.add(n)
            stack.extend(graph.get(n, []))
    if v21:
        # 4節の矛盾: 同じ旧ブロックを、互いに supersedes で結ばれていない複数の CONFIRMED が置き換える
        by_old = {}
        for b in blocks:
            if isinstance(b, dict) and b.get("status") == "CONFIRMED":
                sup = b.get("supersedes") or []
                for x in (sup if isinstance(sup, list) else [sup]):
                    by_old.setdefault(str(x).strip(), []).append(b.get("id"))
        for old, news in by_old.items():
            if len(news) > 1:
                linked = any(f"{pid}#{a}" in [str(x) for x in (graph_sup(blocks, c))] for a in news for c in news if a != c)
                if not linked:
                    W.append(f"{old}: 複数の CONFIRMED ブロック {news} が置き換えている（4節: 矛盾として人間に確認）")
        if "handoff" not in d:
            W.append("handoff がない（引き継ぎ用途なら next / questions / unverified を書く）")
        for k in d:
            if k not in ("meta", "blocks", "handoff"):
                W.append(f"最上位に仕様にないキー {k!r}")
        for k in meta:
            if k not in KD_META + ["previous"]:
                W.append(f"meta に仕様にないキー {k!r}")
    if raw_len > 8000:
        W.append(f"8,000トークンを超えている可能性（{raw_len}字。目安: 日本語でおよそ8,000字）")
    return E, W


def graph_sup(blocks, bid):
    for b in blocks:
        if isinstance(b, dict) and b.get("id") == bid:
            s = b.get("supersedes") or []
            return s if isinstance(s, list) else [s]
    return []


# ---------------------------------------------------------------------------
# TASK
# ---------------------------------------------------------------------------
def check_task(d, rules: str):
    E, W = [], []
    v21 = rules == "2.1"
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}

    def missing(obj, k):
        return (k not in obj) or (v21 and empty(obj.get(k)))

    for k in TASK_META:
        if missing(meta, k):
            E.append(f"meta.{k} が欠けている")
    task = d.get("task")
    if not isinstance(task, str) or not task.strip() or "\n" in task.strip():
        E.append("task が複数行である、または空である")
    acts = d.get("actions")
    acts = acts if isinstance(acts, list) else []
    if v21 and not acts:
        E.append("actions がない、または空")
    for i, a in enumerate(acts, 1):
        if not isinstance(a, dict) or missing(a, "step") or missing(a, "output"):
            E.append(f"actions[{i}]: 番号（step）か output がない")
        elif v21 and missing(a, "do"):
            E.append(f"actions[{i}]: do がない")
    cons = d.get("constraints") if isinstance(d.get("constraints"), list) else []
    lock1 = any("変更" in str(c) and "禁止" in str(c) for c in cons)
    se = d.get("side_effect") if isinstance(d.get("side_effect"), dict) else {}
    lock2 = str(se.get("existing", "")).strip() == "変更なし"
    if not (lock1 and lock2):
        E.append("二重ロックの片方がない（constraints の変更禁止 / side_effect.existing の「変更なし」）")
    fb = d.get("forbidden") if isinstance(d.get("forbidden"), dict) else {}
    hard = fb.get("hard") if isinstance(fb.get("hard"), list) else []
    soft = fb.get("soft") if isinstance(fb.get("soft"), list) else []
    if len(hard) < 2 or len(soft) < 1:
        E.append("forbidden.hard が2件未満、または forbidden.soft が1件未満")
    sc = d.get("success_criteria") if isinstance(d.get("success_criteria"), list) else []
    if len(sc) < 3:
        E.append("success_criteria が3件未満")
    rb = d.get("report_back")
    if "report_back" not in d or (v21 and empty(rb)):
        E.append("report_back がない")
    subj = SUBJ_21 if v21 else SUBJ_20
    amb = AMBIG_21 if v21 else AMBIG_20
    for c in sc:
        hit = [w for w in subj if w in str(c)]
        if hit:
            W.append(f"success_criteria に主観的な基準 {hit}: {c}")
    for a in acts:
        if isinstance(a, dict):
            hit = [w for w in amb if w in str(a.get("do", ""))]
            if hit:
                W.append(f"actions に曖昧な表現 {hit}: {a.get('do')}")
    if v21:
        if "kind" in meta and meta.get("kind") != "TASK":
            E.append(f"meta.kind が TASK ではない: {meta.get('kind')!r}")
        if meta.get("id") and not TASK_ID_RE.match(str(meta["id"])):
            E.append(f"meta.id が TASK-YYYYMMDD-<slug> の形式でない: {meta['id']!r}")
        if meta.get("date") and not DATE_RE.match(str(meta["date"])):
            E.append(f"meta.date が YYYY-MM-DD でない: {meta['date']!r}")
        if meta.get("operation") and meta.get("operation") not in OPERATIONS:
            E.append(f"meta.operation が execute / review / research 以外: {meta.get('operation')!r}")
        if not isinstance(d.get("context"), dict) or empty(d.get("context")):
            E.append("context がない")
        else:
            for k in ("background", "goal"):
                if missing(d["context"], k):
                    E.append(f"context.{k} がない")
        inp = d.get("inputs")
        if not isinstance(inp, dict):
            E.append("inputs がない")
        elif inp.get("read_only") is not True:
            E.append("inputs.read_only: true がない")
        else:
            disc = inp.get("discovery")
            if isinstance(disc, dict) and disc.get("allowed") is True and empty(disc.get("scope")):
                E.append("inputs.discovery.allowed が true なのに scope が空")
        if isinstance(rb, list) and not (3 <= len(rb) <= 5):
            W.append(f"report_back が {len(rb)} 件（3〜5件）")
        if cons and not ("変更" in str(cons[0]) and "禁止" in str(cons[0])):
            W.append("constraints の1件目が変更禁止ではない")
        outs = {str(a.get("output")).strip() for a in acts if isinstance(a, dict) and a.get("output")}
        new = se.get("new") if isinstance(se.get("new"), list) else []
        newtxt = "\n".join(str(x) for x in new)
        # 「<フォルダ>/ 配下」形式の一括列挙を許す
        prefixes = [m.group(1) for x in new for m in [re.match(r"^\s*(\S+/)\s*配下", str(x))] if m]
        miss = sorted(o for o in outs if o not in newtxt and not any(o.startswith(p) for p in prefixes))
        if miss:
            W.append(f"actions の output が side_effect.new に列挙されていない: {miss}")
        if lock2:
            hit = sorted({w for a in acts if isinstance(a, dict) for w in MUTATE_WORDS if w in str(a.get("do", ""))})
            if hit:
                W.append(f"existing が「変更なし」なのに actions に変更を示す語 {hit} がある")
        known = {"meta", "task", "context", "inputs", "actions", "constraints", "forbidden",
                 "success_criteria", "side_effect", "report_back"}
        for k in d:
            if k not in known:
                W.append(f"最上位に仕様にないキー {k!r}")
    return E, W


# ---------------------------------------------------------------------------
def check_text(text_: str, rules: str):
    d, perr, dups, marks = load(text_)
    if perr:
        return {"kind": "?", "errors": [f"YAMLとして読めない: {perr}"], "warnings": []}
    if not isinstance(d, dict):
        return {"kind": "?", "errors": ["YAMLとして読めない（mapping でない）"], "warnings": []}
    E, W = [], []
    if rules == "2.1":
        for x in dups:
            E.append(f"同じ階層に同じキーが2回ある: {x}")
        for x in marks:
            E.append(f"アンカー / エイリアス / タグを使っている: {x}")
        for p, k in walk_keys(d):
            if not (isinstance(k, str) and KEY_RE.match(k)):
                E.append(f"キーが英小文字でない: {p}.{k}")
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    kind = meta.get("kind")
    looks_task = kind == "TASK" or "task" in d or "actions" in d
    if looks_task:
        e, w = check_task(d, rules)
        k = "TASK"
    else:
        e, w = check_kd(d, rules, len(text_))
        k = "KD"
    return {"kind": k, "errors": E + e, "warnings": W + w}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", choices=["2.0", "2.1"], required=True)
    ap.add_argument("--embedded", help="仕様書内の例のキー名（example / task_example）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    out = {}
    for f in a.files:
        t = Path(f).read_text(encoding="utf-8")
        if a.embedded:
            t = yaml.safe_load(t)[a.embedded]
        out[f] = check_text(t, a.rules)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for f, r in out.items():
            print(f"== {f} [{r['kind']}] error {len(r['errors'])} / warning {len(r['warnings'])}")
            for x in r["errors"]:
                print("  E:", x)
            for x in r["warnings"]:
                print("  W:", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
