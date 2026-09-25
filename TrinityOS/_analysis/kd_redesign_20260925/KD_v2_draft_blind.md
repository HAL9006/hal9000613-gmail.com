# KD v2 仕様案（盲検版）— TOS-EXEC-KD2-002

- 作成: 2026-09-25 / 作成者: Claude Code（worker）
- 入力: CC-PACKET TOS-EXEC-KD2-002 の GIVEN_FACTS のみ。TrinityOS 配下のファイルは読んでいない。Web 検索もしていない。
- **盲検条件の開示**: 同じセッションで直前に TOS-EXEC-KD2-001（計測スクリプトの作成）を行った。そのため、KD 仕様8項目と既知カテゴリ7種の名前は事前に知っていた（どちらも本パケットにも書かれている）。TrinityOS の実ファイルは 001 でも存在しなかったので、一度も見ていない。
- 本書の数値・観測はすべてパケット記載の6本に基づく。約929本全体の傾向は**不明**。

---

## 1. 現行KDの問題

### 1.1 事実（パケットの記述から直接言えること）

| # | 事実 | 根拠 |
|---|---|---|
| F1 | v1.0（2026-01-17）以降、仕様は更新されていない。一方、観測6本には少なくとも5種類の異なる形式がある | 仕様履歴、6本の形式 |
| F2 | 4月形式は、ファイル全体としては YAML として妥当でない | 4月の観測 |
| F3 | 7/14形式には id もブロックもない | 7/14の観測 |
| F4 | 7/30形式は、v1.0 の7カテゴリにない id 接頭辞（DIAG/SORT/SKEL/CAV）を使っている | 7/30の観測 |
| F5 | 7/23形式は、v1.0 にないフィールド（truth_type、anchor＋sha256）と派生プロファイル KD-DOC を持つ | 7/23の観測 |
| F6 | 9/07形式はキーが日本語。v1.0 にない要素を持つ（訂正履歴、supersedes、観測と解釈の分離、audience、人間の判断が要る問い、未検証事項） | 9/07の観測 |
| F7 | v1.0 の status に SUPERSEDED はあるが、置き換え先を示すフィールドは必須8項目にない | v1.0 必須項目 |
| F8 | 名前の近い値が2つの軸にある: type の `WARNING` とカテゴリの `WARN`、type の `INSIGHT` とカテゴリの `INS` | v1.0 語彙 |
| F9 | v1.0 の規則「詳細を省略しない・意味変数を多用しない・展開形式」は、利用者の要望「圧縮言語」と方向が逆である | v1.0 規則と要望 |

### 1.2 推測（検証していない。6本からの推論）

| # | 推測 | 推測の根拠 | 確かめる方法 |
|---|---|---|---|
| I1 | 仕様の外側に必要なもの（出典の信頼度、訂正、未解決事項）があり、各セッションがそれぞれ独自に拡張している | F4〜F6 がすべて「追加」の方向 | 001 の drift_report |
| I2 | 全ファイルをまとめて機械パースすることは、現状できない | F2、F3、F6 | 001 の parse_errors |
| I3 | `{CAT}-{NNN}` はファイルやセッションをまたぐと重複する可能性がある | id に日付・セッションの名前空間がない | 全ファイルの id 重複を集計 |
| I4 | 仕様どおりか確かめる仕組み（バリデータ）がない | 形式のずれが9か月放置されている | 利用者に確認 |
| I5 | why の記入率は、ファイルの形式によって差がある | 7/14形式には why を入れる場所がない | 001 の field_stats |
| I6 | 6本が約929本を代表しているかは**不明** | 抽出方法が示されていない | 001 の inventory |

---

## 2. KD v2 仕様案

### 2.1 ファイル形式

| 決定 | why |
|---|---|
| 1ファイル＝1つの妥当な YAML ドキュメント（UTF-8、JSON に変換できる範囲のみ。アンカー・独自タグは使わない） | F2 の再発を防ぎ、パーサの差による揺れをなくすため |
| キーは英小文字 ASCII に固定。値の言語は自由（日本語可） | F6 の日本語キーと v1 の英語キーが混ざるとパースが割れるため。値を日本語にすればニュアンスは失われない |
| 人が読むための Markdown は YAML から生成する。手書きの Markdown は KD として扱わない | 4月形式（Markdown＋フェンス）の目的は、読みやすさだったと推測している。生成で代替すれば、正本が1つに保たれる |
| ファイル名: `KD_{YYYYMMDD}_{session}_{slug}.yaml` | 並び順と由来をファイル名だけで分かるようにするため |

### 2.2 ファイルヘッダ（必須）

