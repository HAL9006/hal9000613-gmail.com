#!/usr/bin/env python3
"""原本 v2.0 と改訂案 v2.1 を比較する（行数・必須項目数・原則の同一性・最小例のチェック結果）."""
import re, sys, json
from pathlib import Path
import yaml
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_packet import check_text

ROOT = HERE.parent
FILES = {"2.0": ROOT / "original" / "SPEC_KD-TASKパケット_v2.0_汎用版.yaml",
         "2.1": ROOT / "SPEC_KD-TASKパケット_v2.1_改訂案.yaml"}


def required_count(raw, d):
    """必須項目数 = structure 内で「# 必須」とコメントされた行 + block.required のキー数 + source_item で「必須。」と書かれた項目数"""
    n_comment = len(re.findall(r"#\s*必須", raw))
    n_block = len(d["block"]["required"])
    n_src = sum(1 for v in d["block"]["source_item"].values() if str(v).startswith("必須"))
    return {"structure_comment": n_comment, "block_required": n_block, "source_item": n_src,
            "total": n_comment + n_block + n_src}


out = {}
for v, p in FILES.items():
    raw = p.read_text(encoding="utf-8")
    d = yaml.safe_load(raw)
    out[v] = {"lines": raw.count("\n"), "chars": len(raw), "required": required_count(raw, d),
              "principles": d["principles"], "task_principles": d["task_principles"]}
    for key in ("example", "task_example"):
        for rules in ("2.0", "2.1"):
            r = check_text(d[key], rules)
            out[v][f"{key}@rules{rules}"] = {"errors": r["errors"], "warnings": r["warnings"]}
same_p = out["2.0"]["principles"] == out["2.1"]["principles"]
same_t = out["2.0"]["task_principles"] == out["2.1"]["task_principles"]
print(f"lines: {out['2.0']['lines']} -> {out['2.1']['lines']} ({out['2.1']['lines'] - out['2.0']['lines']:+d})")
print(f"chars: {out['2.0']['chars']} -> {out['2.1']['chars']} ({out['2.1']['chars'] - out['2.0']['chars']:+d})")
print(f"required: {out['2.0']['required']} -> {out['2.1']['required']}")
print(f"P1-P4 identical: {same_p} / T1-T4 identical: {same_t}")
for v in out:
    for k in out[v]:
        if "@" in k:
            print(f"spec {v} {k}: error {len(out[v][k]['errors'])} warning {len(out[v][k]['warnings'])}", out[v][k]['errors'] + out[v][k]['warnings'])
for v in out:
    out[v].pop("principles"); out[v].pop("task_principles")
out["principles_identical"] = {"P": same_p, "T": same_t}
(ROOT / "spec_compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
