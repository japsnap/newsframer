# Deploy notes

The web front end for NewsFramer. Next.js App Router, Tailwind v4, deployed on Vercel.

## Environment variables

Only two, and both are optional. With neither one set the site builds and runs in demo mode,
shows a "Demo data, not connected" banner on the console, and works on sample rows.

| Name | Needed for | Where to get it |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Reading and writing the real interests and hypotheses | Supabase project settings, API, Project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | The same | Supabase project settings, API, the anon public key |

Set them in Vercel under Project, Settings, Environment Variables. Both are read at build time,
so redeploy after adding them.

**Never put the service role key here.** These values ship to the browser. The anon key is the
only Supabase key that is safe in a public front end, and it is only safe when row level security
is switched on for the table.

The engine's own secrets stay on the engine's machine in its `.env` file. This app never reads
that file and never needs it.

## The Supabase table

The console reads and writes exactly one table: **`user_context`**.

Columns used: `id`, `kind`, `topic`, `weight`, `stance`, `confidence`, `reasoning`,
`specificity`, `status`, `active`, `created_at`. This matches the engine's
`user_context.example.sql`. Nothing else in the engine's database is touched.

Rows where `kind` is `interest` appear on the Interests tab. Rows where `kind` is `hypothesis`
appear on the Hypotheses tab.

### Row level security

The anon key can only do what your policies allow. For the console to work you need a read policy
and an update policy on `user_context`. The console never inserts and never deletes, so it needs
no policy for either. If you would rather keep the table completely private, leave the environment
variables unset and the site stays in demo mode.

## What is live and what is not

| Tab | Status |
|---|---|
| Interests | Live read and write against `user_context` when credentials are present |
| Hypotheses | Live read and write against `user_context` when credentials are present |
| Sources | Read only. The engine writes this table mid run, so a browser write would race it |
| Tuning | Viewer. The engine reads its own `config/models.yaml` off its local disk, which this site cannot reach. Your edits are kept in browser storage as a plan |

Every write goes through a confirm step that lists each field as `old value → new value`.
Nothing is ever written silently. After a save, each row is read straight back from the table,
so the screen shows what the database actually holds.

## Local development

```powershell
npm install
npm run dev
```

Then open http://localhost:3000. Without environment variables it runs in demo mode, which is
the fastest way to work on the interface.

## Deploy

```powershell
npx vercel --prod --yes
```

## Where the numbers come from

Everything quoted on the landing page and in the tuning panel was read out of the engine at
`documents/aiautomation/workflow/newsframer`:

- 61 sources across 7 bundles: `sql/seed_sources.sql`
- Roughly 600 fetched per run: 61 sources at the `light` fetch profile of 10 each
- Nine themes: `theme_count_multiplier` of 1.5 across six bundles with theme floors
- Eight highlights, a cutoff of 6 out of 10, a $2 daily cap: `config/models.yaml`
- 1,700+ deliveries: the operator's own count

The engine folder is never modified by this app or by its build.
