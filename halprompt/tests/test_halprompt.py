# -*- coding: utf-8 -*-
"""halprompt の検証。

ここで検査するのは「規格に適合しているか」「矛盾が残っていないか」「再現するか」だけである。
出力の良し悪しは検査しない（そもそも実装していない）。
"""

import os
import re
import unittest

from halprompt import artify as artify_mod
from halprompt import budget as budget_mod
from halprompt import data, lint, modules
from halprompt.build import BuildError, build
from halprompt.costume import generate
from halprompt.util import word_count

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = [os.path.join(PKG_DIR, f) for f in sorted(os.listdir(PKG_DIR)) if f.endswith(".py")]

ROLES = sorted(data.ROLES)
SEEDS = [0, 1, 7, 42, 777, 9001]


def read_sources():
    out = {}
    for path in SOURCES:
        with open(path, "r", encoding="utf-8") as fh:
            out[os.path.basename(path)] = fh.read()
    return out


class TestDeterminism(unittest.TestCase):
    """同一 seed・同一引数で完全に同一の出力が得られること。"""

    def test_design_reproducible(self):
        for seed in SEEDS:
            a = generate("bass", 2, seed).to_dict()
            b = generate("bass", 2, seed).to_dict()
            self.assertEqual(a, b)

    def test_build_reproducible(self):
        for seed in SEEDS:
            kw = dict(role="guitar", vintage=3, subject="scene", budget_words=150,
                      scene="ruin", lens="tilt", percept="L6,L4", seed=seed)
            self.assertEqual(build(**kw)["prompt"], build(**kw)["prompt"])

    def test_seed_changes_output(self):
        prompts = {build(role="bass", seed=s)["prompt"] for s in SEEDS}
        self.assertGreater(len(prompts), 1)

    def test_artify_reproducible(self):
        text = build(seed=777)["prompt"]
        for level in (1, 2, 3):
            a = artify_mod.artify(text, level=level, seed=5)["text"]
            b = artify_mod.artify(text, level=level, seed=5)["text"]
            self.assertEqual(a, b)


class TestConformance(unittest.TestCase):
    """§2-2 の6条件。"""

    def test_all_costumes_conform(self):
        for seed in SEEDS:
            for role in ROLES:
                for vintage in (1, 2, 3):
                    c = generate(role, vintage, seed)
                    failed = [x["label"] for x in c.conformance["conditions"] if not x["ok"]]
                    self.assertEqual(failed, [], "seed=%s role=%s vintage=%s" % (seed, role, vintage))
                    self.assertLessEqual(c.attempts, 300)

    def test_delta_l_floor(self):
        for seed in SEEDS:
            c = generate("bass", 2, seed)
            for z in c.zones.values():
                self.assertGreaterEqual(z.delta_l, data.DELTA_L_MIN)

    def test_single_high_vis_colour_under_ten_percent(self):
        for seed in SEEDS:
            c = generate("violin", 2, seed)
            self.assertIn(c.accent, data.HIGH_VIS_COLORS)
            self.assertLessEqual(c.accent_area, 0.10)
            self.assertEqual(c.zone("ZONE_C").fg, c.accent)
            others = [z.fg for k, z in c.zones.items() if k != "ZONE_C"]
            self.assertFalse([x for x in others if x in data.HIGH_VIS_COLORS])

    def test_zone_rules(self):
        for seed in SEEDS:
            c = generate("organ", 3, seed)
            self.assertIn(c.zone("ZONE_A").pattern, ("P1", "P3"))
            self.assertNotEqual(c.zone("ZONE_B").pattern, c.zone("ZONE_A").pattern)
            self.assertNotEqual(c.zone("ZONE_B_UNDER").pattern, c.zone("ZONE_A").pattern)
            self.assertNotEqual(c.zone("ZONE_B_UNDER").pattern, c.zone("ZONE_B").pattern)
            self.assertNotEqual(c.zone("ZONE_C").pattern, c.zone("ZONE_A").pattern)

    def test_zone_d_never_covered(self):
        for seed in SEEDS:
            for vintage in (1, 2, 3):
                text = " ".join(generate("piano", vintage, seed).fragments().values()).lower()
                for term in data.ZONE_D_FORBIDDEN_TERMS:
                    self.assertNotIn(term, text)

    def test_forbidden_colours_never_used(self):
        for seed in SEEDS:
            text = " ".join(generate("synth", 2, seed).fragments().values()).lower()
            for term in data.FORBIDDEN_COLOR_TERMS:
                self.assertFalse(re.search(r"\b%s\b" % re.escape(term), text), term)

    def test_pattern_dimensions_within_spec(self):
        for seed in SEEDS:
            for z in generate("bass", 2, seed).zones.values():
                spec = data.PATTERN_CLASSES[z.pattern]
                if spec["min_mm"] is None:
                    self.assertIsNone(z.dim_mm)
                else:
                    self.assertGreaterEqual(z.dim_mm, spec["min_mm"])
                    self.assertLessEqual(z.dim_mm, spec["max_mm"])

    def test_three_variants_exist_and_are_ordered(self):
        for seed in SEEDS:
            f = generate("bass", 2, seed).fragments()
            self.assertGreater(word_count(f["long"]), word_count(f["mid"]))
            self.assertGreater(word_count(f["mid"]), word_count(f["short"]))


