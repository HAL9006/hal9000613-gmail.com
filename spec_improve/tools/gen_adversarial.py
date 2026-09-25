#!/usr/bin/env python3
"""不正パケット（adversarial/）を生成する。内容はすべて架空。

各パケットは、正しい基準パケット（BASE_KD / BASE_TASK）に1種類の違反だけを入れたもの。
違反の種類は CASES の "violates" に、原本の何節のどの規則に反するかを記録する。
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "adversarial"

BASE_KD = """\
meta:
  kind: KD
  kd: "2.0"
  id: KD-20260925-adv-sample
  date: "2026-09-25"
  from: "AI-A（整理担当）"
  to: "AI-B（報告担当）"
  purpose: "架空の点検結果を引き継ぐ"
blocks:
  - id: B001
    type: OBSERVATION
    status: CONFIRMED
    title: 3号機の温度が前回より5度高い
    content: 点検記録では前回 40度、今回 45度。
    why: 異常の有無を判断する基礎データとして記録する
    sources:
      - {ref: "点検記録 2026-09-24", basis: DOCUMENT, page: 2}
    asserted_by: AI-A
  - id: B002
    type: INSIGHT
    status: TENTATIVE
    title: 温度上昇は外気温の影響の可能性
    content: 点検日の外気温が前回より高かったため、外気温の影響が考えられる。
    why: 設備の異常か環境要因かで対応が変わるため
    sources:
      - {ref: "KD-20260925-adv-sample#B001", basis: DERIVED}
    asserted_by: AI-A
handoff:
  next: ["B001 を報告書に転記する"]
  questions: []
  unverified: ["外気温の実測値は未確認"]
"""

BASE_TASK = """\
meta:
  kind: TASK
  kd: "2.0"
  id: TASK-20260925-adv-sample
  date: "2026-09-25"
  from: "AI-A"
  to: "AI-B"
  operation: execute
task: "架空の点検記録から温度の一覧表を作る"
context:
  background: "点検結果を一覧で確認したい"
  premises: ["点検記録は1ファイル"]
  goal: "温度一覧表が1枚で完成している"
  kd_refs: []
inputs:
  required: ["点検記録.xlsx"]
  optional: []
  read_only: true
actions:
  - {step: 1, do: "点検記録から号機と温度を抜き出す", output: "抜き出しメモ"}
  - {step: 2, do: "号機順に並べて表にする", output: "温度一覧表"}
constraints:
  - "既存ファイル・既存データの変更・削除禁止"
forbidden:
  hard: ["点検記録の上書き", "記録にない数値の記載"]
  soft: ["原因の推定（別作業）"]
success_criteria:
  - "表の行数が点検記録の号機数と一致する"
  - "温度の値が点検記録と一致する"
  - "表が1枚に収まっている"
side_effect:
  new: ["抜き出しメモ", "温度一覧表"]
  existing: "変更なし"
report_back:
  - "表の行数（数値）"
  - "success_criteria をすべて満たしたか（YES/NO）"
  - "記録と食い違う値があったか（YES/NO）"
