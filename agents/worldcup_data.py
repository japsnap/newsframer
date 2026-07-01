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
from datetime import datetime, timezone, timedelta

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


def _points(s):
    """Points cell — tolerant of a trailing tiebreak footnote letter, e.g. '1 a' -> 1, '3' -> 3.
    Wikipedia marks teams level on points with a letter (the head-to-head group); the old
    int('1 a') threw and DROPPED every tied team's row, so groups level on points (G, H on
    2026-06-19) rendered empty (item 6, 're-verify all 12 group tables')."""
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else 0


def _standings_rows(thtml, group):
    out = []
    for row in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", thtml):
        vals = [_clean(c) for c in re.findall(r"(?s)<t[hd][^>]*>(.*?)</t[hd]>", row)]
        if len(vals) < 10 or not re.match(r"^\d+$", vals[0]):
            continue  # skip header / malformed rows
        # Drop trailing host/qualified markers: "(H)", "(H, Q)", "(Q)", even "(H)(Q)". The old
        # single-char "(.)" form missed "(H, Q)" -> the team name kept the marker, the team->group
        # lookup failed, and that row fell into a phantom "Group ?" (item 6, 2026-06-19).
        team = re.sub(r"(?:\s*\([^)]*\))+\s*$", "", vals[1]).strip()
        try:
            out.append({"group": group, "team": team, "played": int(vals[2]),
                        "won": int(vals[3]), "drawn": int(vals[4]), "lost": int(vals[5]),
                        "gd": _pmint(vals[8]), "points": _points(vals[9])})
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


def _kickoff_utc(date_str, time_str):
    """Real UTC kickoff from the Wikipedia date + venue time ('8:00 p.m. UTC-4'). Returns
    an aware UTC datetime, or None if either piece can't be parsed (caller then falls back
    to a calendar-day window). This is what makes the result/fixture windows a TRUE rolling
    24h instead of a venue-date cut — the 2026 venues sit in the US (UTC-4..-7), so a venue
    'date' can be a day behind real time."""
    if not date_str or not time_str:
        return None
    tm = re.search(r"(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)?", time_str, re.I)
    om = re.search(r"UTC\s*([+-]?\d{1,2})", time_str, re.I)
    if not tm or not om:
        return None
    h, mn = int(tm.group(1)), int(tm.group(2))
    ap = (tm.group(3) or "").lower().replace(".", "")
    if ap == "pm" and h != 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mn <= 59):
        return None
    try:
        venue = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=h, minute=mn, tzinfo=timezone.utc)
    except ValueError:
        return None
    return venue - timedelta(hours=int(om.group(1)))   # venue-local -> UTC


def build_payload(html, now, result_window_hours=24, fixture_window_hours=24, live_window_hours=4):
    """Bucket matches around `now` (tz-aware, pass JST) by their REAL kickoff time — a true
    rolling window, NOT a calendar-day cut:
      results  = FINISHED matches that kicked off within the last `result_window_hours`.
      live     = matches that kicked off in the last `live_window_hours` but have NO final
                 score yet (in progress) — without this they fall in the gap between the two
                 windows and vanish (a match kicked off but not finished is neither a result
                 nor a future fixture).
      fixtures = matches kicking off within the next `fixture_window_hours`.
    A match whose kickoff time can't be parsed falls back to a date window so it's never lost."""
    now_utc = now.astimezone(timezone.utc)
    today = now.date()
    rd = max(1, round(result_window_hours / 24))
    fd = max(1, round(fixture_window_hours / 24))
    results, fixtures, live = [], [], []
    for m in parse_matches(html):
        if not m.get("date"):
            continue
        try:
            d = datetime.strptime(m["date"], "%Y-%m-%d").date()
        except ValueError:
            d = None
        ku = _kickoff_utc(m.get("date"), m.get("time"))
        if m["played"] and m["home_score"] is not None:
            keep = (0 <= (now_utc - ku).total_seconds() <= result_window_hours * 3600) if ku is not None \
                else (d is not None and 0 <= (today - d).days <= rd)
            if keep:
                results.append({"home": m["home"], "away": m["away"],
                                "home_score": m["home_score"], "away_score": m["away_score"],
                                "goals": m["goals"]})
        elif not m["played"]:
            entry = {"home": m["home"], "away": m["away"], "kickoff": m.get("time", ""), "date": m["date"]}
            if ku is not None:
                ahead = (ku - now_utc).total_seconds()
                if 0 <= ahead <= fixture_window_hours * 3600:
                    fixtures.append(entry)
                elif -live_window_hours * 3600 <= ahead < 0:   # kicked off recently, no final score -> live
                    live.append(entry)
            elif d is not None and 0 <= (d - today).days <= fd:
                fixtures.append(entry)
    return {"results": results, "live": live, "standings": parse_standings(html), "fixtures": fixtures}


# --- Knockout stage (post-group-stage redesign) ----------------------------
# FIFA fixed match numbering for the 48-team 2026 bracket: group stage = 1-72, then
# R32 = 73-88 (16), R16 = 89-96 (8), QF = 97-100, SF = 101-102, 3rd place = 103, Final = 104.
KO_SEQUENCE = ["Round of 32", "Round of 16", "Quarter-finals", "Semi-finals", "Final"]


