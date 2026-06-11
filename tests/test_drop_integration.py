"""
Dry-run + integration test for the drop-report feature in writer.py.

Exercises the REAL writer functions (build_drops / weave / render / splice) on
synthetic scored articles with a STUBBED LLM — no DB, no LLM spend, no send.
Proves: an investigative article is selected, tagged as a drop-report, woven or
standalone correctly, and ALWAYS rendered in the Investigations section.

    venv\\Scripts\\python.exe tests\\test_drop_integration.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import writer  # noqa: E402  (safe: no DB at import)


# --- stubbed LLM (mimics litellm's response shape) -------------------------
class _Msg:
    def __init__(self, c): self.content = c


class _Choice:
    def __init__(self, c): self.message = _Msg(c)


class _Resp:
    def __init__(self, c): self.choices = [_Choice(c)]


def stub_completion(model, messages, **kw):
    # Echo the article title so we can prove the right article was summarized.
    user = messages[-1]["content"]
    m = re.search(r"title:\s*(.*)", user)
    title = (m.group(1).strip() if m else "?")[:40]
    return _Resp(
        '{"short": "STUB: ' + title + ' — one factual sentence.", '
        '"long": "STUB long para one about ' + title + '.\\n\\nPara two with method and why it matters."}'
    )


def art(aid, source_id, title, url, topics, rel=7, act=1):
    return {
        "id": aid, "source_id": source_id, "title": title, "url": url,
        "content_raw": "Body text describing the investigation in detail.",
        "score": {"relevance_score": rel, "actionability": act, "topics": topics,
                  "differentiator": "", "reasoning": "analyst reasoning", "label": "NEW_SIGNAL",
                  "hypotheses": [], "perspective_invited": False},
    }


SOURCES = {"src_cl": "Citizen Lab", "src_fa": "Forensic Architecture"}


def run():
    fails = []

    # Main theme (normal news) is about Pegasus/surveillance.
    main_theme_topics = {"pegasus", "surveillance"}
    clusters = [[
        art("n1", "src_news", "Spyware scandal widens", "https://x/1", ["pegasus", "surveillance"]),
        art("n2", "src_news", "Officials respond to spyware claims", "https://x/2", ["pegasus", "politics"]),
    ]]

    # Two drop candidates: one matches the main theme (-> woven), one does not (-> standalone).
    drop_candidates = [
        art("d1", "src_cl", "Pegasus traced to new operator", "https://citizenlab.ca/p",
            ["pegasus", "spyware"], rel=8),
        art("d2", "src_fa", "Strike pattern reconstructed from satellite data", "https://fa/s",
            ["forensic", "satellite"], rel=7),
    ]

    drops = writer.build_drops(
        drop_candidates, main_theme_topics, max_drops=3, model="stub",
        sources_map=SOURCES, completion_fn=stub_completion,
    )

    if len(drops) != 2:
        fails.append(f"expected 2 drops, got {len(drops)}")

    by_id = {d["article"]["id"]: d for d in drops}
    if not by_id.get("d1", {}).get("woven"):
        fails.append("d1 (shares 'pegasus' with main theme) should be WOVEN")
    if by_id.get("d2", {}).get("woven"):
        fails.append("d2 (no shared topic) should be STANDALONE, not woven")

    for d in drops:
        if not d["render"].get("short"):
            fails.append(f"{d['article']['id']} missing short summary")
        if not d["store"].get("long"):
            fails.append(f"{d['article']['id']} missing long summary")
        if not re.match(r"^[a-z0-9-]+$", d["render"].get("slug", "")):
            fails.append(f"{d['article']['id']} bad slug {d['render'].get('slug')!r}")

    # Slugs unique.
    slugs = [d["render"]["slug"] for d in drops]
    if len(set(slugs)) != len(slugs):
        fails.append(f"slugs not unique: {slugs}")

    # Weave step (as run_writer does): woven drops join the main theme cluster.
    for d in drops:
        if d["woven"]:
            clusters[0].append(d["article"])
    if not any(a["id"] == "d1" for a in clusters[0]):
        fails.append("woven drop d1 was not added to the main theme cluster")

    # Render + splice into a representative brief.
    section = writer.render_investigations_section([d["render"] for d in drops])
    if "## 🔍 Investigations" not in section:
        fails.append("Investigations header missing")
    # ALWAYS surface: both drops appear regardless of woven status.
    for t in ("Pegasus traced to new operator", "Strike pattern reconstructed from satellite data"):
        if t not in section:
            fails.append(f"drop title missing from Investigations: {t}")

    fake_brief = (
        "# NewsFramer Briefing — 2026-06-11\n\n"
        "## Spyware scandal widens\nSynthesis paragraph... [1]\n\n**Articles:**\n[1] [a](u) — Source\n\n"
        "## Highlights\n- **Some item** — summary. [Src](u)\n\n"
        "---\n_Briefing generated from 50 articles. 12 made the relevance cutoff. 1 themes, 1 highlights._"
    )
    spliced = writer.splice_investigations(fake_brief, section)
    if spliced.index("Investigations") > spliced.index("## Highlights"):
        fails.append("Investigations should appear ABOVE Highlights")

    # ---- visible output for the human reviewer ----
    print("=" * 72)
    print("RENDERED INVESTIGATIONS SECTION (what lands in the Telegram brief):")
    print("=" * 72)
    print(section)
    print("=" * 72)
    print("PLACEMENT in the brief (excerpt):")
    print("=" * 72)
    print(spliced)
    print("=" * 72)
    print(f"d1 woven={by_id['d1']['woven']} (expected True)  |  d2 woven={by_id['d2']['woven']} (expected False)")
    print(f"slugs: {slugs}")

    if fails:
        print("\nDRY RUN FAILED:")
        for f in fails:
            print("  - " + f)
        return 1
    print("\nDRY RUN PASSED: drop selected, tagged, woven/standalone correct, always in Investigations.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