```yaml
kd_version: "2.0"
profile: core            # core | doc（2.5節）
file_id: KD_20260925_S0123_kd-redesign
session: S0123
created: 2026-09-25
layer: daily             # daily | consolidated（master index は生成物）
audience: [ai]           # ai | human（F6の audience を正式化）
blocks: [...]
handoff: {...}           # 2.4節
```

### 2.3 ブロック

| フィールド | 必須 | 型・語彙 | why |
|---|---|---|---|
| `id` | 必須 | `{CAT}-{YYMMDD}-{NNN}` 例 `ARCH-260925-001` | I3（重複の可能性）への対策。日付を名前空間にすれば、セッションをまたいでも一意になる |
| `cat` | 必須 | カテゴリ登録簿（registry）にあるもの | F4 から新カテゴリの需要は実在する。自由に増やすのでも禁止するのでもなく、登録制にする |
| `type` | 必須 | DECISION, INSIGHT, RULE, WARNING, PROCEDURE, DEFINITION, **OBSERVATION**, **QUESTION** | F6 の「観測と解釈の分離」を type で表す。観測＝OBSERVATION、解釈＝INSIGHT。v1 の6値はそのまま残し、移行時に値を変換しなくて済むようにする |
| `status` | 必須 | CONFIRMED, TENTATIVE, DEPRECATED, SUPERSEDED | v1 と同じ。語彙を変える根拠がないため |
| `title` | 必須 | 1行 | Master Index に載せ、どのブロックを読み込むか選ぶ材料にするため |
| `content` | 必須 | 自由記述 | v1 と同じ |
| `why` | 必須（空文字は不可） | 自由記述。理由が不明なら `null` と書き、`why_unknown: true` を付ける | KD の目的は WHY の保持。空欄と「理由不明」を区別できるようにする |
| `source` | 必須 | 2.3.1 のリスト | v1 の source_ref に、F5 の truth_type と anchor を統合する |
| `supersedes` / `superseded_by` | status が SUPERSEDED のとき必須 | id のリスト | F7（置き換え先が書けない）の解消。F6 で需要が観測されている |
| `revisions` | 任意 | `[{date, change, reason}]` | F6 の訂正履歴を正式化する |
| `unverified` | 任意 | 文字列のリスト | F6 の未検証事項を正式化する |
| `tags` | 任意 | 文字列のリスト | v1 では必須だったが、なくても意味が損なわれないため任意に下げる（ここは判断。001 の実測で覆ることがある） |

#### 2.3.1 source

```yaml
source:
  - ref: "session S0123 / 会話ログ"
    truth: OBSERVED     # OBSERVED | DOCUMENT | EXPERT | DERIVED | ASSUMED
    anchor: null        # profile=doc かつ truth=DOCUMENT のとき必須
    sha256: null        # 同上
```

why: F5 の truth_type（DOCUMENT/EXPERT/DERIVED）に、OBSERVED（直接観測したもの）と ASSUMED（前提として置いたもの）の2値を加える。観測と解釈を、出典の側からも区別できるようにするため。

### 2.4 handoff（v1 の new_session_prompt を置き換える）

```yaml
handoff:
  next_actions: ["..."]
  human_questions: ["..."]   # 人間の判断が要る問い（F6）
  unverified: ["..."]        # ファイル単位の未検証事項
  prompt: "..."              # 旧 new_session_prompt。任意
```

why: 7/14形式（引継ぎの節）と9/07形式（人間の判断が要る問い）に、同じ需要が独立して現れている。自由文1本では、次のAIが「作業」「問い」「未検証」を区別できない。

### 2.5 プロファイル

| profile | 追加の必須条件 | why |
|---|---|---|
| core | なし | 既定 |
| doc | truth=DOCUMENT の source に anchor と sha256 が必須 | F5 の KD-DOC を仕様として取り込む。KD-DOC の元の定義は見ていないため、この条件は**推測による再構成** |

新しいプロファイルは、この仕様書に追記してから使う（登録制）。

### 2.6 運用層

| 層 | 作り方 | 変更 | why |
|---|---|---|---|
| Daily | セッションごとに手書き | 追記のみ | v1 の3層構造を踏襲する |
| Consolidated | Daily を統合する。重複の解消は supersedes で記録する | ブロックは削除しない。status で無効化する | 過去の判断とその理由（WHY）を消さないため |
| Master Index | **スクリプトで生成**（id, cat, type, status, title, file, sha256） | 手で編集しない | 手書きの索引は本体とずれる。F1 と同じ種類のずれを防ぐため |

加えて、**バリデータ**（JSON Schema と lint）を v2 の一部とする。検証を通らなかった KD は Consolidated に取り込まない。why: I4。

---

## 3. 「圧縮言語化」の採否

**判断: 部分的に採用する。構造は圧縮する。content と why の文章は圧縮しない。**

