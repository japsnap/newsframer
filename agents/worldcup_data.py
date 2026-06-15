"""
World Cup data from Wikipedia (NF-A3) — fetch + parse the structured WC data
(match results with goalscorers+minute, fixtures, group standings) from the public
"2026 FIFA World Cup" Wikipedia page. Free, no API key, no paid tier.

LOCKED source (verified read-only 2026-06-15): the one page carries 131 match boxes
with clean results, scorer+minute (incl. stoppage-time "90+4'"), kickoff times, and
group standings tables. The RSS football feeds are for colour/narrative ONLY; the
numbers come ONLY from here (anti-hallucination, spec §4.3).

The parse_* functions are PURE + deterministic (unit-tested against fixture HTML);
fetch() is the only I/O. Output feeds agents/worldcup_format.py directly:
  match    = {date, time, home:{name}, away:{name}, home_score, away_score,
              goals:[{team:'home'|'away', scorer, minute}], played:bool}
  standing = {group, team, played, won, drawn, lost, gd, points}

Parse DEFENSIVELY: Wikipedia is community-edited, so a missing/odd cell drops that
one item rather than raising (a once-daily pull after matches settle is reliable).

    venv\\Scripts\\python.exe tests\\test_worldcup_data.py
"""
import re
from datetime import datetime

WIKI_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup"
_UA = {"User-Agent": "NewsFramer/1.0 (worldcup parser; personal use)"}


def fetch(url=WIKI_URL, timeout=35):
    """The only I/O. Returns the page HTML (str)."""
    import requests
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r.text