"""


def r(base, old, new, count=1):
    assert old in base, old
    return base.replace(old, new, count)


CASES = [
    # --- KD --------------------------------------------------------------
    ("A01_kd_blocks_empty", "KD 1節: blocks は1件以上",
     BASE_KD.split("blocks:")[0] + "blocks: []\nhandoff:\n  next: []\n  questions: []\n  unverified: []\n"),
    ("A02_kd_sources_empty", "KD 2節: sources は1件以上",
     r(BASE_KD, '    sources:\n      - {ref: "点検記録 2026-09-24", basis: DOCUMENT, page: 2}\n', "    sources: []\n")),
    ("A03_kd_why_empty_string", "KD 2節/P3: why は必須。不明なら UNKNOWN",
     r(BASE_KD, "why: 異常の有無を判断する基礎データとして記録する", 'why: ""')),
    ("A04_kd_title_hash_null", "KD 1節 format_rules: 値の先頭が # なら引用符（無引用だとコメント扱いで値が消える）",
     r(BASE_KD, "title: 3号機の温度が前回より5度高い", "title: #3号機の温度が前回より5度高い")),
    ("A05_kd_kind_wrong", "KD 1節: meta.kind は KD",
     r(BASE_KD, "kind: KD", "kind: TASKS")),
    ("A06_kd_anchor_alias", "KD 1節 format_rules: アンカー（& *）を使わない",
     r(r(BASE_KD, "  from: \"AI-A（整理担当）\"", "  from: &who \"AI-A（整理担当）\""),
       "    asserted_by: AI-A\n", "    asserted_by: *who\n")),
    ("A07_kd_japanese_keys_and_100pct", "KD 1節 format_rules: キーは英小文字 / 5節: 「100%」と書かない",
     r(BASE_KD, "    asserted_by: AI-A\n", "    asserted_by: AI-A\n    確信度: \"100%\"\n")),
    ("A08_kd_observation_derived_confirmed", "P2（OBSERVATION は実際に確認した事実）/ 5節（未検証を CONFIRMED にしない）",
     r(BASE_KD, '      - {ref: "点検記録 2026-09-24", basis: DOCUMENT, page: 2}', '      - {ref: "過去の傾向からの推定", basis: DERIVED}')),
    ("A09_kd_duplicate_block_id", "KD 7節 error: ブロックの id が重複（対照: 検出されるべき）",
     r(BASE_KD, "  - id: B002", "  - id: B001")),
    ("A10_kd_type_out_of_vocab", "KD 7節 error: type が語彙外（対照）",
     r(BASE_KD, "type: INSIGHT", "type: FACT")),
    ("A11_kd_supersedes_self", "KD 7節 error: supersedes が自分自身（対照）",
     r(BASE_KD, "    asserted_by: AI-A\nhandoff", '    asserted_by: AI-A\n    supersedes: ["KD-20260925-adv-sample#B002"]\nhandoff')),
    ("A12_kd_conflicting_supersede", "KD 4節: 同じ旧ブロックを関係のない複数の CONFIRMED が置き換えたら矛盾として人間に確認",
     r(BASE_KD, "handoff:", """  - id: B003
    type: DECISION
    status: CONFIRMED
    title: 温度上昇は計器の誤差として扱う
    content: 計器の許容誤差内として扱う。
    why: 計器の校正記録で誤差範囲を確認したため
    sources:
      - {ref: "校正記録 2026-08", basis: DOCUMENT}
    supersedes: ["KD-20260925-adv-sample#B002"]
  - id: B004
    type: DECISION
    status: CONFIRMED
    title: 温度上昇は設備異常として扱う
    content: 設備異常として対応する。
    why: 担当者が現地で異音を確認したため
    sources:
      - {ref: "担当者の電話連絡 2026-09-25", basis: EXPERT}
    supersedes: ["KD-20260925-adv-sample#B002"]
