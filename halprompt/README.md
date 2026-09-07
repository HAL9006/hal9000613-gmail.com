# halprompt

HAL_9001 用 Midjourney プロンプト生成CLI。

- 全処理が**決定論的な計算**。同一 seed・同一引数で完全に同一の出力になる。
- **LLM API を呼ばない。ネットワーク通信をしない**（LOCAL SOVEREIGNTY / localhost のみ）。
- 依存は **Python 標準ライブラリのみ**（Python 3.8+ で動作。開発は 3.11）。
- **美的判定を実装していない。** 判定するのは「規格に適合しているか（§2-2）」と
  「矛盾が残っていないか（§5）」の2つだけである。

---

## 使い方

リポジトリのルートで実行する。

```bash
# 衣装を生成して適合仕様書を見る
python3 -m halprompt design --role bass --vintage 2 --seed 777

# 完成プロンプト + 配分表 + UI設定チェックリスト
python3 -m halprompt build --role bass --vintage 2 --subject fashion --budget 150 \
        --scene studio --lens "Ultra wide angle, two meters back" \
        --percept L6,L4 --seed 777

# 残留検査だけを回す
python3 -m halprompt build --seed 777 > prompt.txt
python3 -m halprompt lint -f prompt.txt --role bass

# 説明語を削り、不可解要素・素材の自律・未完了を注入する
python3 -m halprompt artify -f prompt.txt --level 3 --seed 777
```

共通オプション: `--seed`（既定 0・完全再現）、`--json`（機械可読出力）。
終了コードは 0=正常 / 1=規格不適合または lint 競合 / 2=引数エラー。

### 主なオプション

| オプション | 既定 | 内容 |
|---|---|---|
| `--role` | bass | piano / bass / guitar / violin / synth / organ（§1-6） |
| `--vintage` | 2 | 1 新造 / 2 中古 / 3 放棄（§1-5） |
| `--subject` | fashion | fashion / performance / scene / none（§4） |
| `--budget` | 150 | 語数の**上限**（目標ではない） |
| `--scene` | studio | studio / street / ruin / hall、または任意文字列 |
| `--lens` | wide | wide / floor / overhead / behind / edge / tilt / none、または6語以内の文字列 |
| `--percept` | なし | L1〜L9 をカンマ区切りで最大2個 |
| `--stylize` | subject 依存 | 原則6の既定値を上書きする |
| `--ar` | なし | 指定時のみパラメータ部に付す |
| `--fill` | 無効 | 余った語数で上位バリアントに昇格させる。**既定では行わない**（予算は上限であって目標ではない） |
| `--no-fill` | — | 余剰再配分を明示的に無効化する（既定と同じ。`--fill` を打ち消す） |

---

## 構造

```
halprompt/
  data.py      §1 データ定義（柄クラス・色と明度・ゾーン・シルエット・年式・用途等級）
  costume.py   §2 衣装生成器（規格適合するまで最大300回再計算）
  modules.py   §3 モジュール合成（M0 FASHION / M1 PERFORMANCE / M2 ANDROID+ENV / M3 FINISH / M4 PERCEPT）
  budget.py    §4 語数予算配分
  lint.py      §5 残留検査
  artify.py    §7 artify
  spec.py      適合仕様書・配分表・UI設定チェックリストの整形
  build.py     §6 build の一本道
  cli.py       §6 CLI
  tests/       検証（規格適合・再現性・予算・lint・8原則・美的判定の不在）
```

テスト:

```bash
python3 -m unittest discover -s halprompt/tests -t .
```

---

## 8原則の実装位置

| 原則 | 実装 |
|---|---|
| 1 前方スロットは有限 | `budget.plan()` が subject モジュールを配置順の先頭に置く |
| 2 楽器語は2語以内 | `data.ROLES[*]["instrument"]`（テストで検査） |
| 3 カメラ指定は6語以内 | `build.resolve_lens()` が7語以上を拒否する |
| 4 アクセント色は物体に結びつける | M3 の全バリアントが `at her lips` を持つ |
| 5 逆光指定時は fill を併記 | M2 の long/mid が `soft fill` を必ず含む |
| 6 stylize 既定値 | `budget.stylize_for()`（fashion 300 / performance 400 / none 600 / scene 500） |
| 7 UI設定チェックリスト | `spec.UI_CHECKLIST` を build 出力末尾に付す |
| 8 L6 採用時の blur 排他 | `lint._blur_violations()` |

`--stylize` の既定値は subject=scene → 500 を含む（原則6の補間。発注側で採用済み）。

## 冗長検査（REDUNDANCY / §5 に追加）

`lint` は排他グループに加えて重複も検出する。**重複の有無だけ**を見る検査であり、
文章の良し悪し・可読性・自然さは評価しない。

1. **楽器名の反復** — `upright piano` / `double bass` / `electric guitar` /
   `violin` / `synthesizer` / `Hammond organ` が本文中に2回以上出たら警告
