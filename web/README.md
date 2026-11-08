# newsframer-web

The website for NewsFramer, served at https://newsframer.wasaku.app.

NewsFramer is an open-source tool that reads the RSS sources you choose each morning, drops
duplicates and noise, scores each story against your topics, and has Claude (on your own Claude
plan, through Claude Code) write one themed brief with every source cited, saved as Markdown and
JSON. The engine lives in its own public repo: https://github.com/japsnap/newsframer

NewsFramer has been paused since 26 September 2026. From June to that day it sent 148 briefings,
with 9,263 article deliveries from 69 RSS sources. Claude and ChatGPT now offer much of this in
chat, so the daily run has stopped. The site stays up as a record and a pointer to
the code.

## Pages

- `/` says what NewsFramer is, that it is paused, what it did, and how it works, and links to the
  engine repo. Its first screen is also the NewsFramer card image on https://wasaku.app.
- `/brief` shows what a finished brief looks like, built to the writer's real output format.
- `/console` is the old working surface for interests, hypotheses, sources and engine settings. It
  is no longer linked from the site and carries a paused note, because the engine it edits does
  not run.

## Running it

```powershell
npm install
npm run dev
```

Environment variables, the Supabase table the console wires to, and what is live versus read only
are in [DEPLOY-NOTES.md](./DEPLOY-NOTES.md).

## Layout

```
app/          the three pages
components/   site chrome, logo, console panels (cascade.tsx is no longer used)
lib/          types mirrored from the engine, sample data, Supabase access
```