| 方式 | 採否 | 得るもの | 失うもの・リスク |
|---|---|---|---|
| A. 独自の略語・記号体系で content/why を書く | 不採用 | token の削減（削減量は**不明**。実測していない） | WHY のニュアンスが失われる。辞書の版とモデルに依存する。人が監査できない。F9 により v1 の設計意図とも反する |
| B. 固定語彙（enum）と短い固定キー | 採用 | 解釈の揺れがなくなる。検証できる | 語彙を追加するには手続きが要る |
| C. id 参照による重複の除去（同じ内容は参照で書く） | 採用 | 繰り返しが減る | 参照先を読み込まないと意味が取れない |
| D. 読み込みの選択（Master Index の title/cat/status で、必要なブロックだけ読む） | 採用 | 1回の読み込み量が減る。効果が最も大きいと推測するが、**未検証** | 索引の品質に依存する |
| E. 1行要約フィールド `gist`（任意）を索引用に置く | 保留 | 選択の精度が上がる | 要約と本文の二重管理になる |

理由: 「AI同士専用」だとしても、KD の目的（WHY の継承）は、解釈にずれがあると守れない。圧縮で得られる token 削減の大きさは不明で、失うもの（理由の欠落、監査できなくなること）はすでに F9 として仕様の意図に書かれている。そこで、削減の手段を「書き方」ではなく「読み込み方」（C と D）に置く。
再検討する条件: 001 の実測で KD の読み込み量がセッションの予算を圧迫していると分かり、かつ C と D では足りないと実測で示された場合、A を限定した範囲（たとえば tags と title だけ）で試す。

---

## 4. 既存約929本の移行方針

1. **原本は変更しない。** 変換は新しいファイルとして作り、`migrated_from: {path, sha256}` を付ける。why: 元に戻せること、GUARD-013 に反する変換を後から検証できること。
2. **形式の分類を先に行う。** 001 の出力をもとに、全ファイルを形式ラベル（仮に A=4月型、B=自由節型、C=v1準拠、D=独自接頭辞、E=日本語キー報告書型、U=不明）に機械的に振り分ける。6本から立てた5形式がすべてを覆うかどうかは**不明**。
3. **Master Index v2 は全件を対象にする。** 変換していないファイルも `v2_status: legacy` として索引に載せる。why: 検索できる状態を先に作れば、本体の変換は後回しにできる。
4. **変換は必要になったものから行う（遅延移行）。** 優先順位: Consolidated → 参照されたもの → 残り。why: 全件を一括変換するコストに見合う効果があるかは不明で、古い知見がどれだけ含まれるかも不明。
5. **欠けている値は推測で埋めない。** why がなければ `why: null` と `why_unknown: true`。id がなければ `LEGACY-{file_id}-{NNN}` を振る。v1 の type/cat とどう対応するか判定できないもの（例: DIAG）は、`cat: UNMAPPED` と `original: "DIAG"` を記録し、登録簿に加えるかどうかは人間が判断する。
6. 変換ができたかどうかは、バリデータを通ったかどうかで判定する。

---

## 5. 変換例（**内容はすべて架空**。形式だけを示す）

### 5.1 4月形式 → v2

変換前（Markdown＋ブロックごとの yaml フェンス）:

````markdown
## 設計判断
```yaml
id: ARCH-003
type: DECISION
status: CONFIRMED
title: ログは日次で分割
content: ログファイルを日付ごとに分ける
source_ref: 4/12 セッション
why: 1ファイルが肥大して読み込めなかった
tags: [log]
```
````

変換後:

```yaml
kd_version: "2.0"
profile: core
file_id: KD_20260412_LEGACY_april-sample
session: UNKNOWN            # 原本に記載がないため
created: 2026-04-12         # ファイル名の日付を採用（原本本文には記載なし）
layer: daily
audience: [ai]
migrated_from: {path: "(原本パス)", sha256: "(原本ハッシュ)"}
blocks:
  - id: ARCH-260412-003     # 旧 ARCH-003
    cat: ARCH
    type: DECISION
    status: CONFIRMED
    title: ログは日次で分割
    content: ログファイルを日付ごとに分ける
    why: 1ファイルが肥大して読み込めなかった
    source:
      - {ref: "4/12 セッション", truth: UNKNOWN, anchor: null, sha256: null}   # Q5 の案A
    tags: [log]
handoff: {next_actions: [], human_questions: [], unverified: []}
```

補足: 原本には出典の種類が書かれていない。種類を推測で決めること（たとえば ASSUMED を入れること）は GUARD-013 に触れるので行わない。上の例は、移行ブロックに限って `truth: UNKNOWN` を許す案Aで書いた。もう一つの案B は、`truth` を空欄のままにして検証エラーとして残す方式。どちらにするかは**未決**（6.2 Q5）。

