"""
World Cup message formatter (NF-A3) — PURE rendering of structured match data into
the daily WhatsApp World Cup message. NO network, NO API key, NO LLM: it takes
ALREADY-fetched, structured data (results, standings, fixtures) and lays it out as
WhatsApp text (flag emojis + monospace standings tables). The API-Football fetch and
the optional LLM wrap-up are wired in later (when the api-sports.io key is in .env);
this is the deterministic, testable half, built UNWIRED so it cannot affect anything.

Data shapes the fetch layer must produce:
  Team     = {"name": str, "iso2": str}            # iso2 optional; drives the flag
  match    = {"home": Team, "away": Team, "home_score": int, "away_score": int,
              "goals": [{"team": "home"|"away", "scorer": str, "minute": int|str}]}
  standing = {"group": str, "team": str, "iso2": str, "played": int, "won": int,
              "drawn": int, "lost": int, "gd": int, "points": int}
  fixture  = {"home": Team, "away": Team, "kickoff": str, "date": "YYYY-MM-DD"}
             # kickoff = Wikipedia venue time ("8:00 p.m. UTC-4"); `date` lets us
             # convert it into the operator's display tz (UTC+offset) at render time.

    venv\\Scripts\\python.exe tests\\test_worldcup_format.py
"""
import re
from datetime import datetime, timedelta

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Country name -> ISO-3166 alpha-2, used only when the data gives a name but no code.
# flag_from_iso2 below covers ANY valid code; extend this map as the draw confirms.
COUNTRY_ISO2 = {
    "argentina": "AR", "brazil": "BR", "france": "FR", "england": "GB", "spain": "ES",
    "germany": "DE", "portugal": "PT", "netherlands": "NL", "belgium": "BE", "italy": "IT",
    "croatia": "HR", "uruguay": "UY", "usa": "US", "united states": "US", "mexico": "MX",
    "canada": "CA", "japan": "JP", "south korea": "KR", "korea republic": "KR",
    "australia": "AU", "morocco": "MA", "senegal": "SN", "nigeria": "NG", "ghana": "GH",
    "cameroon": "CM", "egypt": "EG", "ivory coast": "CI", "saudi arabia": "SA", "iran": "IR",
    "qatar": "QA", "ecuador": "EC", "colombia": "CO", "switzerland": "CH", "denmark": "DK",
    "poland": "PL", "serbia": "RS", "pakistan": "PK", "norway": "NO", "sweden": "SE",
    "austria": "AT", "turkey": "TR", "ukraine": "UA", "peru": "PE", "chile": "CL",
    "paraguay": "PY", "new zealand": "NZ", "south africa": "ZA", "algeria": "DZ", "tunisia": "TN",
    # NF-A3: remaining 2026 World Cup nations so every match/standing renders a flag.
    "czech republic": "CZ", "bosnia and herzegovina": "BA", "haiti": "HT", "curaçao": "CW",
    "curacao": "CW", "cape verde": "CV", "iraq": "IQ", "jordan": "JO", "dr congo": "CD",
    "uzbekistan": "UZ", "panama": "PA", "scotland": "GB", "wales": "GB",
}


def flag_from_iso2(iso2):
    """Regional-indicator flag for any ISO-3166 alpha-2 code ('AR' -> 🇦🇷). Returns ''
    for missing/invalid input rather than a broken glyph."""
    if not iso2 or len(iso2) != 2 or not iso2.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in iso2.upper())


def flag(team):
    """Flag for a team dict: prefer its iso2, else its name, else ''."""
    if not isinstance(team, dict):
        return ""
    cc = team.get("iso2") or COUNTRY_ISO2.get((team.get("name") or "").strip().lower(), "")
    return flag_from_iso2(cc)


def _name(team):
    return (team.get("name", "?") if isinstance(team, dict) else "?") or "?"


def _pm(n):
    n = n or 0
    return f"+{n}" if n > 0 else str(n)


def _goals_str(goals, side):
    out = []
    for g in goals or []:
        if g.get("team") != side:
            continue
        sc, mn = g.get("scorer", "?"), g.get("minute", "")
        out.append(f"{sc} {mn}'" if mn not in ("", None) else str(sc))
    return ", ".join(out)


def format_match(match):
    """A result line + goalscorers, e.g.
       🇦🇷 Argentina 2–1 Brazil 🇧🇷
         ⚽ Messi 23', Álvarez 67'  |  Neymar 80'"""
    match = match or {}
    h, a = match.get("home", {}), match.get("away", {})
    hs, as_ = match.get("home_score"), match.get("away_score")
    score = f"{hs}–{as_}" if hs is not None and as_ is not None else "vs"
    line = " ".join(p for p in (flag(h), _name(h), score, _name(a), flag(a)) if p)
    home_g, away_g = _goals_str(match.get("goals"), "home"), _goals_str(match.get("goals"), "away")
    if home_g or away_g:
        line += "\n  ⚽ " + "  |  ".join(p for p in (home_g, away_g) if p)
    return line


