"""
Tests for agents/surface_render.py — the per-surface output renderer
(items 1,2,3,5 of the 2026-06-19 output-fixes work order). Pure functions only.

    venv\\Scripts\\python.exe tests\\test_surface_render.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import surface_render as sr  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# ---- config fixture mirroring the new config/models.yaml block ----
CFG = {
    "theme_size_levels": {"S": 1000, "M": 2000, "L": 4000},
    "length_to_size": {"short": "S", "medium": "M", "long": "L"},
    "writer_per_highlight_chars": 250,
    "surfaces": {
        "telegram": {"theme_size": "M", "show_source": True, "include_link": True, "link_style": "hyperlink"},
        "whatsapp": {"theme_size": "M", "show_source": True, "include_link": False, "link_style": "hyperlink"},
    },
}

THEME_LINE = "[1] HIVE Stock Spikes as Bitcoin Miner Lands $220M AI Deal — [Decrypt](https://decrypt.co/371570/hives-deal)"
HL_LINE = "- **CME Plans to Sue CFTC** — CME Group is taking legal action. [Reuters](https://reuters.com/x)"


# ===== item 1/2/3: per-theme SIZE (one control: absolute target + derived cap) =====
def test_resolve_size_level():
    ok("tg_default_M", sr.resolve_size_level(CFG, "telegram") == "M")
    ok("wa_default_M", sr.resolve_size_level(CFG, "whatsapp") == "M")
    big = {"theme_size_levels": {"S": 1000, "M": 2000, "L": 4000}, "surfaces": {"telegram": {"theme_size": "L"}}}
    ok("tg_surface_L", sr.resolve_size_level(big, "telegram") == "L")
    ok("chat_length_long_wins", sr.resolve_size_level(CFG, "whatsapp", chat_length="long") == "L")
    ok("chat_length_short", sr.resolve_size_level(CFG, "whatsapp", chat_length="short") == "S")
    ok("missing_surface_M", sr.resolve_size_level({}, "telegram") == "M")
    ok("unknown_level_M", sr.resolve_size_level({"surfaces": {"telegram": {"theme_size": "XL"}}}, "telegram") == "M")


def test_per_theme_target():
    ok("M_target", sr.per_theme_target(CFG, "M") == 2000)
    ok("L_is_2x_M", sr.per_theme_target(CFG, "L") == 4000)
    ok("S_is_half_M", sr.per_theme_target(CFG, "S") == 1000)
    ok("unknown_falls_to_M", sr.per_theme_target(CFG, "XL") == 2000)


def test_derive_cap():
    ok("cap_formula", sr.derive_cap(2000, 8, 8, 250) == 2000 * 8 + 8 * 250)
    ok("cap_L_theme_part_2x", sr.derive_cap(4000, 8, 0, 250) == 32000)
    ok("cap_no_highlights", sr.derive_cap(2000, 5, 0, 250) == 10000)


# ===== item 2: link / source rendering =====
def test_telegram_hyperlink_drops_bracket_keeps_link():
    out = sr.render_citations(THEME_LINE, sr.link_cfg(CFG, "telegram"), number_style="dot")
    ok("tg_no_bare_bracket", not out.startswith("[1]"))
    ok("tg_numbered", out.startswith("1. "))
    ok("tg_keeps_markdown_link", "[Decrypt](https://decrypt.co/371570/hives-deal)" in out)
    ok("tg_title_present", "HIVE Stock Spikes" in out)


def test_whatsapp_no_link_title_plus_source_only():
    out = sr.render_citations(THEME_LINE, sr.link_cfg(CFG, "whatsapp"), number_style="none")
    ok("wa_no_url", "http" not in out)                 # the REAL no-URL proof for WhatsApp
    ok("wa_no_bracket_num", "[1]" not in out)
    ok("wa_has_source_name", out.strip().endswith("— Decrypt"))
    ok("wa_title_present", "HIVE Stock Spikes" in out)


def test_highlight_line_both_surfaces():
    tg = sr.render_citations(HL_LINE, sr.link_cfg(CFG, "telegram"))
    ok("hl_tg_keeps_link", "[Reuters](https://reuters.com/x)" in tg and tg.startswith("- **CME"))
    wa = sr.render_citations(HL_LINE, sr.link_cfg(CFG, "whatsapp"))
    ok("hl_wa_no_url", "http" not in wa)
    ok("hl_wa_source", wa.strip().endswith("Reuters"))


def test_plain_link_style_shows_url():
    cfg = {"surfaces": {"telegram": {"show_source": True, "include_link": True, "link_style": "plain"}}}
    out = sr.render_citations(THEME_LINE, sr.link_cfg(cfg, "telegram"))
    ok("plain_shows_url", "https://decrypt.co/371570/hives-deal" in out and "[Decrypt]" not in out)


def test_non_citation_lines_untouched():
    body = "Some synthesis paragraph with a [1] footnote ref and **bold** text."
    ok("body_untouched", sr.render_citations(body, sr.link_cfg(CFG, "telegram")) == body)


def test_headings_to_bold():
    ok("tg_h2_bold", sr.headings_to_bold("## US-Iran Deal", "**") == "**US-Iran Deal**")
    ok("wa_h2_bold", sr.headings_to_bold("## US-Iran Deal", "*") == "*US-Iran Deal*")
    ok("emoji_heading", sr.headings_to_bold("## 🔍 Investigations", "**") == "**🔍 Investigations**")
    ok("non_heading_untouched", sr.headings_to_bold("plain line", "**") == "plain line")


def test_render_for_telegram_integration():
    text = "## Crypto Mining\n\nSynthesis [1].\n\n**Articles:**\n" + THEME_LINE
    out = sr.render_for_telegram(text, CFG)
    ok("int_heading_bold", "**Crypto Mining**" in out)
    ok("int_cite_clean", "1. HIVE Stock Spikes" in out and "[Decrypt](https://decrypt.co/371570/hives-deal)" in out)
    ok("int_no_bare_cite_bracket", "\n[1] HIVE" not in out)


# ===== item 3: highlight dedup =====
def _hl(cid, topics):
    return {"id": f"a{cid}", "cluster_id": cid, "score": {"topics": topics}}


CRYPTO_REG = ["crypto markets and infrastructure", "geopolitics affecting markets", "policy"]


def test_dedupe_identical_topicsets_collapse():
    # the 4 crypto-regulation highlights (CME, GENIUS, Fed-rule, Powell) share an IDENTICAL
    # 3-topic signature but different clusters -> collapse to ONE (keeps the first = top relevance)
    hls = [_hl(1, CRYPTO_REG), _hl(2, CRYPTO_REG), _hl(3, CRYPTO_REG), _hl(4, CRYPTO_REG)]
    out = sr.dedupe_highlights(hls, [], topic_overlap=1.0, min_shared_topics=3)
    ok("crypto_reg_collapsed_to_1", len(out) == 1 and out[0]["cluster_id"] == 1)


def test_dedupe_thin_overlap_kept():
    # two genuinely different geopolitics stories with only 2 shared tags must NOT collapse
    a = _hl(10, ["geopolitics", "sanctions"])
    b = _hl(11, ["geopolitics", "sanctions"])
    out = sr.dedupe_highlights([a, b], [], topic_overlap=1.0, min_shared_topics=3)
    ok("thin_overlap_both_kept", len(out) == 2)


def test_dedupe_distinct_topics_kept():
    a = _hl(20, CRYPTO_REG)
    b = _hl(21, ["pakistan politics", "budget", "taxation"])
    out = sr.dedupe_highlights([a, b], [], topic_overlap=1.0, min_shared_topics=3)
    ok("distinct_kept", len(out) == 2)


def test_dedupe_theme_highlight_drop():
    # a highlight whose cluster already anchors a theme is removed
    theme = [{"cluster_id": 30, "score": {"topics": CRYPTO_REG}}]
    hls = [_hl(30, CRYPTO_REG), _hl(31, ["pakistan", "budget", "economy"])]
    out = sr.dedupe_highlights(hls, theme, topic_overlap=1.0, min_shared_topics=3)
    ok("theme_dup_dropped", [h["cluster_id"] for h in out] == [31])


def test_dedupe_by_cluster_same_cluster_collapses():
    hls = [_hl(40, ["a", "b"]), _hl(40, ["c", "d"])]
    out = sr.dedupe_highlights(hls, [], by_cluster=True, topic_overlap=1.0, min_shared_topics=3)
    ok("same_cluster_one_kept", len(out) == 1)


# ===== item 5: WhatsApp topic exclude filter =====
INCLUDE = {
    "geopolitics": ["geopolit", "sanction", "middle east"],
    "pakistan": ["pakistan"],
    "cybersecurity": ["cyber", "malware"],
}
# Loose exclude (Shota's chosen cutoff): explicit crypto/prediction-market only, geo+pak,
# cyber deliberately omitted so crypto-MALWARE still reaches the cyber surface.
EXCLUDE = {
    "geopolitics": ["crypto", "bitcoin", "ether", "stablecoin", "prediction market", "kalshi", "cme group", "cftc"],
    "pakistan": ["crypto", "bitcoin", "ether", "stablecoin", "prediction market", "kalshi", "cme group", "cftc"],
}


def test_exclude_drops_crypto_leak():
    cme = ["crypto markets and infrastructure", "geopolitics affecting markets", "policy"]
    ok("cme_excluded_geo", not sr.passes_topic_filter(cme, ["geopolitics", "pakistan"], INCLUDE, EXCLUDE))


def test_exclude_keeps_true_geopolitics():
    hez = ["geopolitics", "sanctions", "hezbollah", "lebanon", "united states"]
    ok("hezbollah_kept", sr.passes_topic_filter(hez, ["geopolitics", "pakistan"], INCLUDE, EXCLUDE))


def test_exclude_keeps_cyber_crypto_malware():
    worm = ["cybersecurity", "crypto markets and infrastructure", "malware"]
    ok("cyber_malware_kept", sr.passes_topic_filter(worm, ["geopolitics", "pakistan", "cybersecurity"], INCLUDE, EXCLUDE))


def test_exclude_keeps_pakistan_budget():
    budget = ["pakistan politics", "pakistan economy", "taxation", "budget"]
    ok("pak_budget_kept", sr.passes_topic_filter(budget, ["geopolitics", "pakistan"], INCLUDE, EXCLUDE))


def test_no_exclude_is_include_only():
    cme = ["crypto markets and infrastructure", "geopolitics affecting markets"]
    ok("no_exclude_includes", sr.passes_topic_filter(cme, ["geopolitics"], INCLUDE, None))


def test_star_wildcard_exclude():
    cme = ["crypto markets", "policy"]
    ok("star_excludes_all", not sr.passes_topic_filter(cme, ["geopolitics"], INCLUDE, {"*": ["crypto"]}))


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as e:
                print(f"FAIL: {e}")
                failed += 1
            except Exception as e:
                print(f"ERROR in {name}: {type(e).__name__}: {e}")
                failed += 1
    print(f"\n{len(PASS)} checks passed, {failed} test(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