class TestBudget(unittest.TestCase):
    """§4 語数予算配分。"""

    def test_within_budget(self):
        """budget は上限。下回るのは正常な出力である。"""
        for seed in (0, 7, 777):
            for role in ROLES:
                for subject in data.SUBJECTS:
                    for b in (100, 130, 150, 170, 190):
                        for fill in (False, True):
                            res = build(role=role, subject=subject, budget_words=b,
                                        seed=seed, fill=fill)
                            self.assertLessEqual(
                                word_count(res["body"]), b,
                                "%s/%s/%d/fill=%s" % (role, subject, b, fill))

    def test_under_budget_never_warns(self):
        """予算未達は正常。警告に値しない。"""
        for b in (150, 200, 300, 400):
            for subject in data.SUBJECTS:
                res = build(subject=subject, budget_words=b, seed=3)
                self.assertLessEqual(word_count(res["body"]), b)
                self.assertEqual([n for n in res["plan"]["notes"] if n.startswith("警告")], [])

    def test_over_budget_always_warns(self):
        """最短構成でも上限に収まらない場合だけ、理由を添えて警告する。"""
        for b in (30, 40, 60):
            for subject in data.SUBJECTS:
                res = build(subject=subject, budget_words=b, seed=3)
                if word_count(res["body"]) > b:
                    self.assertTrue([n for n in res["plan"]["notes"] if n.startswith("警告")],
                                    "budget=%d subject=%s" % (b, subject))

    def test_fill_is_opt_in(self):
        """既定では余剰再配分を行わない。--fill の時だけ動く。"""
        default = build(subject="fashion", budget_words=150, seed=777)
        self.assertEqual([n for n in default["plan"]["notes"] if "余剰再配分" in n], [])
        filled = build(subject="fashion", budget_words=150, seed=777, fill=True)
        self.assertGreaterEqual(word_count(filled["body"]), word_count(default["body"]))
        self.assertLessEqual(word_count(filled["body"]), 150)

    def test_subject_module_is_first(self):
        for subject, module in budget_mod.SUBJECT_MODULE.items():
            res = build(subject=subject, seed=11)
            self.assertEqual(res["plan"]["order"][0], module)
            self.assertTrue(res["plan"]["rows"][0]["is_subject"])
            head = res["variants"][module][res["plan"]["chosen"][module]]
            self.assertTrue(res["body"].startswith(head.split(".")[0]))

    def test_subject_module_never_degraded_below_others(self):
        """subject のモジュールは最後まで落とさない。"""
        res = build(subject="fashion", budget_words=60, seed=2)
        rank = {"short": 0, "mid": 1, "long": 2}
        chosen = res["plan"]["chosen"]
        self.assertGreaterEqual(rank[chosen["M0"]], min(rank[chosen[m]] for m in ("M1", "M2", "M3")))

    def test_allocation_shares(self):
        alloc = budget_mod.allocate("fashion", 150)
        self.assertAlmostEqual(alloc["M0"], 67.5)
        for m in ("M1", "M2", "M3"):
            self.assertAlmostEqual(alloc[m], 27.5)
        even = budget_mod.allocate("none", 200)
        for m in modules.MODULE_IDS:
            self.assertAlmostEqual(even[m], 50.0)

    def test_default_stays_within_allocation(self):
        res = build(subject="fashion", budget_words=150, seed=4)
        for row in res["plan"]["rows"]:
            if row["variant"] != "short":
                self.assertLessEqual(row["words"], row["allocated"])


