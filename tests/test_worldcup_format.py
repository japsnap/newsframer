"""
Tests for agents/worldcup_format.py — pure rendering of World Cup data into the
WhatsApp message (NF-A3). No network, no API, no LLM.

    venv\\Scripts\\python.exe tests\\test_worldcup_format.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import worldcup_format as wc  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def test_flag_from_iso2():
    ok("flag_ar", wc.flag_from_iso2("AR") == "🇦🇷")
    ok("flag_lowercase", wc.flag_from_iso2("br") == "🇧🇷")
    ok("flag_empty", wc.flag_from_iso2("") == "")
    ok("flag_one_letter", wc.flag_from_iso2("X") == "")
    ok("flag_digits", wc.flag_from_iso2("12") == "")


def test_flag_by_name_lookup():
    ok("flag_name", wc.flag({"name": "Brazil"}) == "🇧🇷")
    ok("flag_iso_wins", wc.flag({"name": "Brazil", "iso2": "AR"}) == "🇦🇷")
    ok("flag_unknown", wc.flag({"name": "Atlantis"}) == "")


def test_format_match_with_goalscorers():
    m = {"home": {"name": "Argentina", "iso2": "AR"},
         "away": {"name": "Brazil", "iso2": "BR"},
         "home_score": 2, "away_score": 1,
         "goals": [{"team": "home", "scorer": "Messi", "minute": 23},
                   {"team": "home", "scorer": "Alvarez", "minute": 67},
                   {"team": "away", "scorer": "Neymar", "minute": 80}]}
    s = wc.format_match(m)
    ok("match_score", "2–1" in s)
    ok("match_flags", "🇦🇷" in s and "🇧🇷" in s)
    ok("match_scorer", "Messi 23'" in s and "Neymar 80'" in s)
    ok("match_goal_marker", "⚽" in s)


def test_format_match_goalless_has_no_scorer_line():
    m = {"home": {"name": "Spain", "iso2": "ES"}, "away": {"name": "Italy", "iso2": "IT"},
         "home_score": 0, "away_score": 0, "goals": []}
    s = wc.format_match(m)
    ok("goalless_score", "0–0" in s)
    ok("goalless_no_marker", "⚽" not in s)


def test_format_match_defensive_on_empty():
    s = wc.format_match({})            # must not raise
    ok("empty_match_str", isinstance(s, str))


def test_format_results_empty():
    ok("results_empty", "No matches in the last 24 hours" in wc.format_results([]))


def test_format_standings_table():
    standings = [
        {"group": "A", "team": "Argentina", "iso2": "AR", "played": 2, "won": 2,
         "drawn": 0, "lost": 0, "gd": 4, "points": 6},
        {"group": "A", "team": "Mexico", "iso2": "MX", "played": 2, "won": 0,
         "drawn": 1, "lost": 1, "gd": -2, "points": 1},
    ]
    s = wc.format_standings(standings)
    ok("standings_group", "*Group A*" in s)
    ok("standings_mono", "```" in s)
    ok("standings_header", "Pts" in s and "GD" in s)
    ok("standings_team", "Argentina" in s and "Mexico" in s)
    # leader (6 pts) must be listed before the 1-pt team
    ok("standings_sorted", s.index("Argentina") < s.index("Mexico"))
    ok("standings_gd_sign", "+4" in s and "-2" in s)


def test_format_fixtures():
    fx = [{"home": {"name": "Spain", "iso2": "ES"}, "away": {"name": "Germany", "iso2": "DE"},
           "kickoff": "21:00 JST"}]
    s = wc.format_fixtures(fx)
    ok("fixtures_vs", "vs" in s and "21:00 JST" in s)
    ok("fixtures_flags", "🇪🇸" in s and "🇩🇪" in s)
    ok("fixtures_empty", "No matches scheduled" in wc.format_fixtures([]))


def test_kickoff_in_tz():
    # 9:00 p.m. UTC-5  -> 02:00 UTC next day -> +5 (Karachi) -> 07:00 the day after.
    ok("ktz_convert", "7:00 AM" in wc.kickoff_in_tz("2026-06-15", "9:00 p.m. UTC-5", 5))
    # 8:00 p.m. UTC-4  -> 00:00 UTC next day -> +5 -> 05:00.
    ok("ktz_pm", wc.kickoff_in_tz("2026-06-15", "8:00 p.m. UTC-4", 5).endswith("5:00 AM"))
    ok("ktz_noon", "5:00 PM" in wc.kickoff_in_tz("2026-06-15", "12:00 p.m. UTC+0", 5))
    ok("ktz_midnight", "5:00 AM" in wc.kickoff_in_tz("2026-06-15", "12:00 a.m. UTC+0", 5))
    ok("ktz_weekday", wc.kickoff_in_tz("2026-06-15", "9:00 p.m. UTC-5", 5)[:3] in
       ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
    # Unparseable -> '' so the caller falls back to the raw venue string (never crashes).
    ok("ktz_no_offset", wc.kickoff_in_tz("2026-06-15", "3:00 p.m. local", 5) == "")
    ok("ktz_no_date", wc.kickoff_in_tz("", "8:00 p.m. UTC-4", 5) == "")
    ok("ktz_none_off", wc.kickoff_in_tz("2026-06-15", "8:00 p.m. UTC-4", None) == "")


def test_format_fixtures_tz_and_fallback():
    fx = [{"home": {"name": "Spain", "iso2": "ES"}, "away": {"name": "Germany", "iso2": "DE"},
           "kickoff": "9:00 p.m. UTC-5", "date": "2026-06-15"}]
    s = wc.format_fixtures(fx, tz_offset_hours=5, tz_label="PKT / UTC+5")
    ok("fx_tz_label", "PKT / UTC+5" in s)
    ok("fx_tz_time", "7:00 AM" in s)            # converted to UTC+5
    ok("fx_tz_no_raw", "UTC-5" not in s)        # raw venue string is gone
    # No tz given -> raw venue string is shown unchanged.
    s2 = wc.format_fixtures(fx)
    ok("fx_raw_fallback", "9:00 p.m. UTC-5" in s2)


def test_full_message_assembly():
    msg = wc.format_worldcup_message(
        results=[{"home": {"name": "Argentina", "iso2": "AR"},
                  "away": {"name": "Brazil", "iso2": "BR"},
                  "home_score": 1, "away_score": 0,
                  "goals": [{"team": "home", "scorer": "Messi", "minute": 12}]}],
        standings=[{"group": "A", "team": "Argentina", "iso2": "AR", "played": 1,
                    "won": 1, "drawn": 0, "lost": 0, "gd": 1, "points": 3}],
        fixtures=[{"home": {"name": "Spain", "iso2": "ES"},
                   "away": {"name": "Germany", "iso2": "DE"}, "kickoff": "21:00 JST"}],
        wrap_up="Argentina edged Brazil.",
    )
    ok("msg_header", "World Cup 2026" in msg)
    ok("msg_results", "Yesterday's results" in msg and "Messi 12'" in msg)
    ok("msg_standings", "*Group A*" in msg)
    ok("msg_fixtures", "Next 24 hours" in msg)
    ok("msg_wrapup", "Wrap-up" in msg and "edged Brazil" in msg)


def test_section_order_and_reply():
    msg = wc.format_worldcup_message(
        results=[{"home": {"name": "Argentina", "iso2": "AR"},
                  "away": {"name": "Brazil", "iso2": "BR"},
                  "home_score": 1, "away_score": 0, "goals": []}],
        standings=[{"group": "A", "team": "Argentina", "played": 1, "won": 1,
                    "drawn": 0, "lost": 0, "gd": 1, "points": 3}],
        fixtures=[{"home": {"name": "Spain", "iso2": "ES"},
                   "away": {"name": "Germany", "iso2": "DE"},
                   "kickoff": "9:00 p.m. UTC-5", "date": "2026-06-15"}],
        tz_offset_hours=5, tz_label="PKT / UTC+5", reply_line="Any questions, reply",
    )
    i_res = msg.index("Yesterday's results")
    i_fix = msg.index("Next 24 hours")
    i_std = msg.index("*Group A*")
    ok("order_results_before_fixtures", i_res < i_fix)
    ok("order_fixtures_before_standings", i_fix < i_std)   # NEW order: results -> fixtures -> standings
    ok("reply_line_at_end", msg.rstrip().endswith("Any questions, reply"))
    ok("tz_time_in_msg", "7:00 AM" in msg)
    # reply_line="" must NOT append anything
    msg2 = wc.format_worldcup_message([], [], [], reply_line="")
    ok("no_reply_when_blank", "Any questions" not in msg2)


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
