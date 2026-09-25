# adversarial_result — 不正パケットによるチェックリストの検出試験（step 2）

- 作成数: **29件**（`adversarial/` 配下。KD 18件、TASK 11件。内容はすべて架空）。基準パケット `BASE_KD.yaml` / `BASE_TASK.yaml` は、v2.0 / v2.1 のどちらのルールでも error 0・warning 0。
- 各パケットは基準パケットに**1種類の違反**だけを入れたもの（A07 と A13 は、同じ種類の違反を2〜3箇所に入れている）。うち8件は、原本のチェックリストで検出されるはずの**対照**。
- 判定: `tools/run_adversarial.py`。違反に対応するメッセージが出たときだけ「検出」と数える。関係のない警告しか出なかった場合は「非検出」。
- 再実行: `python3 tools/gen_adversarial.py && python3 tools/run_adversarial.py`（詳細は `adversarial_detection.json`）

## 結果の要約

| チェックリスト | 検出 / 作成 | 検出率 |
|---|---:|---:|
| 原本 v2.0（7節・14節） | 8 / 29 | 27.6% |
| 改訂案 v2.1（7節・14節） | 29 / 29 | 100%（下の注意を参照） |

**v2.1 の結果の読み方（重要）**: v2.1 のチェック項目は、これらの不正パケットを見たあとで、それを検出できるように書いたものです。同じ29件で測った v2.1 の検出率は作り方からして高くなるので、**改善効果の検証ではありません**。v2.1 がほかの違反も検出できるか、また実際のAI（ChatGPT / Gemini / Copilot 等）が自然文のチェックリストを読んで同じように判定するかは、**検証していません**。

**このチェッカの限界**: `check_packet.py` は、私が自然文のチェックリストをプログラムにしたものです。v2.0 の「非検出」は「チェックリストの項目を文字どおりに当てはめると検出されない」という意味です。実際のAIが常識で補って気づく可能性はあります（未検証）。

## 全件の検出結果

| ファイル | 違反した規則（原本） | v2.0 チェックリスト | v2.1 チェックリスト |
|---|---|---|---|
| `A01_kd_blocks_empty.yaml` | KD 1節: blocks は1件以上 | 非検出 | error |
| `A02_kd_sources_empty.yaml` | KD 2節: sources は1件以上 | 非検出 | error |
| `A03_kd_why_empty_string.yaml` | KD 2節/P3: why は必須。不明なら UNKNOWN | 非検出 | error |
| `A04_kd_title_hash_null.yaml` | KD 1節 format_rules: 値の先頭が # なら引用符（無引用だとコメント扱いで値が消える） | 非検出 | error |
| `A05_kd_kind_wrong.yaml` | KD 1節: meta.kind は KD | 非検出 | error |
| `A06_kd_anchor_alias.yaml` | KD 1節 format_rules: アンカー（& *）を使わない | 非検出 | error |
| `A07_kd_japanese_keys_and_100pct.yaml` | KD 1節 format_rules: キーは英小文字 / 5節: 「100%」と書かない | 非検出 | error |
| `A08_kd_observation_derived_confirmed.yaml` | P2（OBSERVATION は実際に確認した事実）/ 5節（未検証を CONFIRMED にしない） | 非検出 | warning |
| `A09_kd_duplicate_block_id.yaml` | KD 7節 error: ブロックの id が重複（対照: 検出されるべき） | error | error |
| `A10_kd_type_out_of_vocab.yaml` | KD 7節 error: type が語彙外（対照） | error | error |
| `A11_kd_supersedes_self.yaml` | KD 7節 error: supersedes が自分自身（対照） | error | error |
| `A12_kd_conflicting_supersede.yaml` | KD 4節: 同じ旧ブロックを関係のない複数の CONFIRMED が置き換えたら矛盾として人間に確認 | 非検出 | warning |
| `A13_kd_bad_formats.yaml` | KD 1節: meta.id は KD-YYYYMMDD-<slug>、date は YYYY-MM-DD / 2節: block.id は B001 形式 | 非検出 | error |
| `A14_kd_page_invalid.yaml` | KD 2節 source_item: page は1以上の整数 | 非検出 | error |
| `A15_kd_duplicate_yaml_key.yaml` | KD 1節: 全体が妥当なYAML（YAML仕様ではキー重複は不可。多くの読み手は黙って後勝ち） | 非検出 | error |
| `A16_kd_fullwidth_indent.yaml` | KD 1節: 全体が妥当なYAML（全角スペースでインデント）（対照） | error | error |
| `A17_kd_person_without_source.yaml` | KD 7節 warning: asserted_by が人なのに sources がその発言を指さない（対照） | warning | warning |
| `A18_kd_no_handoff.yaml` | KD 1節: handoff は「引き継ぎでは実質必須」 | 非検出 | warning |
| `T01_task_no_context.yaml` | TASK 12節: context は必須 | 非検出 | error |
| `T02_task_no_read_only.yaml` | TASK 12節: inputs.read_only は必須 | 非検出 | error |
| `T03_task_operation_out_of_vocab.yaml` | TASK 12節: operation は execute・review・research のいずれか | 非検出 | error |
| `T04_task_lock_but_overwrite_action.yaml` | T2 二重ロック: 既存を変えない宣言と矛盾する作業 | 非検出 | warning |
| `T05_task_report_back_open.yaml` | TASK 12節: report_back は数値か YES/NO で答えられるもの3〜5件 | 非検出 | warning |
| `T06_task_subjective_criteria.yaml` | T3: 完了条件は数値か状態で確かめられるものだけ | 非検出 | warning |
| `T07_task_side_effect_incomplete.yaml` | TASK 12節: side_effect.new は新しく作るものをすべて列挙 | 非検出 | warning |
| `T08_task_two_line.yaml` | TASK 14節 error: task が複数行（対照） | error | error |
| `T09_task_hard_one.yaml` | TASK 14節 error: forbidden.hard が2件未満（対照） | error | error |
| `T10_task_spec_version_alias.yaml` | TASK 12節: 版は meta.kd に書く（受領パケットと同じ別名 spec_version）（対照） | error | error |
| `T11_task_no_inputs.yaml` | TASK 12節: inputs は必須 | 非検出 | error |