def format_results(matches):
    """Part 1 — yesterday's results."""
    if not matches:
        return "*Yesterday's results*\n_No matches in the last 24 hours._"
    return "*Yesterday's results*\n" + "\n".join(format_match(m) for m in matches)


def format_standings(standings):
    """Part 2 — per-group standings, one monospace table per group (no emoji inside
    the table so columns line up; teams shown by short name)."""
    if not standings:
        return ""
    groups = {}
    for r in standings:
        groups.setdefault(r.get("group", "?"), []).append(r)
    blocks = []
    for g in sorted(groups):
        rows = sorted(groups[g], key=lambda r: (-(r.get("points") or 0), -(r.get("gd") or 0)))
        lines = [f"*Group {g}*", "```",
                 f"{'Team':<13}{'P':>2}{'W':>2}{'D':>2}{'L':>2}{'GD':>4}{'Pts':>4}"]
        for r in rows:
            nm = (r.get("team", "?") or "?")[:12]
            lines.append(f"{nm:<13}{r.get('played',0):>2}{r.get('won',0):>2}"
                         f"{r.get('drawn',0):>2}{r.get('lost',0):>2}"
                         f"{_pm(r.get('gd',0)):>4}{(r.get('points') or 0):>4}")
        lines.append("```")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def kickoff_in_tz(date_str, venue_time, offset_hours):
    """Convert a Wikipedia venue kickoff (e.g. '8:00 p.m. UTC-4' on date_str
    'YYYY-MM-DD') into the operator's display tz (UTC+offset_hours). Returns a short
    'Wed 7:00 AM' string, or '' if the input can't be parsed (caller falls back to the
    raw venue string — never crashes). Pure arithmetic: no tz database needed (the host
    has no IANA tzdata; the offset is supplied from config, e.g. Asia/Karachi = +5)."""
    if not date_str or not venue_time or offset_hours is None:
        return ""
    tm = re.search(r"(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)?", venue_time, re.I)
    om = re.search(r"UTC\s*([+-]?\d{1,2})", venue_time, re.I)
    if not tm or not om:
        return ""
    h, mnt = int(tm.group(1)), int(tm.group(2))
    ap = (tm.group(3) or "").lower().replace(".", "")
    if ap == "pm" and h != 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mnt <= 59):
        return ""
    try:
        base = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=h, minute=mnt)
    except (ValueError, TypeError):
        return ""
    disp = base - timedelta(hours=int(om.group(1))) + timedelta(hours=int(offset_hours))
    hr12 = disp.hour % 12 or 12
    return f"{_WEEKDAYS[disp.weekday()]} {hr12}:{disp.minute:02d} {'AM' if disp.hour < 12 else 'PM'}"


def format_fixtures(fixtures, tz_offset_hours=None, tz_label=""):
    """Part: next-24h fixtures. When tz_offset_hours is given, each kickoff is shown in
    the display tz (UTC+offset); otherwise the raw venue string is shown. The display-tz
    label (e.g. 'PKT / UTC+5') goes once in the header, not on every line."""
    if not fixtures:
        return "*Next 24 hours*\n_No matches scheduled._"
    header = "*Next 24 hours*"
    if tz_label:
        header += f" _(kickoff in {tz_label})_"
    out = [header]
    for fx in fixtures:
        h, a = fx.get("home", {}), fx.get("away", {})
        ko = ""
        if tz_offset_hours is not None:
            ko = kickoff_in_tz(fx.get("date"), fx.get("kickoff", ""), tz_offset_hours)
        ko = ko or fx.get("kickoff", "")          # fall back to the raw venue time
        line = " ".join(p for p in (flag(h), _name(h), "vs", _name(a), flag(a)) if p)
        out.append(f"{line} — {ko}" if ko else line)
    return "\n".join(out)


def format_live(live):
    """Matches in progress (kicked off, no final score yet) — without this a match that is
    being played at brief-build time vanishes (it's neither a finished result nor a future
    fixture). Shown as a simple live line; the next slot carries the final score."""
    if not live:
        return ""
    out = ["🔴 *In progress*"]
    for fx in live or []:
        h, a = fx.get("home", {}), fx.get("away", {})
        line = " ".join(p for p in (flag(h), _name(h), "vs", _name(a), flag(a)) if p)
        out.append(f"{line} — _live now_")
    return "\n".join(out)


def format_worldcup_message(results, standings, fixtures, live=None, wrap_up=None,
                            tz_offset_hours=None, tz_label="", reply_line=""):
    """Assemble the full World Cup WhatsApp message. Section order: results -> in-progress
    -> next-24h fixtures -> group standings. wrap_up is the optional written summary
    (generated FROM the same structured data — never news). reply_line is an optional
    closing invite (e.g. 'Any questions, reply'); kept config-driven so the text/toggle
    lives in config, not code."""
    parts = ["🏆 *World Cup 2026 — Daily Update*",
             format_results(results),
             format_live(live),
             format_fixtures(fixtures, tz_offset_hours, tz_label),
             format_standings(standings)]
    if wrap_up:
        parts.append("*Wrap-up*\n" + wrap_up.strip())
    msg = "\n\n".join(p for p in parts if p)
    if reply_line and reply_line.strip():
        msg += "\n\n" + reply_line.strip()
    return msg


