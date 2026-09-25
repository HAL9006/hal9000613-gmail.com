# spec_improve — AI間通信仕様 v2.0 の検査と v2.1 改訂案（TASK-20260925-spec-improve）

| ファイル | step | 内容 |
|---|---|---|
| `check_original.md` | 1 | 原本と2つの最小例のチェック結果、チェックリストの外で見つかった不備（CHK-01〜06） |
| `adversarial/` | 2 | 不正パケット29件と基準パケット2件（内容は架空） |
| `adversarial_result.md` / `adversarial_detection.json` | 2 | 検出可否の表（v2.0: 8/29、v2.1: 29/29）と欠陥 ADV-01〜21 |
| `usability_findings.md` | 3 | 3つの用途での誤解・迷い・矛盾（USE-01〜16）と、受領した TASK パケットの事前点検 |
| `SPEC_KD-TASKパケット_v2.1_改訂案.yaml` | 4 | 改訂案 |
| `changelog.md` / `spec_compare.json` | 5 | 変更 C01〜C25（それぞれ根拠の所見 ID 付き）、提案 PR-01〜07、行数・必須項目数の比較 |
| `KD_result.yaml` | 6 | 結果報告（KD パケット。v2.1 のチェックで error 0 / warning 0） |
| `original/` | — | 添付原本のコピー（sha256 一致。比較用。原本自体は変更していない） |
| `received_TASK-20260925-spec-improve.yaml` | — | 受領した TASK パケットの写し（事前点検の記録用） |
| `tools/` | — | `check_packet.py`（チェッカ）、`gen_adversarial.py`、`run_adversarial.py`、`compare_specs.py` |

## 再実行（標準ライブラリ + PyYAML。ネットワーク通信なし）

```bash
cd spec_improve
python3 tools/gen_adversarial.py
python3 tools/run_adversarial.py
python3 tools/compare_specs.py
python3 tools/check_packet.py --rules 2.1 KD_result.yaml
```
