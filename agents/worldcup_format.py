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
  fixture  = {"home": Team, "away": Team, "kickoff": str}   # kickoff pre-formatted (JST)

    venv\\Scripts\\python.exe tests\\test_worldcup_format.py
"""

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


def format_fixtures(fixtures):
    """Part 3 — next-24h fixtures."""
    if not fixtures:
        return "*Next 24 hours*\n_No matches scheduled._"
    out = ["*Next 24 hours*"]
    for fx in fixtures:
        h, a = fx.get("home", {}), fx.get("away", {})
        ko = fx.get("kickoff", "")
        line = " ".join(p for p in (flag(h), _name(h), "vs", _name(a), flag(a)) if p)
        out.append(f"{line} — {ko}" if ko else line)
    return "\n".join(out)


def format_worldcup_message(results, standings, fixtures, wrap_up=None):
    """Assemble the full 3-part World Cup WhatsApp message. wrap_up is the optional
    written summary (added later, generated FROM the same structured data — never news)."""
    parts = ["🏆 *World Cup 2026 — Daily Update*",
             format_results(results),
             format_standings(standings),
             format_fixtures(fixtures)]
    if wrap_up:
        parts.append("*Wrap-up*\n" + wrap_up.strip())
    return "\n\n".join(p for p in parts if p)
