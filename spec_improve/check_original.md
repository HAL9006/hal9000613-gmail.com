# check_original — 原本 v2.0 と2つの最小例の機械検査（step 1）

- 対象: `original/SPEC_KD-TASKパケット_v2.0_汎用版.yaml`（添付原本のコピー。sha256 `bfdc7eb3…9229` が添付原本と一致）
- 道具: `tools/check_packet.py --rules 2.0`。原本の 7節（KD）と 14節（TASK）のチェックリストを**文字どおり**に実装した。
  - 「欠けている」は「キーがない」と読んだ。原本はこの語を定義していないので、キーがあって値が空の場合は検出しない（→ ADV-03/04）。
  - 14節 warning の主観語は、原本に書かれた語（適切・十分・高品質）と ambiguous_words の ng 句に限った。
- 注: パケットの指示文にある「8節・13節のチェックリスト」は、原本では **7節（checklist）と 14節（task_checklist）**。8節は情報管理、13節は受け手の規則なので、7節・14節で検査した（→ USE-05）。

## 1. チェックリストによる結果

| 対象 | 適用したチェックリスト | error | warning |
|---|---|---:|---:|
| 仕様書本体 | 7節の「YAMLとして読めない」のみ（仕様書はパケットではないので、meta などの項目は当てはまらない） | 0 | 0 |
| KD最小例（9節 `example`） | 7節 | **0** | **0** |
| TASK最小例（15節 `task_example`） | 14節 | **0** | **0** |

どちらの最小例も、原本のチェックリストは通る。

## 2. チェックリストの外で見つかった不備（原本の他の規則との照合）

| ID | 検証 / 推論 | 内容 | 証拠 |
|---|---|---|---|
| CHK-01 | 検証した | 1節 format_rules の3項目め「YAMLのアンカー（& *）とタグ（!）は使わない。値の先頭が * & ! : # の場合は引用符で囲む」が、YAML としては文字列ではなく **mapping** として読まれる。`!` のあとの「 : 」でキーと値に分かれ、値の「# の場合は引用符で囲む」はコメントとして消える。**引用符の規則を書いた行そのものが、その規則に違反している** | `yaml.safe_load` の結果が `{'YAMLのアンカー（& *）とタグ（!）は使わない。値の先頭が * & !': None}` |
| CHK-02 | 検証した | KD最小例 B002 の title「振動上昇は**軸受の摩耗**が原因の可能性」の要点が、content にない。content には「軸受」「摩耗」の語が1つも出てこない。P1 は受け手に title で読むかどうかを選ばせるので、title と content が食い違うと、title だけを読んだ受け手と content を読んだ受け手で理解が変わる | 文字列照合: `'軸受' in content == False`, `'摩耗' in content == False` |
| CHK-03 | 検証した | TASK最小例の side_effect.new は「所見欄_下書き」の1件だけ。actions の output のうち4件（読み取りメモ・所見欄の表・所見文・確認事項欄）が載っていない。12節は「新しく作るものの一覧（**すべて**列挙）」と定めているが、14節にこれを確かめる項目がないので、チェックは通ってしまう | actions[].output と side_effect.new の集合を比較 |
| CHK-04 | 検証した | 2節は why を「なぜそう判断したか」と定義している。一方 KD最小例 B001（OBSERVATION）の why は「報告書で異常の有無を判断するための基礎データ」で、判断の理由ではなく**記録した目的**が書かれている。OBSERVATION で why に何を書くかが定義されていない | 2節 why の定義文と B001 の why の比較 |
| CHK-05 | 検証した | 2節と7節は asserted_by について「**人の名前**」と書いているが、KD最小例 B003 の asserted_by は役職名（点検担当者）。役職名が「人の名前」に当たり、7節 warning の対象になるのかが読み取れない | 7節 warning の文面と B003 の比較 |
| CHK-06 | 検証した | 1節は「キー（項目名）は**英小文字**」と定めているが、仕様自身が `kd_refs`・`read_only`・`success_criteria` など、アンダースコアを含むキーを必須項目に使っている。規則を文字どおりに読むと、仕様どおりのパケットが違反になる | 1節 format_rules と 12節 structure の比較 |

参考（不備として数えないもの）: 仕様書本体では、vocab の語彙名（OBSERVATION など20キー）が英大文字になっている。これは仕様書の中の語彙の定義で、パケットのキーではないので、1節の規則は当てはまらないと判断した。

## 3. 再実行の方法

```bash
cd spec_improve
python3 tools/check_packet.py --rules 2.0 --embedded example      original/SPEC_KD-TASKパケット_v2.0_汎用版.yaml
python3 tools/check_packet.py --rules 2.0 --embedded task_example original/SPEC_KD-TASKパケット_v2.0_汎用版.yaml
python3 tools/compare_specs.py        # 原本と改訂版の数値比較（spec_compare.json）
```