# --- Knockout stage rendering (post-group-stage redesign) ------------------
def _flag_name(name):
    """'🇫🇷 France' — the flag (from the name) plus the name; just the name if no flag maps."""
    cc = COUNTRY_ISO2.get((name or "").strip().lower(), "")
    fl = flag_from_iso2(cc)
    return f"{fl} {name}".strip() if fl else (name or "")


def format_ko_result(match):
    """A knockout result with a CLEAR WINNER: 'winner beat loser score' (winner first, score
    read from the winner's side). A draw resolved on penalties is marked '(pens)'. If the winner
    is unknown (a tie whose advancement isn't on the page yet), fall back to a neutral score line."""
    match = match or {}
    h, a = match.get("home", {}), match.get("away", {})
    hs, as_ = match.get("home_score"), match.get("away_score")
    hn, an = _name(h), _name(a)
    winner = match.get("winner")
    if winner in (hn, an) and hs is not None and as_ is not None:
        if winner == hn:
            wn, ln, wf_, lf_, ws, ls = hn, an, flag(h), flag(a), hs, as_
        else:
            wn, ln, wf_, lf_, ws, ls = an, hn, flag(a), flag(h), as_, hs
        pens = " (pens)" if ws == ls else ""
        line = " ".join(p for p in (wf_, wn, "beat", ln, lf_) if p) + f" {ws}–{ls}{pens}"
    else:
        score = f"{hs}–{as_}" if hs is not None and as_ is not None else "vs"
        line = " ".join(p for p in (flag(h), hn, score, an, flag(a)) if p)
    home_g, away_g = _goals_str(match.get("goals"), "home"), _goals_str(match.get("goals"), "away")
    if home_g or away_g:
        line += "\n  ⚽ " + "  |  ".join(p for p in (home_g, away_g) if p)
    return line


def format_ko_results(matches):
    if not matches:
        return ""
    return "⚽ *Results*\n" + "\n".join(format_ko_result(m) for m in matches)


def format_ko_live(live):
    """In-progress matches — the result lands in the NEXT update (your 'to be announced' ask)."""
    if not live:
        return ""
    out = ["🔴 *Playing now* — result in the next update"]
    for fx in live:
        h, a = fx.get("home", {}), fx.get("away", {})
        out.append(" ".join(p for p in (flag(h), _name(h), "vs", _name(a), flag(a)) if p))
    return "\n".join(out)


def format_ko_fixtures(fixtures, tz_offset_hours=None, tz_label=""):
    if not fixtures:
        return ""
    header = "⏭ *Next up*"
    if tz_label:
        header += f" _(kickoff {tz_label})_"
    out = [header]
    for fx in fixtures:
        h, a = fx.get("home", {}), fx.get("away", {})
        ko = ""
        if tz_offset_hours is not None:
            ko = kickoff_in_tz(fx.get("date"), fx.get("kickoff", ""), tz_offset_hours)
        ko = ko or fx.get("kickoff", "")
        line = " ".join(p for p in (flag(h), _name(h), "vs", _name(a), flag(a)) if p)
        out.append(f"{line} — {ko}" if ko else line)
    return "\n".join(out)


def format_eliminated(teams):
    """Cumulative knocked-out list, NEWEST FIRST (the caller orders it)."""
    if not teams:
        return ""
    return "❌ *Knocked out* _(newest first)_\n" + " · ".join(_flag_name(t) for t in teams)


def format_still_alive(through, yet, current_round, next_round):
    """Still-alive split in two: teams already THROUGH to the next round, and teams YET TO PLAY
    the current round."""
    blocks = []
    if through:
        blocks.append(f"🟢 *Through to {next_round}*\n" + " · ".join(_flag_name(t) for t in through))
    if yet:
        blocks.append(f"⏳ *{current_round} — yet to play*\n" + " · ".join(_flag_name(t) for t in yet))
    return "\n\n".join(blocks)


def format_knockout_message(payload, tz_offset_hours=None, tz_label="", reply_line=""):
    """Assemble the knockout WhatsApp message: round header -> results (with winners) -> playing
    now -> next up -> knocked out -> still alive (through / yet to play). No group tables."""
    p = payload or {}
    cur = p.get("current_round") or "Knockout stage"
    parts = [f"🏆 *World Cup 2026 — {cur}*",
             format_ko_results(p.get("results") or []),
             format_ko_live(p.get("live") or []),
             format_ko_fixtures(p.get("fixtures") or [], tz_offset_hours, tz_label),
             format_eliminated(p.get("eliminated") or []),
             format_still_alive(p.get("through") or [], p.get("yet_to_play") or [],
                                cur, p.get("next_round") or "the next round")]
    msg = "\n\n".join(x for x in parts if x)
    if reply_line and reply_line.strip():
        msg += "\n\n" + reply_line.strip()
    return msg