class TestLint(unittest.TestCase):
    """§5 残留検査。"""

    def test_built_prompts_pass(self):
        for seed in (0, 7, 777):
            for role in ROLES:
                for subject in data.SUBJECTS:
                    for scene in sorted(data.SCENES):
                        res = build(role=role, subject=subject, scene=scene, seed=seed)
                        self.assertTrue(res["lint"]["ok"],
                                        "%s %s %s: %s" % (role, subject, scene, res["lint"]))

    def test_detects_instrument_conflict(self):
        r = lint.lint("She is holding a grand piano and an electric guitar.")
        self.assertFalse(r["ok"])
        self.assertEqual(r["conflicts"][0]["group"], "楽器")

    def test_accompaniment_scope_is_ignored(self):
        r = lint.lint("Holding a double bass, a trio behind her with a grand piano and drums.")
        self.assertTrue(r["ok"], r)
        self.assertIn("grand piano", r["instruments_out_of_scope"])

    def test_primary_marker_reopens_scope(self):
        r = lint.lint("A trio in the background, then she is holding a grand piano "
                      "while an electric guitar rests on her.")
        self.assertFalse(r["ok"])

    def test_detects_posture_place_lens_conflicts(self):
        self.assertFalse(lint.lint("She is seated, standing behind the desk.")["ok"])
        self.assertFalse(lint.lint("An empty concert hall on a street corner.")["ok"])
        self.assertFalse(lint.lint("Ultra wide angle shot with a prime lens.")["ok"])
        self.assertFalse(lint.lint("Monochrome image rendered in full color.")["ok"])
        self.assertFalse(lint.lint("Full body view, a close-up of her face.")["ok"])
        self.assertFalse(lint.lint("Blonde hair, black hair.")["ok"])

    def test_parameters_and_comments_excluded(self):
        body = "Holding a double bass. --style raw --hall --piano"
        self.assertTrue(lint.lint(body)["ok"])
        self.assertTrue(lint.lint("Holding a double bass.\n# grand piano hall")["ok"])

    def test_role_exclusions(self):
        r = lint.lint("Holding a double bass beside a grand piano.", role="bass")
        self.assertIn("grand piano", r["role_violations"])


class TestVocabulary(unittest.TestCase):
    """修正1: 柄語彙に色名を含めない。配色は §1-2 が独立に決める。"""

    COLOUR_WORDS = sorted(set(list(data.BASE_COLORS) + list(data.HIGH_VIS_COLORS)
                              + ["ochre", "beige", "grey", "gray", "white", "red"]))

    def test_pattern_vocabulary_has_no_colour(self):
        for key, spec in data.PATTERN_CLASSES.items():
            for vocab in spec["vocab"]:
                for colour in self.COLOUR_WORDS:
                    self.assertNotIn(colour, vocab.lower(), "%s: %s" % (key, vocab))

    def test_no_colour_word_collides_with_colourway(self):
        """「色名を含む柄語 + 別の配色指定」が同居しないこと。"""
        for seed in SEEDS + [3, 11, 55]:
            for vintage in (1, 2, 3):
                c = generate("bass", vintage, seed)
                for z in c.zones.values():
                    for colour in self.COLOUR_WORDS:
                        if colour in z.vocab.lower():
                            self.assertIn(colour, (z.fg.lower(), z.bg.lower()),
                                          "%s / %s on %s" % (z.vocab, z.fg, z.bg))


