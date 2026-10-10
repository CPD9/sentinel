# SENTINEL web app

Next.js (App Router) + TypeScript + Tailwind. Screens and their JSON fields are specified in
[`docs/PRODUCT.md`](../docs/PRODUCT.md); endpoints in [`docs/API.md`](../docs/API.md). Nothing here calls an external
service: no auth, no cloud storage, no web fonts.

```bash
cd web
npm install
npm run dev      # fixtures mode, http://127.0.0.1:3000
npm run check    # eslint + tsc
npm run build && npm run start
```

## Data modes (`lib/data.ts` is the only module that fetches)

| `NEXT_PUBLIC_DATA_MODE` | Source |
|---|---|
| `fixtures` (default) | `../fixtures/*.json`, copied to `public/fixtures` by `scripts/copy-fixtures.mjs` before `dev` and `build`. **MOCK data**; a banner says so. Audio and snippets are 404, uploads and saving settings are refused, events are replayed from a file. |
| `api` | `/api/*` as in `docs/API.md`, proxied by `next.config.ts` to `API_BASE` (default `http://127.0.0.1:8001`). |

Copy `.env.example` to `.env.local` to switch.

## Layout

```
app/            routes: / (Inbox), calls/[id] (?tab=), calls/[id]/processing, settings, quality
components/     shell/ (nav, badges, states)  inbox/  processing/  call/ (+tabs/)  audio/ (lanes)  settings/  quality/
lib/            types.ts (mirror of pipeline/schemas.py)  data.ts  mock-replay.ts  format.ts  colors.ts
```

If `pipeline/schemas.py` changes, update `lib/types.ts` and `docs/PRODUCT.md` in the same change.
