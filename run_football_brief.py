"""
NewsFramer — daily Football news WhatsApp message (NF-A2). A self-contained RSS-headline
digest (agents/event_feed) delivered as its OWN WhatsApp message, separate from the World
Cup message and the main brief. NO LLM, NO DB, NO writer/litellm import — so it can NEVER
crash or block the other two. WhatsApp-only (never Telegram).

Config-gated: it rides the existing 11:00 WhatsApp dispatch only when `football_enabled: true`
(default false => nothing changes). Standalone, this script always BUILDS + prints for
verification regardless of the flag; only `--send` posts.

TEMPLATE: agents/event_feed is topic-agnostic. To run another event after the World Cup,
add a `<event>_feeds/<event>_header/...` block to config/models.yaml, copy this runner, and
add a maybe_send_<event>() call in run_whatsapp_brief — no engine changes.

Delivery reuses `openclaw message send` to the `wikibot` account, to every chat in
config/whatsapp_deliveries.yaml not opted out with `football: false`. Confirmed-send gate
(§4.3 principle): a target counts only if the gateway returns a real messageId; a failure
alerts and is not counted. The message carries NO DB article_ids — nothing is recorded in
`deliveries`.

Usage:
  python run_football_brief.py          # dry run: fetch feeds + build + print the message
  python run_football_brief.py --send    # build + post to the WhatsApp group + Muda's DM
"""
import os
import re
import sys
import subprocess
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "agents"))
import event_feed as ef        # noqa: E402  (pure digest: requests + feedparser only)
import deliver as dlv          # noqa: E402  (send_alert — lightweight: yaml + requests, no litellm)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REGISTRY_PATH = os.path.join(BASE, "config", "whatsapp_deliveries.yaml")
OPENCLAW_MJS = os.environ.get(
    "OPENCLAW_MJS",
    os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "openclaw", "openclaw.mjs"),
)


def _cfg():
    try:
        import yaml
        with open(os.path.join(BASE, "config", "models.yaml"), encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_registry():
    """The gitignored per-chat WhatsApp registry (group JID + DM numbers). Targets/numbers
    live ONLY here, never in tracked config."""
    try:
        import yaml
        if os.path.exists(REGISTRY_PATH):
            with open(REGISTRY_PATH, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def build_from_config(cfg, now=None):
    """Fetch the configured football feeds and build the WhatsApp digest ('' when nothing in
    window). The only I/O is the per-feed fetch, each wrapped so one dead feed can't sink the
    message. `now` defaults to UTC now (injectable for tests)."""
    cfg = cfg or {}
    feeds = cfg.get("football_feeds", []) or []
    now = now or datetime.now(timezone.utc)
    data = []
    for fd in feeds:
        url = (fd or {}).get("url")
        name = (fd or {}).get("name") or "Football"
        if not url:
            continue
        try:
            data.append((name, ef.fetch(url, int(cfg.get("football_fetch_timeout", 25)))))
        except Exception as e:
            print(f"  Football: feed FAILED {name}: {type(e).__name__}: {e}")
    return ef.build_message(
        data, now,
        window_hours=int(cfg.get("football_window_hours", 24)),
        max_items=int(cfg.get("football_max_items", 10)),
        max_per_source=int(cfg.get("football_max_per_source", 3)),
        header=cfg.get("football_header", "⚽ *Football — Today's Headlines*"),
        include_links=bool(cfg.get("football_include_links", True)),
        reply_line=cfg.get("football_reply_line", ""),
    )


# --- delivery (mirrors run_worldcup_brief; duplicated so this job stays independent) -------
def send_whatsapp(text, account, target):
    cmd = ["node", OPENCLAW_MJS, "message", "send", "--channel", "whatsapp",
           "--account", account, "--target", target, "--message", text, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or "")[-400:], (r.stderr or "")[-200:]


def confirmed_message_id(rc, stdout):
    """Confirmed only if rc==0 AND the gateway returned a real messageId."""
    if rc != 0:
        return None
    m = re.search(r'"messageId"\s*:\s*"?([^",}\s]+)', stdout or "")
    return m.group(1) if m else None


def deliver(msg, reg):
    """Send the football message to every registry chat NOT opted out (`football: false`).
    One target's failure (or exception) alerts via the newsframer bot and is not counted; it
    never stops the other targets. Returns (confirmed, attempted)."""
    account = reg.get("account", "wikibot")
    targets = [d for d in reg.get("deliveries", []) if d.get("football", True) and d.get("target")]
    if not targets:
        print("  Football delivery: no WhatsApp targets (registry empty or all opted out) — nothing sent.")
        return 0, 0
    confirmed = 0
    for d in targets:
        name = d.get("name", "?")
        try:
            rc, out, err = send_whatsapp(msg, account, d["target"])
            mid = confirmed_message_id(rc, out)
            print(f"  [Football -> {name}] rc={rc} messageId={mid} {(out or '')[:120]}")
            if mid:
                confirmed += 1
            else:
                dlv.send_alert(f"\U0001f6a8 NewsFramer Football: WhatsApp send FAILED for {name} (rc={rc}) — not counted.")
        except Exception as e:
            print(f"  [Football -> {name}] EXCEPTION {type(e).__name__}: {e}")
            try:
                dlv.send_alert(f"\U0001f6a8 NewsFramer Football: send EXCEPTION for {name}: {type(e).__name__} — not counted.")
            except Exception:
                pass
    return confirmed, len(targets)


def main():
    send = "--send" in sys.argv[1:]
    cfg = _cfg()
    if not cfg.get("football_enabled", False):
        print("run_football: NOTE football_enabled=false — this builds/prints for verification, "
              "but the 11:00 dispatch will NOT include it until you set football_enabled: true.")
    now = datetime.now(timezone.utc)
    try:
        msg = build_from_config(cfg, now)
    except Exception as e:
        print(f"run_football: SKIP — build failed: {type(e).__name__}: {e}")
        return 3
    if not msg:
        print("run_football: SKIP (no empty send) — nothing in the window.")
        return 2
    print(f"run_football: chars={len(msg)} (now {now:%Y-%m-%d %H:%M} UTC)")
    print("-" * 60)
    print(msg)
    print("-" * 60)
    if not send:
        print("\nDRY RUN — nothing sent. Re-run with --send to post to the WhatsApp group + Muda's DM.")
        return 0
    reg = load_registry()
    confirmed, attempted = deliver(msg, reg)
    print(f"\nFootball delivery: {confirmed}/{attempted} target(s) confirmed.")
    return 0 if (attempted and confirmed == attempted) else (1 if attempted else 0)


if __name__ == "__main__":
    sys.exit(main())
