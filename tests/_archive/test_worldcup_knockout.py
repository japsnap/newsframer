# ARCHIVED 2026-07-22 — retired, not deleted (repo archive rule).
# Reason: the World Cup / football module was removed from the codebase (2026 tournament
# ended 2026-07-19; operator chose clean deletion over extracting a tournament template).
# Subject coverage now: none — the code under test no longer exists (agents/worldcup_data.py,
# agents/worldcup_format.py, run_worldcup_brief.py, agents/event_feed.py, run_football_brief.py
# and all worldcup_*/football_* config keys were deleted the same day).
# This file will no longer run: its imports were deleted with the feature.

"""
Knockout-stage World Cup logic (post-group-stage redesign). PURE derivation over match dicts —
no network, no HTML. Covers: round-from-match-number, winner (decisive score OR penalty winner via
who-advances), eliminated (cumulative, newest-first), and the still-alive split (through-to-next
vs yet-to-play). The HTML parsing (round/number attach) is verified live separately.

    venv\\Scripts\\python.exe tests\\test_worldcup_knockout.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import worldcup_data as wd  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def M(num, home, away, hs=None, as_=None, played=False, date="2026-06-29"):
    return {"number": num, "round": wd.round_for_match_number(num),
            "home": {"name": home}, "away": {"name": away},
            "home_score": hs, "away_score": as_, "goals": [], "played": played, "date": date}


# --- round-from-number + sequence ------------------------------------------

def test_round_for_match_number():
    ok("r32_lo", wd.round_for_match_number(73) == "Round of 32")
    ok("r32_hi", wd.round_for_match_number(88) == "Round of 32")
    ok("r16", wd.round_for_match_number(89) == "Round of 16" and wd.round_for_match_number(96) == "Round of 16")
    ok("qf", wd.round_for_match_number(97) == "Quarter-finals" and wd.round_for_match_number(100) == "Quarter-finals")
    ok("sf", wd.round_for_match_number(101) == "Semi-finals" and wd.round_for_match_number(102) == "Semi-finals")
    ok("final", wd.round_for_match_number(104) == "Final")
    ok("group_none", wd.round_for_match_number(50) is None)
    ok("none_none", wd.round_for_match_number(None) is None)


def test_next_round():
    ok("r32_next", wd.next_round("Round of 32") == "Round of 16")
    ok("r16_next", wd.next_round("Round of 16") == "Quarter-finals")
    ok("sf_next", wd.next_round("Semi-finals") == "Final")
    ok("final_next", wd.next_round("Final") is None)


# --- placeholder teams ------------------------------------------------------

def test_is_placeholder_team():
    ok("winner_match", wd.is_placeholder_team("Winner Match 83"))
    ok("runner_up", wd.is_placeholder_team("Runner-up Group A"))
    ok("loser", wd.is_placeholder_team("Loser Match 101"))
    ok("real_team", not wd.is_placeholder_team("Argentina"))
    ok("empty", wd.is_placeholder_team(""))


# --- winner (decisive score OR penalty via advancement) --------------------

def test_winner_decisive_score():
    m = M(78, "France", "Sweden", 3, 0, played=True)
    ok("higher_wins", wd.match_winner_name(m, advancing=set()) == "France")
    m2 = M(74, "Brazil", "Japan", 1, 2, played=True)
    ok("away_wins", wd.match_winner_name(m2, advancing=set()) == "Japan")


def test_winner_penalty_via_advancement():
    # Germany 1-1 Paraguay; Paraguay appears in a later match -> Paraguay won the shootout.
    m = M(75, "Germany", "Paraguay", 1, 1, played=True)
    ok("tie_advancing_wins", wd.match_winner_name(m, advancing={"Paraguay"}) == "Paraguay")
    ok("tie_other_advancing", wd.match_winner_name(
        M(76, "Netherlands", "Morocco", 1, 1, played=True), advancing={"Morocco"}) == "Morocco")


def test_winner_unknown_when_tie_and_no_advance_info():
    m = M(75, "Germany", "Paraguay", 1, 1, played=True)
    ok("tie_undetermined", wd.match_winner_name(m, advancing=set()) is None)


def test_winner_none_when_unplayed():
    ok("unplayed_none", wd.match_winner_name(M(81, "Belgium", "Senegal"), advancing=set()) is None)


# --- full knockout state ----------------------------------------------------

def _scenario():
    """R32 partly played (73-80 done, 81-88 upcoming), R16 fixtures 89-92 set (real teams),
    93-96 still placeholders. Mirrors the real 2026-07-02 page."""
    return [
        M(73, "South Africa", "Canada", 0, 1, played=True, date="2026-06-28"),
        M(74, "Brazil", "Japan", 2, 1, played=True, date="2026-06-29"),
        M(75, "Germany", "Paraguay", 1, 1, played=True, date="2026-06-29"),   # Paraguay adv (pens)
        M(78, "France", "Sweden", 3, 0, played=True, date="2026-06-30"),
        M(80, "England", "DR Congo", 2, 1, played=True, date="2026-07-01"),
        M(81, "Belgium", "Senegal"),        # upcoming R32
        M(84, "Spain", "Austria"),          # upcoming R32
        M(89, "Paraguay", "France"),        # R16 fixture (real teams) -> Paraguay+France advanced
        M(90, "Canada", "Morocco"),         # R16 fixture -> Canada+Morocco advanced
        M(93, "Winner Match 85", "Winner Match 86"),   # placeholder R16
    ]


def test_current_round_is_r32():
    st = wd.derive_knockout_state(_scenario())
    ok("current_r32", st["current_round"] == "Round of 32")
    ok("next_r16", st["next_round"] == "Round of 16")


def test_eliminated_newest_first():
    st = wd.derive_knockout_state(_scenario())
    elim = st["eliminated"]
    # losers: South Africa(06-28), Japan(06-29), Germany(06-29, lost pens), Sweden(06-30), DR Congo(07-01)
    ok("elim_has_losers", set(elim) == {"South Africa", "Japan", "Germany", "Sweden", "DR Congo"})
    ok("elim_newest_first", elim[0] == "DR Congo" and elim[-1] == "South Africa")


def test_through_to_next_round():
    st = wd.derive_knockout_state(_scenario())
    # teams appearing in a real R16 fixture = advanced from R32
    ok("through_set", set(st["through"]) == {"Paraguay", "France", "Canada", "Morocco"})
    ok("no_placeholder_in_through", all(not wd.is_placeholder_team(t) for t in st["through"]))


def test_yet_to_play_current_round():
    st = wd.derive_knockout_state(_scenario())
    # unplayed R32 matches 81, 84 -> their (real) teams
    ok("yet_set", set(st["yet_to_play"]) == {"Belgium", "Senegal", "Spain", "Austria"})


def test_results_carry_winner_name():
    st = wd.derive_knockout_state(_scenario())
    by_pair = {(r["home"]["name"], r["away"]["name"]): r for r in st["results"]}
    ok("france_winner", by_pair[("France", "Sweden")]["winner"] == "France")
    ok("paraguay_pen_winner", by_pair[("Germany", "Paraguay")]["winner"] == "Paraguay")


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