class TestRedundancy(unittest.TestCase):
    """修正3: 冗長検査。重複の有無だけを見る。"""

    def test_repeated_instrument(self):
        r = lint.lint("Holding a double bass, the double bass leaned away.")
        self.assertFalse(r["ok"])
        self.assertIn("double bass ×2", [f["detail"] for f in r["redundancy"]])

    def test_synonym_pair(self):
        r = lint.lint("The instrument leaned away, held clear of her body.")
        self.assertIn("同義句の同居", [f["kind"] for f in r["redundancy"]])

    def test_repeated_trigram(self):
        r = lint.lint("A wide stripe bodice over a wide stripe skirt.")
        self.assertIn("3-gramの重複", [f["kind"] for f in r["redundancy"]])

    def test_stopword_only_trigram_ignored(self):
        r = lint.lint("It is the same as it is the same.")
        self.assertNotIn(("3-gramの重複", "it is the"),
                         [(f["kind"], f["detail"].rsplit(" ×", 1)[0]) for f in r["redundancy"]])

    def test_generated_fragments_are_clean(self):
        for seed in SEEDS + [3, 11, 55]:
            for role in ROLES:
                for vintage in (1, 2, 3):
                    c = generate(role, vintage, seed)
                    self.assertEqual(c.redundancy, [], "seed=%s %s v%s" % (seed, role, vintage))
                    self.assertTrue(c.clean)


class TestPrinciples(unittest.TestCase):
    """CONSTRAINTS の8原則。"""

    def test_p1_subject_first(self):
        res = build(subject="performance", seed=1)
        self.assertTrue(res["body"].startswith("Humanoid female"))

    def test_p2_instrument_two_words_max(self):
        for role, spec in data.ROLES.items():
            self.assertLessEqual(word_count(spec["instrument"]), 2, role)

    def test_p3_lens_six_words_max(self):
        for key, text in data.LENSES.items():
            self.assertLessEqual(word_count(text), data.LENS_MAX_WORDS, key)
        with self.assertRaises(BuildError):
            build(lens="A very long camera instruction that clearly exceeds six words", seed=1)

    def test_p4_accent_bound_to_an_object(self):
        for variant in ("long", "mid", "short"):
            self.assertIn("at her lips", modules.m3("Tilted frame", "amber", variant))

    def test_p5_backlight_always_has_fill(self):
        for variant in ("long", "mid"):
            text = modules.m2(data.SCENES["studio"], variant).lower()
            if "backlit" in text or "backlighting" in text:
                self.assertIn("soft fill", text)

    def test_p6_stylize_defaults(self):
        self.assertEqual(budget_mod.stylize_for("fashion"), 300)
        self.assertEqual(budget_mod.stylize_for("performance"), 400)
        self.assertEqual(budget_mod.stylize_for("none"), 600)
        for subject in data.SUBJECTS:
            self.assertIn("--stylize %d" % budget_mod.stylize_for(subject),
                          build(subject=subject, seed=1)["prompt"])

    def test_p7_ui_checklist_present(self):
        from halprompt.build import format_build
        out = format_build(build(seed=1))
        self.assertIn("貼る前に UI でこれを設定", out)
        self.assertIn("Personalize > Select profile", out)

    def test_p8_l6_excludes_blur_terms(self):
        res = build(percept="L6", seed=1)
        self.assertEqual(res["lint"]["blur_violations"], [])
        polluted = res["prompt"].replace("--stylize", "shot with heavy bokeh --stylize")
        self.assertTrue(lint.lint(polluted, percept_keys=["L6"])["blur_violations"])

    def test_percept_limit(self):
        with self.assertRaises(BuildError):
            build(percept="L1,L2,L3", seed=1)
        with self.assertRaises(BuildError):
            build(percept="L99", seed=1)