def round_for_match_number(n):
    """Knockout round name for a FIFA match number (None for group-stage / unknown)."""
    if not isinstance(n, int):
        return None
    if 73 <= n <= 88:
        return "Round of 32"
    if 89 <= n <= 96:
        return "Round of 16"
    if 97 <= n <= 100:
        return "Quarter-finals"
    if 101 <= n <= 102:
        return "Semi-finals"
    if n == 103:
        return "Third place"
    if n == 104:
        return "Final"
    return None


def next_round(round_name):
    """The round a winner of `round_name` advances to (None past the Final / for a side match
    like 'Third place')."""
    try:
        i = KO_SEQUENCE.index(round_name)
    except ValueError:
        return None
    return KO_SEQUENCE[i + 1] if i + 1 < len(KO_SEQUENCE) else None


_PLACEHOLDER_RE = re.compile(r"^\s*(winner|loser|runner[-\s]?up)\b", re.I)


def is_placeholder_team(name):
    """True for bracket placeholders like 'Winner Match 83' / 'Runner-up Group A' / 'Loser Match 101'
    (and empty) — teams not yet determined, which must never be listed as real teams."""
    if not name or not name.strip():
        return True
    n = name.strip()
    if _PLACEHOLDER_RE.match(n):
        return True
    if re.search(r"\bmatch\s+\d+", n, re.I):
        return True
    return False


def _real_names(match):
    out = []
    for side in ("home", "away"):
        nm = (match.get(side) or {}).get("name")
        if nm and not is_placeholder_team(nm):
            out.append(nm)
    return out


def match_winner_name(match, advancing):
    """The winning team's name, or None if unplayed / undetermined. Decisive score -> higher score.
    A draw means it went to penalties (a.e.t.) — the winner is then whichever side is known to have
    ADVANCED (appears in a later bracket match); `advancing` is that set of team names."""
    if not match.get("played"):
        return None
    hs, as_ = match.get("home_score"), match.get("away_score")
    if hs is None or as_ is None:
        return None
    h = (match.get("home") or {}).get("name")
    a = (match.get("away") or {}).get("name")
    if hs > as_:
        return h
    if as_ > hs:
        return a
    adv = advancing or set()
    if h in adv and a not in adv:
        return h
    if a in adv and h not in adv:
        return a
    return None   # tie with no advancement info yet -> unknown (rendered without a winner)


def _round_idx(round_name):
    """Order key for advancement: R32<R16<QF<SF<Final. Off-sequence (Third place / None) = -1."""
    try:
        return KO_SEQUENCE.index(round_name)
    except ValueError:
        return -1


def derive_knockout_state(matches):
    """From a list of knockout match dicts (each carrying `round`, teams, scores, played; `number`
    optional), derive the tournament state for the redesigned message:
      current_round / next_round,
      results   = played matches, each with a resolved `winner` (penalty-aware),
      eliminated = losers, NEWEST FIRST (cumulative — the group stage is over),
      through    = real teams already into the NEXT round,
      yet_to_play = real teams still to play the CURRENT round.
    Keys off ROUND (robust: played boxes don't expose a match number), not the number.
    Pure: no HTML, no time windows (windowing of results/fixtures happens upstream)."""
    ko = [m for m in matches if m.get("round")]

    results, elim_order = [], []
    for m in ko:
        if not m.get("played") or m.get("home_score") is None:
            continue
        mi = _round_idx(m["round"])
        later_teams = set()
        for m2 in ko:
            if _round_idx(m2["round"]) > mi:          # a later round == advanced past this match
                later_teams.update(_real_names(m2))
        w = match_winner_name(m, later_teams)
        r = dict(m)
        r["winner"] = w
        results.append(r)
        if w:
            loser = next((nm for nm in _real_names(m) if nm != w), None)
            if loser:
                elim_order.append((m.get("date") or "", mi, m.get("number") or 0, loser))
    elim_order.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)   # newest first
    eliminated = [t[3] for t in elim_order]

    seq_unplayed = sorted({_round_idx(m["round"]) for m in ko
                           if not m.get("played") and _real_names(m) and _round_idx(m["round"]) >= 0})
    if seq_unplayed:
        current = KO_SEQUENCE[seq_unplayed[0]]
    else:
        played = [m["round"] for m in ko if m.get("played") and _round_idx(m["round"]) >= 0]
        current = played[-1] if played else None
    nxt = next_round(current) if current else None

    def _collect(pred):
        seen, out = set(), []
        for m in ko:
            if pred(m):
                for nm in _real_names(m):
                    if nm not in seen:
                        seen.add(nm)
                        out.append(nm)
        return out

    through = _collect(lambda m: m.get("round") == nxt) if nxt else []
    yet_to_play = _collect(lambda m: m.get("round") == current and not m.get("played"))

    return {"current_round": current, "next_round": nxt, "results": results,
            "eliminated": eliminated, "through": through, "yet_to_play": yet_to_play}