### 5.2 9/07形式（日本語キー報告書型）→ v2

変換前:

```yaml
報告: 分類処理の遅延
観測:
  - 9/06 の実行で処理時間が前回の3倍
解釈:
  - 入力件数の増加が原因と考える
訂正履歴:
  - 9/07 初版の「2倍」を「3倍」に訂正
supersedes: OPS-012
audience: AI
人間の判断が要る問い:
  - 夜間バッチに移すか
未検証事項:
  - 入力件数の実数
```

変換後:

```yaml
kd_version: "2.0"
profile: core
file_id: KD_20260907_LEGACY_sort-delay
session: UNKNOWN
created: 2026-09-07
layer: daily
audience: [ai]
migrated_from: {path: "(原本パス)", sha256: "(原本ハッシュ)"}
blocks:
  - id: OPS-260907-001
    cat: OPS                  # 原本にカテゴリなし。supersedes 先が OPS なので OPS とした（人間の確認を要する）
    type: OBSERVATION
    status: CONFIRMED
    title: 分類処理の時間が前回の3倍
    content: 9/06 の実行で処理時間が前回の3倍
    why: null
    why_unknown: true
    source: [{ref: "9/06 実行", truth: OBSERVED, anchor: null, sha256: null}]
    revisions: [{date: 2026-09-07, change: "2倍→3倍", reason: "(原本に記載なし)"}]
  - id: OPS-260907-002
    cat: OPS
    type: INSIGHT
    status: TENTATIVE
    title: 遅延の原因は入力件数の増加（解釈）
    content: 入力件数の増加が原因と考える
    why: 観測 OPS-260907-001 からの解釈
    source: [{ref: "OPS-260907-001", truth: DERIVED, anchor: null, sha256: null}]
    supersedes: [OPS-012]     # 原本はファイル単位の supersedes。どのブロックに付くかは不明なため、仮にここに置いた
    unverified: ["入力件数の実数"]
handoff:
  next_actions: []
  human_questions: ["夜間バッチに移すか"]
  unverified: ["入力件数の実数"]
```

この変換で解釈が入った箇所（`cat` の決定、`supersedes` を付けたブロック）はコメントで明示した。移行時には、この種の判断を `migration_notes` に記録する案を 6.2 に挙げている。

---

## 6. 前提・未解決の問い・設計を変えうるデータ

### 6.1 前提
- P1: KD を主に読むのは AI、主に書くのも AI。人間は監査する役割（audience の設定から推測）。
- P2: KD の読み込み量には上限がある（コンテキストの制約）。上限の値は**不明**。
- P3: 観測6本は、形式の種類をおおむね示している。ただし比率は示していない。
- P4: YAML パーサが使える環境で運用する。

### 6.2 未解決の問い（人間の判断が要る）
- Q1: 「圧縮言語」で本当に解決したい問題は何か。token 量、読み込み時間、書く手間、ほかの AI との互換性のどれか。答えによって3節の判断が変わる。
- Q2: KD-DOC の元の定義は何か（2.5節は推測による再構成）。
- Q3: DIAG/SORT/SKEL/CAV を登録簿に正式に加えるか。
- Q4: 人間も直接読む KD は存在するか。存在するなら、Markdown を生成するだけで足りるか。
- Q5: 出典の種類が不明な移行ブロックは、`truth: UNKNOWN` を許すか、検証エラーとして残すか。
- Q6: ファイル単位の supersedes を、どのブロックに付けるかのルール。
- Q7: 約929本という数は、どこまでを数えた推定か（Daily/Consolidated/Master Index のすべてを含むか）。

### 6.3 どのデータがあれば設計が変わるか

| データ（主に 001 の出力） | 変わりうる判断 |
|---|---|
| inventory.csv の token 数の合計と分布 | 3節（圧縮の採否）。読み込み量が小さければ、C と D も優先度が下がる |
| field_stats.csv の why の空欄率 | why を必須のまま維持するか（空欄が多いなら、書く側の支援が先） |
| field_stats.csv の tags と source_ref の使用率 | 2.3節の必須と任意の区分 |
| drift_report.md の仕様外フィールドの一覧と件数 | 2.3節に正式に取り込むフィールドの選定 |
| drift_report.md の id 接頭辞の件数 | カテゴリ登録簿の初期内容 |
| parse_errors.csv の件数と種類 | 4節の移行の順序と自動化の範囲 |
| spec_lineage.md（v1.0 以外の仕様書が存在するか） | 前提 F1 そのものが崩れる可能性 |
| id の重複の実数 | 2.3節の id 形式（I3 が偽なら、日付による名前空間は不要） |