## 欠陥として記録するもの（v2.0 で非検出だった21件。いずれも checker で再現できるので「検証した」）

| ID | ファイル | 検出できない理由 | v2.1 |
|---|---|---|---|
| ADV-01 | `A01_kd_blocks_empty.yaml` | blocks: [] はブロックがないので、「ブロックの必須項目が欠けている」に当たらない。中身のないパケットが通る | error |
| ADV-02 | `A02_kd_sources_empty.yaml` | sources: [] は要素がないので、「sources の各要素に ref か basis がない」に当たらない。根拠のないブロックが通る | error |
| ADV-03 | `A03_kd_why_empty_string.yaml` | why: "" はキーがあるので「欠けている」と判定されない。P3（UNKNOWN と書く）が守られていなくても通る | error |
| ADV-04 | `A04_kd_title_hash_null.yaml` | `title: #3号機…` はコメント扱いで値が null になる。キーはあるので、タイトルが黙って消えても通る | error |
| ADV-05 | `A05_kd_kind_wrong.yaml` | kind の値は確かめていない（あるかどうかだけ） | error |
| ADV-06 | `A06_kd_anchor_alias.yaml` | format_rules の禁止事項（アンカー・エイリアス）に対応するチェック項目がない | error |
| ADV-07 | `A07_kd_japanese_keys_and_100pct.yaml` | 日本語キーと仕様外のキー（「確信度: 100%」）を確かめる項目がない。5節が禁じる「100%」の表現が、仕様外のキーを通って入り込む | error |
| ADV-08 | `A08_kd_observation_derived_confirmed.yaml` | basis が DERIVED だけの OBSERVATION / CONFIRMED は、P2 と5節に反するが、7節の warning は UNKNOWN しか見ない | warning |
| ADV-09 | `A12_kd_conflicting_supersede.yaml` | 4節3項の「矛盾として人間に確認する」に対応するチェック項目がない。そのうえ「互いに関係のない」が定義されていない | warning |
| ADV-10 | `A13_kd_bad_formats.yaml` | id・date・block.id の書式を確かめる項目がない（出た warning は、id を変えたことで起きた副作用の参照警告だけ） | error |
| ADV-11 | `A14_kd_page_invalid.yaml` | page の型と範囲を確かめる項目がない | error |
| ADV-12 | `A15_kd_duplicate_yaml_key.yaml` | 重複キーは多くの YAML 読み込み器が黙って後勝ちにする。最初の why が消えて UNKNOWN が残るが、出るのは「why が UNKNOWN」の warning だけで、消えたことは分からない | error |
| ADV-13 | `A18_kd_no_handoff.yaml` | handoff は「任意（引き継ぎでは実質必須）」。チェック項目がない | warning |
| ADV-14 | `T01_task_no_context.yaml` | 14節は context の欠落を確かめない（12節では必須） | error |
| ADV-15 | `T02_task_no_read_only.yaml` | 14節は inputs.read_only の欠落を確かめない（12節では必須）。受領した TASK パケットにもこの欠落がある | error |
| ADV-16 | `T03_task_operation_out_of_vocab.yaml` | operation の値を確かめる項目がない | error |
| ADV-17 | `T04_task_lock_but_overwrite_action.yaml` | 二重ロックは2箇所の宣言があるかだけを見る。actions に「上書き保存する」とあっても通る | warning |
| ADV-18 | `T05_task_report_back_open.yaml` | report_back は「ない」ときしか検出されない。7件の自由記述（感想など）でも通る | warning |
| ADV-19 | `T06_task_subjective_criteria.yaml` | 主観語の例（適切・十分・高品質）に当たらない主観的な基準（正確・わかりやすい・問題ない）は検出されない | warning |
| ADV-20 | `T07_task_side_effect_incomplete.yaml` | side_effect.new を「すべて列挙」したかを確かめる項目がない（TASK最小例自体にも同じ不備がある: CHK-03） | warning |
| ADV-21 | `T11_task_no_inputs.yaml` | 14節は inputs の欠落を確かめない（12節では必須） | error |

## 必須項目について

改訂案 v2.1 では**必須項目を増やしていない**（37 → 37。数え方は changelog.md）。v2.1 で error にした項目（blocks・sources が空、context・inputs・read_only の欠落など）は、どれも原本の 1節・2節・12節で既に「必須」「1件以上」とされていたものです。上の表は、それをチェックリストで確かめられなかったために起きる具体的な失敗の記録にあたります（例: A01 では中身のない KD、T02 では入力を変更しない宣言のない依頼が、そのまま通る）。

## 対照8件について

A09 / A10 / A11 / A16 / A17 / T08 / T09 / T10 は、原本のチェックリストで検出された。ただし A16（全角スペースのインデント）は **YAML としては読めてしまい**、`purpose` が「\u3000 purpose」という別のキーに化けた結果として「meta.purpose が欠けている」が出たもの。原因（全角スペース）は示されない（→ USE-07）。T10 は受領した TASK パケットと同じ誤り（`kd` の代わりに `spec_version`）。