# --- Knockout HTML parsing (round + match number attach) -------------------
_KO_HEAD_RE = re.compile(r'id="(Round_of_32|Round_of_16|Quarter-finals|Semi-finals|Third_place_play-off|Final)"')
_KO_HATNOTE_RE = re.compile(r'2026 FIFA World Cup (round of 32|round of 16|quarter-finals|semi-finals)', re.I)


def _norm_round(s):
    s = (s or "").strip().lower().replace("_", " ").replace("-", "-")
    return {
        "round of 32": "Round of 32", "round_of_32": "Round of 32",
        "round of 16": "Round of 16", "round_of_16": "Round of 16",
        "quarter-finals": "Quarter-finals", "semi-finals": "Semi-finals",
        "third place play-off": "Third place", "third_place_play-off": "Third place",
        "final": "Final",
    }.get(s, None)


def _round_markers(html):
    marks = []
    for m in _KO_HEAD_RE.finditer(html):
        r = _norm_round(m.group(1).replace("_", " "))
        if r:
            marks.append((m.start(), r))
    for m in _KO_HATNOTE_RE.finditer(html):
        r = _norm_round(m.group(1))
        if r:
            marks.append((m.start(), r))
    marks.sort()
    return marks


def _nearest_round(marks, pos):
    best = None
    for mp, lab in marks:
        if mp <= pos:
            best = lab
        else:
            break
    return best


def _match_number(box):
    m = re.search(r'id="[Mm]atch[ _]?(\d{1,3})"', box) or re.search(r'>\s*Match\s+(\d{1,3})\s*<', box)
    return int(m.group(1)) if m else None


def parse_knockout_matches(html):
    """Every KNOCKOUT match box (group boxes excluded), enriched with `number` (when the box
    exposes it) and `round` (from the number if present, else the nearest section heading)."""
    html = html or ""
    marks = _round_markers(html)
    starts = [m.start() for m in re.finditer(r'class="footballbox"', html)]
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(html)
        box = html[s:e]
        if "2026_FIFA_World_Cup_Group_" in box:
            continue
        parsed = _parse_box(box)
        if not parsed:
            continue
        num = _match_number(box)
        parsed["number"] = num
        parsed["round"] = round_for_match_number(num) if num else _nearest_round(marks, s)
        out.append(parsed)
    return out


def build_knockout_payload(html, now, result_window_hours=48, fixture_window_hours=48, live_window_hours=4):
    """The knockout-stage counterpart of build_payload. Derives the full state (current/next round,
    eliminated newest-first, through / yet-to-play) from ALL knockout matches, then windows the
    DISPLAY lists by real kickoff time:
      results  = finished matches in the last `result_window_hours`, each with a resolved `winner`
      live     = current-round matches kicked off but unfinished ('result in the next update')
      fixtures = REAL (both-determined) current-round matches in the next `fixture_window_hours`
    Placeholder bracket slots ('Winner Match 83') never appear as fixtures."""
    now_utc = now.astimezone(timezone.utc)
    today = now.date()
    matches = parse_knockout_matches(html)
    state = derive_knockout_state(matches)
    cur = state["current_round"]
    winner_of = {(r["home"]["name"], r["away"]["name"], r.get("date")): r.get("winner")
                 for r in state["results"]}

    def _within_days(dstr, span_h, ahead=False):
        try:
            d = datetime.strptime(dstr, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return False
        delta = (d - today).days if ahead else (today - d).days
        return 0 <= delta <= max(1, round(span_h / 24))

    results, live, fixtures = [], [], []
    for m in matches:
        rnd = m.get("round")
        if not rnd:
            continue
        ku = _kickoff_utc(m.get("date"), m.get("time"))
        if m.get("played") and m.get("home_score") is not None:
            keep = (0 <= (now_utc - ku).total_seconds() <= result_window_hours * 3600) if ku is not None \
                else _within_days(m.get("date"), result_window_hours)
            if keep:
                results.append({"home": m["home"], "away": m["away"],
                                "home_score": m["home_score"], "away_score": m["away_score"],
                                "goals": m["goals"], "round": rnd,
                                "winner": winner_of.get((m["home"]["name"], m["away"]["name"], m.get("date")))})
        elif not m.get("played"):
            if rnd != cur:                                   # only the current round is 'next up'
                continue
            if is_placeholder_team(m["home"].get("name")) or is_placeholder_team(m["away"].get("name")):
                continue
            entry = {"home": m["home"], "away": m["away"], "kickoff": m.get("time", ""),
                     "date": m["date"], "round": rnd}
            if ku is not None:
                ahead = (ku - now_utc).total_seconds()
                if 0 <= ahead <= fixture_window_hours * 3600:
                    fixtures.append(entry)
                elif -live_window_hours * 3600 <= ahead < 0:
                    live.append(entry)
            elif _within_days(m.get("date"), fixture_window_hours, ahead=True):
                fixtures.append(entry)

    payload = dict(state)
    payload["results"] = results     # windowed for display; derivation already used the full set
    payload["live"] = live
    payload["fixtures"] = fixtures
    payload["standings"] = []        # knockout has no group tables (keeps the runner's shape)
    return payload
