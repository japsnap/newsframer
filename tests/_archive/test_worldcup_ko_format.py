# ARCHIVED 2026-07-22 — retired, not deleted (repo archive rule).
# Reason: the World Cup / football module was removed from the codebase (2026 tournament
# ended 2026-07-19; operator chose clean deletion over extracting a tournament template).
# Subject coverage now: none — the code under test no longer exists (agents/worldcup_data.py,
# agents/worldcup_format.py, run_worldcup_brief.py, agents/event_feed.py, run_football_brief.py
# and all worldcup_*/football_* config keys were deleted the same day).
# This file will no longer run: its imports were deleted with the feature.

"""
Knockout-stage World Cup MESSAGE rendering (post-group-stage). PURE: structured state in,
WhatsApp text out. Winner shown with the "X beat Y" verb (winner first), penalty wins marked
"(pens)", eliminated newest-first, still-alive split into through / yet-to-play. No group tables.

    venv\\Scripts\\python.exe tests\\test_worldcup_ko_format.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import worldcup_format as wf  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def R(home, away, hs, as_, winner, goals=None):
    return {"home": {"name": home}, "away": {"name": away}, "home_score": hs, "away_score": as_,
            "winner": winner, "goals": goals or []}


# --- single result line -----------------------------------------------------

def test_result_home_winner():
    line = wf.format_ko_result(R("England", "DR Congo", 2, 1, "England"))
    ok("winner_first", "England beat DR Congo" in line)
    ok("score", "2–1" in line)
    ok("no_pens", "(pens)" not in line)


def test_result_away_winner_flips_score():
    # South Africa 0-1 Canada, Canada won -> "Canada beat South Africa 1–0"
    line = wf.format_ko_result(R("South Africa", "Canada", 0, 1, "Canada"))
    ok("winner_first", "Canada beat South Africa" in line)
    ok("score_flipped", "1–0" in line)


def test_result_penalty_winner():
    line = wf.format_ko_result(R("Germany", "Paraguay", 1, 1, "Paraguay"))
    ok("pen_winner_first", "Paraguay beat Germany" in line)
    ok("pens_marked", "(pens)" in line)
    ok("draw_score", "1–1" in line)


def test_result_undetermined_no_beat():
    line = wf.format_ko_result(R("Germany", "Paraguay", 1, 1, None))
    ok("no_beat", "beat" not in line)
    ok("both_teams", "Germany" in line and "Paraguay" in line)


def test_result_goals_line():
    line = wf.format_ko_result(R("England", "DR Congo", 2, 1, "England",
                                 goals=[{"team": "home", "scorer": "Kane", "minute": "12"},
                                        {"team": "away", "scorer": "Bakambu", "minute": "55"}]))
    ok("has_scorers", "Kane" in line and "Bakambu" in line)


# --- eliminated -------------------------------------------------------------

def test_eliminated_section():
    out = wf.format_eliminated(["DR Congo", "Sweden", "Japan"])
    ok("header", "Knocked out" in out)
    ok("all_names", all(n in out for n in ("DR Congo", "Sweden", "Japan")))
    ok("order_kept", out.index("DR Congo") < out.index("Sweden") < out.index("Japan"))


def test_eliminated_empty_is_blank():
    ok("blank", wf.format_eliminated([]) == "")


# --- still alive: through / yet-to-play -------------------------------------

def test_still_alive_two_groups():
    out = wf.format_still_alive(["Canada", "France"], ["Spain", "Austria"],
                                current_round="Round of 32", next_round="Round of 16")
    ok("through_header", "Through to Round of 16" in out)
    ok("through_teams", "Canada" in out and "France" in out)
    ok("yet_header", "Round of 32" in out and "yet to play" in out)
    ok("yet_teams", "Spain" in out and "Austria" in out)


# --- full message -----------------------------------------------------------

def _payload():
    return {
        "current_round": "Round of 32", "next_round": "Round of 16",
        "results": [R("England", "DR Congo", 2, 1, "England"),
                    R("Germany", "Paraguay", 1, 1, "Paraguay")],
        "live": [{"home": {"name": "Belgium"}, "away": {"name": "Senegal"}}],
        "fixtures": [{"home": {"name": "Spain"}, "away": {"name": "Austria"},
                      "kickoff": "12:00 p.m. UTC-7", "date": "2026-07-02"}],
        "eliminated": ["DR Congo", "Paraguay-loser"],
        "through": ["Canada", "France"],
        "yet_to_play": ["Spain", "Austria"],
    }


def test_full_message_structure():
    msg = wf.format_knockout_message(_payload(), tz_offset_hours=5, tz_label="PKT", reply_line="Reply to chat")
    ok("round_header", "Round of 32" in msg.split("\n")[0])
    ok("no_group_tables", "Group" not in msg)
    ok("results", "England beat DR Congo" in msg)
    ok("playing_now", "Playing now" in msg and "next update" in msg)
    ok("next_up", "Spain" in msg and "Austria" in msg)
    ok("knocked_out", "Knocked out" in msg)
    ok("through", "Through to Round of 16" in msg)
    ok("yet", "yet to play" in msg)
    ok("reply", "Reply to chat" in msg)


def test_full_message_thin_sections_skipped():
    # no live, no fixtures -> those sections absent, no crash
    p = _payload()
    p["live"] = []
    p["fixtures"] = []
    msg = wf.format_knockout_message(p)
    ok("no_playing", "Playing now" not in msg)
    ok("still_results", "England beat DR Congo" in msg)


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
