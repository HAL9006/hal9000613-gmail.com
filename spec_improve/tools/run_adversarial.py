#!/usr/bin/env python3
"""adversarial/ の全不正パケットを v2.0 / v2.1 のチェックリストで検査し、検出可否を表にする.

「検出」= その違反に対応するメッセージ（EXPECT のキーワードを含む error / warning）が出たこと。
無関係な警告だけが出た場合は「非検出」と数える。
出力: ../adversarial_detection.json と、標準出力に Markdown 表。
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_packet import check_text  # noqa: E402

ADV = HERE.parent / "adversarial"
EXPECT = {
    "A01": "blocks が空", "A02": "sources が欠けている", "A03": "why が欠けている", "A04": "title が欠けている",
    "A05": "kind が KD ではない", "A06": "アンカー", "A07": "キーが英小文字でない", "A08": "DERIVED/UNKNOWN だけ",
    "A09": "重複", "A10": "type が語彙外", "A11": "自分自身", "A12": "複数の CONFIRMED", "A13": "形式でない",
    "A14": "page が", "A15": "同じキーが2回", "A16": "purpose", "A17": "asserted_by が人", "A18": "handoff がない",
    "T01": "context がない", "T02": "read_only", "T03": "operation が", "T04": "変更を示す語", "T05": "report_back が",
    "T06": "主観的", "T07": "side_effect.new", "T08": "task が複数行", "T09": "forbidden.hard", "T10": "meta.kd",
    "T11": "inputs がない",
}


def main():
    rows, res = [], {}
    for f in sorted(ADV.glob("[AT][0-9][0-9]_*.yaml")):
        cid = f.name[:3]
        text = f.read_text(encoding="utf-8")
        violates = re.search(r"^# 違反: (.*)$", text, re.M).group(1)
        rec = {"violates": violates}
        for rules in ("2.0", "2.1"):
            r = check_text(text, rules)
            hitE = [m for m in r["errors"] if EXPECT[cid] in m]
            hitW = [m for m in r["warnings"] if EXPECT[cid] in m]
            level = "error" if hitE else ("warning" if hitW else "非検出")
            rec[rules] = {"level": level, "errors": r["errors"], "warnings": r["warnings"]}
        res[f.name] = rec
        rows.append((f.name, violates, rec["2.0"]["level"], rec["2.1"]["level"]))
    (HERE.parent / "adversarial_detection.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("| ファイル | 違反した規則（原本） | v2.0 チェックリスト | v2.1 チェックリスト |")
    print("|---|---|---|---|")
    for n, v, a, b in rows:
        print(f"| `{n}` | {v} | {a} | {b} |")
    d20 = sum(1 for r in rows if r[2] != "非検出")
    d21 = sum(1 for r in rows if r[3] != "非検出")
    print(f"\n作成数 {len(rows)} / v2.0 検出 {d20} / v2.1 検出 {d21}")


if __name__ == "__main__":
    main()