handoff:""")),
    ("A13_kd_bad_formats", "KD 1節: meta.id は KD-YYYYMMDD-<slug>、date は YYYY-MM-DD / 2節: block.id は B001 形式",
     r(r(r(BASE_KD, "id: KD-20260925-adv-sample\n", "id: kd_0925\n"), 'date: "2026-09-25"', 'date: "2026/9/25"'),
       "  - id: B002", "  - id: \"2\"")),
    ("A14_kd_page_invalid", "KD 2節 source_item: page は1以上の整数",
     r(BASE_KD, "page: 2}", "page: 0}")),
    ("A15_kd_duplicate_yaml_key", "KD 1節: 全体が妥当なYAML（YAML仕様ではキー重複は不可。多くの読み手は黙って後勝ち）",
     r(BASE_KD, "    why: 異常の有無を判断する基礎データとして記録する\n",
       "    why: 異常の有無を判断する基礎データとして記録する\n    why: UNKNOWN\n")),
    ("A16_kd_fullwidth_indent", "KD 1節: 全体が妥当なYAML（全角スペースでインデント）（対照）",
     r(BASE_KD, "  purpose:", "　 purpose:")),
    ("A17_kd_person_without_source", "KD 7節 warning: asserted_by が人なのに sources がその発言を指さない（対照）",
     r(BASE_KD, "    asserted_by: AI-A\n  - id: B002", "    asserted_by: 設備課長\n  - id: B002".replace("設備課長", "現場責任者"))
     .replace('basis: DOCUMENT, page: 2}', 'basis: OBSERVED}')),
    ("A18_kd_no_handoff", "KD 1節: handoff は「引き継ぎでは実質必須」",
     BASE_KD.split("handoff:")[0]),
    # --- TASK ------------------------------------------------------------
    ("T01_task_no_context", "TASK 12節: context は必須",
     r(BASE_TASK, BASE_TASK[BASE_TASK.index("context:"):BASE_TASK.index("inputs:")], "")),
    ("T02_task_no_read_only", "TASK 12節: inputs.read_only は必須",
     r(BASE_TASK, "  read_only: true\n", "")),
    ("T03_task_operation_out_of_vocab", "TASK 12節: operation は execute・review・research のいずれか",
     r(BASE_TASK, "operation: execute", "operation: fix")),
    ("T04_task_lock_but_overwrite_action", "T2 二重ロック: 既存を変えない宣言と矛盾する作業",
     r(BASE_TASK, 'do: "号機順に並べて表にする", output: "温度一覧表"',
       'do: "号機順に並べ、点検記録.xlsx に上書き保存する", output: "温度一覧表"')),
    ("T05_task_report_back_open", "TASK 12節: report_back は数値か YES/NO で答えられるもの3〜5件",
     r(BASE_TASK, BASE_TASK[BASE_TASK.index("report_back:"):],
       "report_back:\n  - \"感想\"\n  - \"気づいたこと\"\n  - \"改善案\"\n  - \"苦労した点\"\n  - \"次にやりたいこと\"\n  - \"所要時間の内訳\"\n  - \"その他\"\n")),
    ("T06_task_subjective_criteria", "T3: 完了条件は数値か状態で確かめられるものだけ",
     r(BASE_TASK, BASE_TASK[BASE_TASK.index("success_criteria:"):BASE_TASK.index("side_effect:")],
       "success_criteria:\n  - \"表が正確である\"\n  - \"表がわかりやすい\"\n  - \"問題なく完了している\"\n")),
    ("T07_task_side_effect_incomplete", "TASK 12節: side_effect.new は新しく作るものをすべて列挙",
     r(BASE_TASK, 'new: ["抜き出しメモ", "温度一覧表"]', 'new: ["温度一覧表"]')),
    ("T08_task_two_line", "TASK 14節 error: task が複数行（対照）",
     r(BASE_TASK, 'task: "架空の点検記録から温度の一覧表を作る"', 'task: |\n  架空の点検記録から\n  温度の一覧表を作る')),
    ("T09_task_hard_one", "TASK 14節 error: forbidden.hard が2件未満（対照）",
     r(BASE_TASK, 'hard: ["点検記録の上書き", "記録にない数値の記載"]', 'hard: ["点検記録の上書き"]')),
    ("T10_task_spec_version_alias", "TASK 12節: 版は meta.kd に書く（受領パケットと同じ別名 spec_version）（対照）",
     r(BASE_TASK, '  kd: "2.0"', '  spec_version: "2.0"')),
    ("T11_task_no_inputs", "TASK 12節: inputs は必須",
     r(BASE_TASK, BASE_TASK[BASE_TASK.index("inputs:"):BASE_TASK.index("actions:")], "")),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, violates, body in CASES:
        (OUT / f"{name}.yaml").write_text(f"# 不正パケット（内容は架空）\n# 違反: {violates}\n{body}", encoding="utf-8")
    (OUT / "BASE_KD.yaml").write_text("# 基準パケット（正しい形。内容は架空）\n" + BASE_KD, encoding="utf-8")
    (OUT / "BASE_TASK.yaml").write_text("# 基準パケット（正しい形。内容は架空）\n" + BASE_TASK, encoding="utf-8")
    print(f"{len(CASES)} cases -> {OUT}")


if __name__ == "__main__":
    main()