# --- pure helpers ----------------------------------------------------------
def _clean(s):
    s = s or ""
    s = re.sub(r"(?s)<style[^>]*>.*?</style>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("−", "-")                 # keep the unicode minus (goal difference)
    s = re.sub(r"&#8722;|&minus;", "-", s)
    s = re.sub(r"&#160;|&nbsp;", " ", s)
    s = re.sub(r"&#?[a-zA-Z0-9]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _team(block, prop):
    """Team name from the <th itemprop="homeTeam|awayTeam"> ... first <a> link text."""
    m = re.search(r'itemprop="' + prop + r'".*?<span itemprop="name">(.*?)</span>\s*</th>', block, re.S)
    seg = m.group(1) if m else ""
    a = re.search(r"<a[^>]*>([^<]+)</a>", seg)
    name = _clean(a.group(1)) if a else _clean(seg)
    return name or None


def _goals(block, cls, side):
    """Goals from the <td class="fhgoal|fagoal"> list: each <li> = a scorer + its
    minute span(s) like <span>9'</span> / <span>90+4'</span>."""
    m = re.search(r'class="' + cls + r'">(.*?)</td>', block, re.S)
    if not m:
        return []
    seg, goals = m.group(1), []
    for li in re.findall(r"(?s)<li>(.*?)</li>", seg):
        a = re.search(r"<a[^>]*>([^<]+)</a>", li)
        scorer = _clean(a.group(1)) if a else (_clean(li).split(" ")[0] if _clean(li) else "?")
        for mn in re.findall(r"<span>\s*(\d+(?:\+\d+)?)'\s*</span>", li):
            goals.append({"team": side, "scorer": scorer, "minute": mn})
    return goals


def _parse_box(b):
    home, away = _team(b, "homeTeam"), _team(b, "awayTeam")
    if not home or not away:
        return None
    dm = re.search(r'class="bday[^"]*">(\d{4}-\d{2}-\d{2})</span>', b)
    # Grab the WHOLE ftime div, not just the leading text: the UTC offset lives inside an
    # <a>UTC-4</a> anchor, so a "[^<]+" stop loses it (and the kickoff can't be converted
    # to the operator's tz). _clean strips the tags, leaving e.g. "8:00 p.m. UTC-4".
    tm = re.search(r'class="ftime">(.*?)</div>', b, re.S)
    sm = re.search(r'class="fscore">(?:<a[^>]*>)?([^<]+)', b)
    raw = _clean(sm.group(1)) if sm else ""
    played = bool(re.match(r"^\d+\s*[–-]\s*\d+$", raw))
    hs = a_s = None
    if played:
        p = re.split(r"[–-]", raw)
        try:
            hs, a_s = int(p[0].strip()), int(p[1].strip())
        except (ValueError, IndexError):
            played = False
    gm = re.search(r"2026_FIFA_World_Cup_Group_([A-L])", b)
    return {
        "date": dm.group(1) if dm else None,
        "time": _clean(tm.group(1)) if tm else None,
        "group": gm.group(1) if gm else None,
        "home": {"name": home}, "away": {"name": away},
        "home_score": hs, "away_score": a_s,
        "goals": _goals(b, "fhgoal", "home") + _goals(b, "fagoal", "away"),
        "played": played,
    }


def parse_matches(html):
    """All match boxes -> match dicts (played ones have scores+goals; the rest are
    fixtures with played=False)."""
    starts = [m.start() for m in re.finditer(r'class="footballbox"', html or "")]
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(html)
        box = _parse_box(html[s:e])
        if box:
            out.append(box)
    return out


def _pmint(s):
    s = (s or "").replace("−", "-").replace("+", "").strip()  # unicode minus -> ascii
    try:
        return int(s)
    except ValueError:
        return 0


def _standings_rows(thtml, group):
    out = []
    for row in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", thtml):
        vals = [_clean(c) for c in re.findall(r"(?s)<t[hd][^>]*>(.*?)</t[hd]>", row)]
        if len(vals) < 10 or not re.match(r"^\d+$", vals[0]):
            continue  # skip header / malformed rows
        team = re.sub(r"\s*\(.\)\s*$", "", vals[1]).strip()  # drop host "(H)" marker
        try:
            out.append({"group": group, "team": team, "played": int(vals[2]),
                        "won": int(vals[3]), "drawn": int(vals[4]), "lost": int(vals[5]),
                        "gd": _pmint(vals[8]), "points": int(vals[9])})
        except (ValueError, IndexError):
            continue
    return out


def parse_standings(html):
    """Group standings -> standing dicts. Finds every standings wikitable (one that
    has both 'Pld' and 'Pts') and labels it from the nearest preceding 'Group X'
    heading — robust to Wikipedia giving played groups a duplicate section id."""
    html = html or ""
    team_group = {}                      # team name -> group, learned from the match boxes
    for m in parse_matches(html):
        if m.get("group"):
            team_group[m["home"]["name"]] = m["group"]
            team_group[m["away"]["name"]] = m["group"]
    out = []
    for tm in re.finditer(r"(?s)<table[^>]*?wikitable[^>]*?>.*?</table>", html):
        thtml = tm.group(0)
        if "Pts" not in thtml or "Pld" not in thtml:
            continue
        before = html[max(0, tm.start() - 1600): tm.start()]
        hm = re.findall(r"Group ([A-L])\b", before)
        heading_g = hm[-1] if hm else None
        for row in _standings_rows(thtml, None):
            row["group"] = team_group.get(row["team"]) or heading_g or "?"
            out.append(row)
    return out


def build_payload(html, now, result_window_days=1, fixture_window_days=1):
    """Filter parsed data to last-Nd results + next-Nd fixtures + all standings, in
    the exact shape agents/worldcup_format expects. `now` is a tz-aware datetime
    (use JST so the day window matches the brief)."""
    today = now.date()
    results, fixtures = [], []
    for m in parse_matches(html):
        if not m.get("date"):
            continue
        try:
            d = datetime.strptime(m["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if m["played"] and m["home_score"] is not None:
            if 0 <= (today - d).days <= result_window_days:
                results.append({"home": m["home"], "away": m["away"],
                                "home_score": m["home_score"], "away_score": m["away_score"],
                                "goals": m["goals"]})
        elif not m["played"]:
            if 0 <= (d - today).days <= fixture_window_days:
                fixtures.append({"home": m["home"], "away": m["away"],
                                 "kickoff": m.get("time", ""), "date": m["date"]})
    return {"results": results, "standings": parse_standings(html), "fixtures": fixtures}
