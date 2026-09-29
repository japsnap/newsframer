"""
Tests for run_whatsapp_brief text transforms: md_to_whatsapp + strip_sources.
These shape the actual bytes sent to WhatsApp recipients (heading/bold/bullet
conversion; source-stripping for secondary languages), so pinning them guards real
delivery output. Pure string logic.

    venv\\Scripts\\python.exe tests\\test_whatsapp_format.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_whatsapp_brief as wa  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# --- md_to_whatsapp: markdown -> WhatsApp markup ---------------------------
def test_heading_becomes_bold():
    ok("h2", wa.md_to_whatsapp("## SpaceX News") == "*SpaceX News*")
    ok("h1", wa.md_to_whatsapp("# Title") == "*Title*")


def test_double_star_becomes_single_star():
    ok("bold", wa.md_to_whatsapp("This is **bold** text") == "This is *bold* text")


def test_bullets_normalised():
    ok("dash_bullet", wa.md_to_whatsapp("- First").startswith("• First"))
    ok("star_bullet", wa.md_to_whatsapp("* Second").startswith("• Second"))


def test_plain_line_unchanged():
    ok("plain", wa.md_to_whatsapp("just a sentence") == "just a sentence")


# --- strip_sources: remove citations/links for secondary languages ---------
def test_strips_inline_numeric_marker():
    ok("inline_marker", wa.strip_sources("Hello [1] world") == "Hello world")


def test_strips_markdown_link():
    out = wa.strip_sources("See [Reuters](https://reuters.com/x) here")
    ok("link_removed", "reuters.com" not in out and "Reuters" not in out)
    ok("link_text_kept", out.startswith("See") and out.endswith("here"))


def test_strips_articles_block():
    text = "Body paragraph.\n\n*Articles:*\n[1] Foo — Reuters\n[2] Bar — BBC\n\nNext section."
    out = wa.strip_sources(text)
    ok("articles_header_gone", "*Articles:*" not in out)
    ok("articles_entries_gone", "Foo" not in out and "Bar" not in out)
    ok("body_kept", "Body paragraph." in out and "Next section." in out)


def test_collapses_excess_blank_lines():
    ok("collapse", "\n\n\n" not in wa.strip_sources("a\n\n\n\n\nb"))


def test_md_strips_links():
    # WhatsApp can't render markdown links -> strip [text](url) -> text so no raw URL leaks (the
    # regression the user flagged: the writer's citation drifted to [title](url) — Source).
    out = wa.md_to_whatsapp("[IRGC: Launched attacks](https://www.middleeasteye.net/live-blog/x) — Middle East Eye")
    ok("link_text_kept", "IRGC: Launched attacks" in out)
    ok("source_kept", "Middle East Eye" in out)
    ok("no_url", "http" not in out and "](" not in out)


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
