# kd_redesign_20260925 — TOS-EXEC-KD2-001

KD v2 再設計のための一次データ収集（棚卸し・計測のみ。設計提案・評価は含まない）。

## 実行状況

| 項目 | 状態 |
|---|---|
| 集計スクリプト `kd_inventory.py` | 作成済・合成データで動作確認済 |
| 実データでの実行 | **未実行**。この会話の実行環境（クラウド上のGitリポジトリ）には TrinityOS 本体（README_AI.md / _state/ / KD ファイル群）が存在しないため |
| 出力ファイル（下表） | ローカルで下記コマンドを実行すると生成される |

## 実行方法（ローカルのみ・外部通信なし）

```bash
pip install pyyaml            # 未導入の場合のみ
python kd_inventory.py --root <TrinityOSのパス>
# 出力先: <TrinityOS>/_analysis/kd_redesign_20260925/
```

- 対象ファイルは読み取り専用で開く（書き込みは出力フォルダのみ）。
- 出力フォルダ自体と `.git` は走査対象外。
- 使うのは標準ライブラリと PyYAML のみ。ネットワーク通信は行わない。

## 出力一覧

| ファイル | ACTION | 内容 |
|---|---|---|
| `state_snapshot.md` | 1 | README_AI.md の本文と sha256、`_state/` 配下のファイル一覧（size / sha256 / mtime）とテキストファイル本文 |
| `inventory.csv` | 2 | path, size, sha256, mtime(UTC), est_tokens, matched_patterns, encoding |
| `field_stats.csv` | 3 | section, key, value, count, ratio, note（縦持ち） |
| `drift_report.md` | 4 | 仕様外フィールド・独自カテゴリ値・id プレフィックス・最上位キー・派生プロファイル候補・YAML独自タグ・解析モード（出現ファイルと件数のみ） |
| `spec_lineage.md` | 5 | 仕様書の家系ごとに版を日付順に並べ、前版からの追加・削除項目を列挙 |
| `parse_errors.csv` | 6 | path, severity(error/warning), error_type, detail（修正はしない） |
| `kd_inventory.py` | 7 | 集計スクリプト（再実行可能） |
| `run_meta.json` | 7 | 実行時刻・件数・Python/PyYAML の版（時刻を含むのはこのファイルだけ） |

再現性: `inventory.csv` / `field_stats.csv` / `drift_report.md` / `spec_lineage.md` / `parse_errors.csv` / `state_snapshot.md` は、入力ファイルが同じなら再実行しても同じ内容になる（2回実行して md5 一致を確認済）。ただし mtime を使う列は、ファイルをコピーすると変わることがある。

## 計測定義（スクリプトに実装した判定基準）

### 対象パターン（ACTION 2）
ファイル名を大文字小文字を区別せずに照合する。

- `KD_*.yaml` / `KD_*.yml`、`Consolidated_KD*`、`Master_Index*`、`SPEC_Knowledge_Distillate*`、`*KD-DOC*`、`SPEC_UCA_ALS*`、`圧縮言語カタログ*`
- CRL・SMCL・SCF・ICS 関連仕様: ファイル名の拡張子を除いた部分を英数字以外の文字で区切り、`CRL` / `SMCL` / `SCF` / `ICS` のいずれかと完全に一致するトークンがあるもの（例: `CRL_spec.md` は対象、`NOTICS.md` は対象外）。この条件に当てはまらない関連仕様は拾えない。

### 推定 token 数
ASCII 文字は 4 文字で 1 token、非 ASCII 文字は 1 文字で 1 token として数える。デコードできないファイルは bytes ÷ 4。トークナイザ（外部データ）は使わない概算値。

### KD ファイルとブロック（ACTION 3）
- 解析する KD ファイル: `KD_yaml` または `Consolidated_KD` に一致したファイル。`.yaml/.yml` はファイル全体（複数ドキュメント `---` 可）を、`.md` は ```` ```yaml ```` フェンスの中身を解析する。
- YAML のスカラ値はすべて文字列として読む（型推論なし）。未知タグ `!xxx` も値は読み込み、タグの件数を drift_report に記録する。
- ブロックの判定: `id` キーを持つ mapping、またはリストの要素で仕様フィールドを 2 つ以上持つ mapping。ブロックの中に入れ子になった mapping はブロックとして数えない。
- 空欄の判定: null / 空文字 / `~` / `null` / 空リスト / 空 mapping。
- 1 ブロックの文字数: ブロック内の文字列スカラ（キーを含む）の総文字数。
- カテゴリ: `category` フィールドの値の分布と、`id` に含まれる英字トークンが既知カテゴリ語（ARCH/TECH/OPS/PROTO/INS/WARN/SESS）と完全に一致するものを、別々のセクションとして記録する。type 値や id とカテゴリの対応付け（「相当」判断）はしない。

### 仕様書の系譜（ACTION 5）
- 家系: ファイル名から日付（YYYYMMDD 等）と `vX.Y` を除いた文字列でまとめる（機械的な処理）。
- 日付: ファイル名 → 本文の `date/created/updated/作成日/更新日` 行 → mtime の順に採用し、どれを使ったかを列に記録する。
- 版: ファイル名の `vX.Y` → 本文の `version/ver/版` 行。どちらもなければ「不明」。
- 項目: YAML はキーパス、それ以外は Markdown の見出し行。前版との集合差を「追加」「削除」として列挙する。

### parse_errors.csv（ACTION 6）
- `error`: デコード失敗・YAML 構文エラー（行・列付き）。このファイルは集計から除外する。
- `warning`: 重複キー（後に書かれた値で読み込む）/ ブロック判定に一致する mapping がない（NoBlocks）。
