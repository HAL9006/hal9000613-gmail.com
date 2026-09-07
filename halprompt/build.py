# -*- coding: utf-8 -*-
"""§6 build — 衣装生成 → モジュール合成 → 語数予算配分 → 残留検査 までの一本道。"""

from . import budget, data, lint as lint_mod, modules
from .costume import generate
from .spec import UI_CHECKLIST, format_allocation
from .util import squeeze, word_count


class BuildError(ValueError):
    pass


def resolve_scene(value):
    if value is None:
        return data.SCENES["studio"]
    if value in data.SCENES:
        return data.SCENES[value]
    return value


def resolve_lens(value):
    if value is None:
        return data.LENSES["wide"]
    text = data.LENSES.get(value, value)
    if word_count(text) > data.LENS_MAX_WORDS:
        raise BuildError("原則3違反: カメラ指定は6語以内。指定は %d 語です: %r"
                         % (word_count(text), text))
    return text


def resolve_percept(value):
    if not value:
        return []
    keys = [k.strip().upper() for k in value.split(",") if k.strip()]
    for k in keys:
        if k not in data.PERCEPT_LENSES:
            raise BuildError("未知の PERCEPT LENS: %s（L1-L9）" % k)
    if len(keys) > data.PERCEPT_MAX:
        raise BuildError("原則: PERCEPT LENS は最大%d個です（指定 %d 個）"
                         % (data.PERCEPT_MAX, len(keys)))
    if len(set(keys)) != len(keys):
        raise BuildError("PERCEPT LENS が重複しています: %s" % ",".join(keys))
    return keys


def build(role="bass", vintage=2, subject="fashion", budget_words=data.DEFAULT_BUDGET,
          scene=None, lens=None, percept=None, seed=0, stylize=None, ar=None, fill=True):
    if subject not in data.SUBJECTS:
        raise BuildError("未知の subject: %s（%s）" % (subject, " / ".join(data.SUBJECTS)))
    if budget_words < 20:
        raise BuildError("budget は 20 words 以上を指定してください")

    costume = generate(role=role, vintage=vintage, seed=seed)
    scene_text = resolve_scene(scene)
    lens_text = resolve_lens(lens)
    percept_keys = resolve_percept(percept)

    m4_text = modules.m4(percept_keys, costume.accent)
    variants = modules.build_variants(costume, role, scene_text, lens_text, costume.accent)
    plan = budget.plan(variants, subject, budget_words,
                       percept_words=word_count(m4_text), fill=fill)

    parts = [variants[m][plan["chosen"][m]] for m in plan["order"]]
    if m4_text:
        parts.append(m4_text)
    body = squeeze(" ".join(parts))

    params = ["--stylize %d" % (stylize if stylize is not None else budget.stylize_for(subject))]
    if ar:
        params.append("--ar %s" % ar)
    prompt = body + " " + " ".join(params)

    result = lint_mod.lint(prompt, role=role, percept_keys=percept_keys)
    return {
        "prompt": prompt,
        "body": body,
        "params": " ".join(params),
        "costume": costume,
        "plan": plan,
        "variants": variants,
        "lint": result,
        "percept": percept_keys,
        "scene": scene_text,
        "lens": lens_text,
        "seed": seed,
        "total_words": word_count(body),
    }


def format_build(res):
    from .spec import RULE
    out = [RULE, "PROMPT  seed=%s / role=%s / subject=%s" % (
        res["seed"], res["costume"].role, res["plan"]["subject"]), RULE, res["prompt"], "",
        format_allocation(res["plan"], res["variants"]), "",
        RULE, "残留検査（§5）", RULE, lint_mod.format_report(res["lint"]), "",
        UI_CHECKLIST]
    return "\n".join(out)