class TestArtify(unittest.TestCase):
    """§7 artify。"""

    def test_removes_explanatory_terms(self):
        text = ("A figure, museum realism, photorealistic, highly detailed, "
                "stenciled serial glyphs for identification. --stylize 300")
        res = artify_mod.artify(text, level=1, seed=1)
        low = res["text"].lower()
        for term in ("museum realism", "photorealistic", "highly detailed", "identification"):
            self.assertNotIn(term, low)
        self.assertIn("--stylize 300", res["text"])

    def test_injection_by_level(self):
        text = build(seed=1)["prompt"]
        self.assertEqual(len(artify_mod.artify(text, level=1, seed=1)["injected"]), 1)
        self.assertEqual(len(artify_mod.artify(text, level=2, seed=1)["injected"]), 2)
        r3 = artify_mod.artify(text, level=3, seed=1)
        self.assertEqual(len(r3["injected"]), 3)
        self.assertIn(r3["injected"][0], artify_mod.UNEXPLAINED)
        self.assertIn(r3["injected"][1], artify_mod.MATERIAL)
        self.assertIn(r3["injected"][2], artify_mod.INCOMPLETE)

    def test_artified_prompt_still_lints(self):
        for seed in (0, 7, 777):
            text = build(seed=seed)["prompt"]
            out = artify_mod.artify(text, level=3, seed=seed)["text"]
            self.assertTrue(lint.lint(out, role="bass")["ok"], out)


class TestNoAestheticJudgement(unittest.TestCase):
    """CONSTRAINTS: 美的判定を実装しないこと（grep で確認可能なこと）。"""

    FORBIDDEN_DEF = re.compile(
        r"(?:def|class)\s+(?:\w+_)?(?:beaut|aesthet|artist|taste|quality|masterpiece|"
        r"is_good|is_bad|goodness|badness|prefer|rank|rate|score_art)\w*", re.IGNORECASE)

    def test_no_aesthetic_functions(self):
        for name, src in read_sources().items():
            hits = self.FORBIDDEN_DEF.findall(src)
            self.assertEqual(hits, [], "%s: %s" % (name, hits))

    def test_only_two_kinds_of_judgement_exist(self):
        """判定してよいのは規格適合(§2-2)と残留矛盾(§5)の2つのみ。"""
        c = generate("bass", 2, 777)
        self.assertEqual(sorted(c.conformance.keys()), ["conditions", "distance", "id_score"])
        self.assertEqual(len(c.conformance["conditions"]), 6)
        self.assertEqual(sorted(lint.lint("x").keys()),
                         ["blur_violations", "conflicts", "instruments_in_scope",
                          "instruments_out_of_scope", "ok", "redundancy", "role_violations"])


class TestLocalSovereignty(unittest.TestCase):
    """外部依存なし・ネットワークなし・LLM API なし。"""

    NETWORK = re.compile(r"\b(?:import\s+(?:socket|urllib|http|requests|ssl)|"
                         r"from\s+(?:socket|urllib|http|requests)\b|openai|anthropic|"
                         r"https?://)", re.IGNORECASE)
    STDLIB = {"argparse", "json", "os", "random", "re", "sys", "unittest", "collections", "unicodedata"}

    def test_no_network_or_llm(self):
        for name, src in read_sources().items():
            self.assertIsNone(self.NETWORK.search(src), name)

    def test_only_standard_library(self):
        for name, src in read_sources().items():
            for mod in re.findall(r"^\s*import\s+([a-zA-Z_][\w.]*)", src, re.M):
                self.assertIn(mod.split(".")[0], self.STDLIB, "%s: %s" % (name, mod))
            for mod in re.findall(r"^\s*from\s+([a-zA-Z_][\w.]*)\s+import", src, re.M):
                root = mod.split(".")[0]
                if root in ("halprompt", ""):
                    continue
                self.assertIn(root, self.STDLIB, "%s: %s" % (name, mod))


class TestReadme(unittest.TestCase):
    def test_readme_has_the_section(self):
        path = os.path.join(PKG_DIR, "README.md")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("この道具が計算しないこと", text)
        for line in ("これは良いか", "これは作品か", "この不可解要素を採用すべきか"):
            self.assertIn(line, text)


if __name__ == "__main__":
    unittest.main()
