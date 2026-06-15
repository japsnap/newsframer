"""
Tests for agents/worldcup_data.py — parse the Wikipedia '2026 FIFA World Cup' page
into results (with goalscorers+minute), fixtures, and group standings. The synthetic
HTML below mirrors the REAL Wikipedia structure (footballbox + wikitable, incl. an
ISO bday span, fscore link to the group, fhgoal/fagoal lists, and a unicode/entity
minus in GD). No network.

    venv\\Scripts\\python.exe tests\\test_worldcup_data.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import worldcup_data as wd  # noqa: E402

JST = timezone(timedelta(hours=9))
PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


HTML = (
    '<div class="footballbox" style="color:inherit">'
    '<div class="fleft"><time><div class="fdate">June 14, 2026<span style="display:none"> '
    '(<span class="bday dtstart published updated itvstart">2026-06-14</span>)</span></div>'
    '<div class="ftime">8:00 p.m. <a href="/wiki/UTC">UTC-4</a></div></time></div>'
    '<table class="fevent"><tbody><tr itemprop="name">'
    '<th class="fhome" itemprop="homeTeam" itemscope=""><span itemprop="name">'
    '<a href="/wiki/Argentina" title="Argentina">Argentina</a><span class="flagicon">f</span></span></th>'
    '<th class="fscore"><a href="/wiki/2026_FIFA_World_Cup_Group_C#A_vs_B" title="x">2–1</a></th>'
    '<th class="faway" itemprop="awayTeam" itemscope=""><span itemprop="name">'
    '<span class="flagicon">f</span><a href="/wiki/Brazil" title="Brazil">Brazil</a></span></th></tr>'
    '<tr class="fgoals"><td class="fhgoal"><div class="plainlist"><ul>'
    '<li><a href="/wiki/Messi" title="Messi">Messi</a> <span class="fb-goal">'
    '<span title="Goal"><img/></span> <span>23\'</span></span></li>'
    '<li><a href="/wiki/Alvarez" title="Alvarez">Alvarez</a> <span class="fb-goal"><span>90+2\'</span></span></li>'
    '</ul></div></td>'
    '<td class="fagoal"><div class="plainlist"><ul><li><a href="/wiki/Neymar" title="Neymar">Neymar</a> '
    '<span class="fb-goal"><span>80\'</span></span></li></ul></div></td></tr>'
    '</tbody></table></div>'
    '<div class="footballbox" style="color:inherit">'
    '<div class="fleft"><time><div class="fdate">June 15, 2026<span style="display:none"> '
    '(<span class="bday dtstart published updated itvstart">2026-06-15</span>)</span></div>'
    '<div class="ftime">9:00 p.m. <a href="/wiki/UTC">UTC-5</a></div></time></div>'
    '<table class="fevent"><tbody><tr itemprop="name">'
    '<th class="fhome" itemprop="homeTeam"><span itemprop="name"><a href="/wiki/Spain" title="Spain">Spain</a></span></th>'
    '<th class="fscore"><a href="/wiki/2026_FIFA_World_Cup_Group_C">v</a></th>'
    '<th class="faway" itemprop="awayTeam"><span itemprop="name"><a href="/wiki/Germany" title="Germany">Germany</a></span></th></tr>'
    '</tbody></table></div>'
    '<h3 id="Group_C">Group C</h3>'
    '<table class="wikitable"><tbody>'
    '<tr><th>Pos</th><th>Team</th><th>Pld</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Qualification</th></tr>'
    '<tr><td>1</td><td><a href="/wiki/Argentina">Argentina</a></td><td>1</td><td>1</td><td>0</td><td>0</td><td>2</td><td>1</td><td>+1</td><td>3</td><td>Advance</td></tr>'
    '<tr><td>2</td><td><a href="/wiki/Brazil">Brazil</a></td><td>1</td><td>0</td><td>0</td><td>1</td><td>1</td><td>2</td><td>&#8722;1</td><td>0</td><td></td></tr>'
    '</tbody></table>'
)


def test_parse_result_match():
    r = wd.parse_matches(HTML)[0]
    ok("home", r["home"]["name"] == "Argentina")
    ok("away", r["away"]["name"] == "Brazil")
    ok("score", r["home_score"] == 2 and r["away_score"] == 1)
    ok("played", r["played"] is True)
    ok("group", r["group"] == "C")
    ok("date", r["date"] == "2026-06-14")
    ok("time", "8:00" in r["time"])
    ok("time_has_utc_offset", "UTC-4" in r["time"])   # offset (inside the <a>) must survive for tz conversion
    g = r["goals"]
    ok("goal_count", len(g) == 3)
    ok("home_scorer", any(x["scorer"] == "Messi" and x["minute"] == "23" and x["team"] == "home" for x in g))
    ok("stoppage", any(x["scorer"] == "Alvarez" and x["minute"] == "90+2" for x in g))
    ok("away_scorer", any(x["scorer"] == "Neymar" and x["minute"] == "80" and x["team"] == "away" for x in g))


def test_parse_fixture_match():
    f = wd.parse_matches(HTML)[1]
    ok("fixture_unplayed", f["played"] is False)
    ok("fixture_teams", f["home"]["name"] == "Spain" and f["away"]["name"] == "Germany")
    ok("fixture_no_score", f["home_score"] is None)


def test_parse_standings():
    st = wd.parse_standings(HTML)
    ok("two_rows", len(st) == 2)
    arg = [s for s in st if s["team"] == "Argentina"][0]
    bra = [s for s in st if s["team"] == "Brazil"][0]
    ok("group_from_match", arg["group"] == "C" and bra["group"] == "C")
    ok("arg", arg["points"] == 3 and arg["gd"] == 1 and arg["won"] == 1)
    ok("bra_negative_gd", bra["gd"] == -1)   # minus entity must be preserved
    ok("bra_pts", bra["points"] == 0 and bra["lost"] == 1)


def test_build_payload_windows():
    # now = 2026-06-15 12:00 JST = 03:00 UTC. Rolling-24h by REAL kickoff (not venue date):
    #   Arg-Bra  kicked off 06-15 00:00 UTC (3h ago)   -> result.
    #   Spain-Ger kicks off 06-16 02:00 UTC (23h ahead) -> fixture.
    now = datetime(2026, 6, 15, 12, 0, tzinfo=JST)
    pay = wd.build_payload(HTML, now)
    ok("results_one", len(pay["results"]) == 1)         # Arg-Bra, kicked off within last 24h
    ok("fixtures_one", len(pay["fixtures"]) == 1)        # Spain-Germany, kicks off within next 24h
    ok("standings_two", len(pay["standings"]) == 2)
    ok("result_goals_intact", len(pay["results"][0]["goals"]) == 3)
    ok("fixture_kickoff", "9:00" in pay["fixtures"][0]["kickoff"])
    ok("fixture_kickoff_utc", "UTC-5" in pay["fixtures"][0]["kickoff"])   # offset survives for tz conversion
    ok("fixture_date", pay["fixtures"][0]["date"] == "2026-06-15")   # date carried for tz conversion


def test_rolling_window_beats_venue_date():
    # THE BUG: a match with venue date 06-14 but whose REAL kickoff was 06-15 06:00 UTC.
    # now = 06-16 06:00 JST (06-15 21:00 UTC) -> kicked off only 15h ago. The old calendar
    # filter (today 06-16 minus venue 06-14 = 2 days) WRONGLY dropped it; rolling-24h keeps it.
    html = (
        '<div class="footballbox"><div class="fleft"><time>'
        '<div class="fdate">June 14, 2026<span style="display:none"> '
        '(<span class="bday">2026-06-14</span>)</span></div>'
        '<div class="ftime">11:00 p.m. <a href="/wiki/UTC">UTC-7</a></div></time></div>'
        '<table class="fevent"><tbody><tr itemprop="name">'
        '<th class="fhome" itemprop="homeTeam"><span itemprop="name"><a href="/wiki/Sweden">Sweden</a></span></th>'
        '<th class="fscore"><a href="/wiki/2026_FIFA_World_Cup_Group_F">5–1</a></th>'
        '<th class="faway" itemprop="awayTeam"><span itemprop="name"><a href="/wiki/Tunisia">Tunisia</a></span></th>'
        '</tr></tbody></table></div>'
    )
    now = datetime(2026, 6, 16, 6, 0, tzinfo=JST)
    pay = wd.build_payload(html, now)
    ok("venue_date_lag_kept", len(pay["results"]) == 1)
    ok("venue_date_lag_team", pay["results"][0]["home"]["name"] == "Sweden")
    # And a match that kicked off >24h ago is NOT a result, even if its venue date is "today".
    old = html.replace("2026-06-14", "2026-06-16").replace("11:00 p.m. <a href=\"/wiki/UTC\">UTC-7",
                                                            "1:00 a.m. <a href=\"/wiki/UTC\">UTC+0")
    # 06-16 01:00 UTC kickoff vs now 06-15 21:00 UTC -> in the FUTURE by 4h -> a fixture, not a result.
    pay2 = wd.build_payload(old, now)
    ok("future_not_result", len(pay2["results"]) == 0)


def test_empty_html_safe():
    ok("empty_matches", wd.parse_matches("") == [])
    ok("empty_standings", wd.parse_standings("") == [])
    p = wd.build_payload("", datetime(2026, 6, 15, tzinfo=JST))
    ok("empty_payload", p["results"] == [] and p["fixtures"] == [] and p["standings"] == [])


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