2. **同義句の同居** — `clear of her body` × `leaned away`、`strong backlighting` × `backlit` など5組
3. **3-gram の重複** — 3語のスライディングウィンドウで同一 3-gram が2回以上。
   ストップワードのみの 3-gram は数えない（句読点は無視するため、文をまたぐ 3-gram も拾う）

衣装生成器（§2）は、規格適合（§2-2）に加えてこの冗長検査を自分の断片に掛け、
重複が残る案は再計算する。判定は「規格に適合しているか」と「矛盾が残っていないか」の2つのままである。

---

## 語数予算は「上限」である

`--budget` は目標ではなく**上限**。下回るのは正常な出力であり、警告しない。

```
テキストが短い → moodboard / profile の支配率が上がる → 芸術寄りの出力
テキストが長い → テキストが支配する      → 説明可能・設計寄りの出力
```

どちらも正しい出力なので、予算を埋めるために長い版へ昇格させることは既定では行わない
（原則1「前方スロットは有限」に反し、意味の予算が薄まる方向に働くため）。
昇格が欲しい時だけ `--fill` を付ける。

配分の手順（§4）:

1. M4 PERCEPT LENS の語数を先に予約し、残りを M0〜M3 の予算とする
2. subject のモジュールに 45%、残り3モジュールに残余を均等配分
3. 各モジュールについて、割当語数を超えない最長のバリアントを選ぶ
4. 上限を超えていれば M3 → M2 → M1 → M0 の順に1段ずつ落とす。
   subject のモジュールは**他が尽きた時だけ**落とす（最後まで落とさない）
5. `--fill` 指定時のみ、上限を超えない範囲で1段ずつ上げ直す

全モジュールが short でも上限に収まらない場合だけ、配分表に警告行を出す。
これは黙って外さないための行であり、**未達の警告は出さない**。

この処理に判断は一切含まれない。全て決定論である。

---

## パケット仕様からの明示的な差分

実装にあたり、仕様が一意に定まらなかった箇所と、その決定。

1. **M1 の二人目の奏者** — テンプレートは `a humanoid pianist` 固定だが、
   `--role piano` では「二人とも pianist」になり "two players only" と矛盾する。
   role の奏者名と重複する場合のみ `a humanoid bassist` に差し替える（`data.SECOND_PLAYER_*`）。
2. **`{role}ist`** — piano→pianoist のような語を避け、role ごとに奏者名を持つ
   （pianist / bassist / guitarist / violinist / synthesist / organist）。
3. **subject=scene の stylize 既定値** — 原則6に記載が無いため、
   performance(400) と none(600) の中間 500 とした。`--stylize` で上書きできる。
4. **高視認色の面積** — ZONE_C の面積は 12% だが条件(4)は「面積 ≤ 0.10」。
   高視認色は ZONE_C の**前景**に置かれるものとして、柄クラスごとの前景比
   （P1 0.35 / P2 0.50 / P3 0.45 / P4 1.00）を掛けた値を面積とする。
   したがって ZONE_C が無地(P4)になった案は条件(4)で落ち、再計算される。
5. **§4 の余剰再配分** — 既定で無効。`--fill` 指定時のみ動く（AMEND2 で確定）。
6. **lint の対象外** — パラメータ部（`--` 以降）に加え、
   `#` で始まる行（UI設定チェックリスト）も検査対象外とする。

---

## 既知の相互作用（仕様通りだが、目視の対象）

- **ZONE_C は ZONE_A とだけ異クラスであればよい。** ZONE_B と同じクラスになることがあり、
  その場合はクラス一意性 0.6 が効いて ID_score が下がる。落ちれば再計算される。
- **条件(5) D は常に 0.75 以上になる。** 定数項 0.25 が2つあり、
  3クラス使用も設計上常に真であるため。大柄の有無だけが 0.75 / 1.00 を分ける。

---

## この道具が計算しないこと

```
判定できるもの（実装する）:
  規格に適合しているか       AWC-1 の6条件
  矛盾が残っていないか       楽器・編成・姿勢・場所・レンズの競合
  予算内に収まっているか     語数

判定できないもの（実装しない）:
  これは良いか
  これは作品か
  この不可解要素を採用すべきか

後者は道具の外にある。
生成された候補を捨てる判断は人間が握る。
その判断の回数と基準が、この作品群の作品性そのものである。
```

コードベースに美的判定の関数は存在しない。次の grep が空であることで確認できる。

```bash
grep -rniE "def .*(beaut|aesthet|artist|taste|quality|masterpiece|is_good|is_bad)" halprompt/*.py
```

（`aesthetics` の語は M3 の英語断片「Helmut Newton and Man Ray aesthetics」に
文字列として現れるが、これはプロンプトの語彙であって判定器ではない。）
