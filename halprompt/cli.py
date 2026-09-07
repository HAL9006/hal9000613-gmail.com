# -*- coding: utf-8 -*-
"""§6 CLI仕様

  halprompt design  --role bass --vintage 2 --seed 777
  halprompt build   --role bass --vintage 2 --subject fashion --budget 150 ...
  halprompt lint    -f prompt.txt
  halprompt artify  -f prompt.txt --level 3

共通: --seed で完全再現。--json で機械可読出力。
"""

import argparse
import json
import sys

from . import artify as artify_mod
from . import build as build_mod
from . import data
from . import lint as lint_mod
from .costume import generate
from .spec import format_design
from .util import word_count


def _read_text(path):
    if path in (None, "-"):
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _add_common(p):
    p.add_argument("--seed", type=int, default=0, help="乱数種。同一 seed で同一出力（既定 0）")
    p.add_argument("--json", action="store_true", help="機械可読（JSON）で出力する")


def make_parser():
    p = argparse.ArgumentParser(
        prog="halprompt",
        description="HAL_9001 用 Midjourney プロンプト生成CLI（決定論・LLM API 不使用・美的判定なし）")
    sub = p.add_subparsers(dest="command")

    d = sub.add_parser("design", help="衣装を生成し適合仕様書を表示する")
    d.add_argument("--role", default="bass", choices=sorted(data.ROLES))
    d.add_argument("--vintage", type=int, default=2, choices=sorted(data.VINTAGES))
    _add_common(d)

    b = sub.add_parser("build", help="完成プロンプト + 配分表 + UI設定チェックリスト")
    b.add_argument("--role", default="bass", choices=sorted(data.ROLES))
    b.add_argument("--vintage", type=int, default=2, choices=sorted(data.VINTAGES))
    b.add_argument("--subject", default="fashion", choices=data.SUBJECTS)
    b.add_argument("--budget", type=int, default=data.DEFAULT_BUDGET, help="語数予算（既定 150）")
    b.add_argument("--scene", default="studio",
                   help="場面。キー(%s)または任意文字列" % "/".join(sorted(data.SCENES)))
    b.add_argument("--lens", default="wide",
                   help="カメラ。キー(%s)または6語以内の文字列" % "/".join(sorted(data.LENSES)))
    b.add_argument("--percept", default=None, help="PERCEPT LENS。例 L6,L4（最大2個）")
    b.add_argument("--stylize", type=int, default=None, help="既定値は subject から決まる（原則6）")
    b.add_argument("--ar", default=None, help="アスペクト比。指定時のみ出力に付す")
    b.add_argument("--no-fill", action="store_true",
                   help="余剰語数の再配分を無効化し、§4 の素の配分だけを使う")
    _add_common(b)

    l = sub.add_parser("lint", help="排他グループの競合を報告する")
    l.add_argument("-f", "--file", default="-", help="対象ファイル（既定は標準入力）")
    l.add_argument("--role", default=None, choices=sorted(data.ROLES),
                   help="指定すると role の除外楽器も検査する")
    l.add_argument("--percept", default=None, help="採用中の PERCEPT LENS。L6 指定時は原則8を検査")
    l.add_argument("--json", action="store_true")

    a = sub.add_parser("artify", help="説明語を削除し、不可解要素・素材の自律・未完了を注入する")
    a.add_argument("-f", "--file", default="-", help="対象ファイル（既定は標準入力）")
    a.add_argument("--level", type=int, default=1, choices=[1, 2, 3],
                   help="1=不可解要素 / 2=+素材の自律 / 3=+未完了")
    _add_common(a)
    return p


def cmd_design(args):
    c = generate(role=args.role, vintage=args.vintage, seed=args.seed).to_dict()
    if args.json:
        print(json.dumps(c, ensure_ascii=False, indent=2))
    else:
        print(format_design(c))
    return 0 if all(x["ok"] for x in c["conformance"]["conditions"]) else 1


def cmd_build(args):
    res = build_mod.build(
        role=args.role, vintage=args.vintage, subject=args.subject,
        budget_words=args.budget, scene=args.scene, lens=args.lens,
        percept=args.percept, seed=args.seed, stylize=args.stylize,
        ar=args.ar, fill=not args.no_fill)
    if args.json:
        print(json.dumps({
            "prompt": res["prompt"],
            "body": res["body"],
            "params": res["params"],
            "seed": res["seed"],
            "scene": res["scene"],
            "lens": res["lens"],
            "percept": res["percept"],
            "plan": res["plan"],
            "lint": res["lint"],
            "costume": res["costume"].to_dict(),
            "words": word_count(res["body"]),
        }, ensure_ascii=False, indent=2))
    else:
        print(build_mod.format_build(res))
    return 0 if res["lint"]["ok"] else 1


def cmd_lint(args):
    text = _read_text(args.file)
    keys = [k.strip().upper() for k in (args.percept or "").split(",") if k.strip()]
    res = lint_mod.lint(text, role=args.role, percept_keys=keys)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(lint_mod.format_report(res))
    return 0 if res["ok"] else 1


def cmd_artify(args):
    text = _read_text(args.file)
    res = artify_mod.artify(text, level=args.level, seed=args.seed)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(res["text"])
        print()
        print(artify_mod.format_report(res))
        for line in res["comments"]:
            print(line)
    return 0


COMMANDS = {"design": cmd_design, "build": cmd_build, "lint": cmd_lint, "artify": cmd_artify}


def main(argv=None):
    parser = make_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return COMMANDS[args.command](args)
    except build_mod.BuildError as exc:
        sys.stderr.write("エラー: %s\n" % exc)
        return 2
    except ValueError as exc:
        sys.stderr.write("エラー: %s\n" % exc)
        return 2
