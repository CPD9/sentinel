# Reference notes (web app)

Read-only study of existing code before building `web/`. Clones live outside the repo (`~/Developer/_refs`).
Only the first reference is named in the product; the others were inspiration, and their licences are respected
(MIT: attribution kept in the files that adapt code).

**Rule for everything below:** nothing may call an external service. Auth, billing, cloud storage, cloud inference and
hosted job queues are dropped entirely.

## 1. Primary: Leadership-Demo (CPD9, our org)

Next.js 16 App Router, Tailwind 4, shadcn/ui (Radix), `next-themes`, `react-dropzone`, `sonner`.

| Adopt / adapt | From | Used in SENTINEL |
|---|---|---|
| App Router layout: shell layout + `projects` list + `projects/[id]` detail | `app/dashboard/layout.tsx`, `app/dashboard/projects/page.tsx`, `projects/[id]/page.tsx` | `app/(shell)/page.tsx` Inbox, `calls/[id]` dashboard |
| Tabs driven by one config array, with a per-tab error marker and a mobile `Select` fallback | `lib/tab-config.ts`, `components/project-detail/tab-triggers.tsx` | `lib/tabs.ts`; the Reasoning/Audio tabs show an error dot when their document failed |
| Step-by-step processing UI: phase cards with waiting / running / done state, progress, elapsed time | `components/processing-flow.tsx`, `processing-flow/phase-card.tsx` | `StageTimeline` (12 stages from `STAGES`, driven by real `ProcessingEvent`s, not a time estimate) |
| Status helpers (status → variant/icon/label) kept in one file | `lib/status-utils.ts` | `lib/format.ts` + `components/shell/badges.tsx` |
| Upload dropzone with type validation and drag state | `components/upload-dropzone.tsx` | Inbox upload (.wav only, `POST /api/calls`) |
| Project card/row with inline progress for processing items | `components/projects/project-card.tsx`, `compact-progress.tsx` | Inbox rows show the current stage |
| Empty / skeleton / loading states as small components | `components/projects/empty-state.tsx`, `tab-skeleton.tsx` | `StateCards` (Loading / Empty / Error, PRODUCT.md global rules) |
| Speaker dialogue list with coloured speaker chips | `components/project-tabs/transcript-tab.tsx` | Transcript tab (roles advisor / customer / unknown; evidence highlight added) |
| One data hook per page, UI never talks to the backend directly | pages use Convex `useQuery` | `lib/data.ts` is the only module that fetches (`DATA_MODE=fixtures\|api`) |

Drop: Clerk, Convex, Vercel Blob, Inngest, AssemblyAI, OpenAI, pricing/tier/credit code (`tier-*`, `upgrade`, `PRICING.md`),
the marketing home page, the emerald "glass card" gradient styling (we want calm, high-contrast, no decoration), the
"Powered by Inngest" banner, project rename/delete actions.

## 2. audio-cnn visualisation (Andreas Trolle, MIT)

Next.js 15, Tailwind 4, shadcn. Files under `audio-cnn-visualisation/src`.

| Adopt / adapt | From | Used in SENTINEL |
|---|---|---|
| Diverging colour scale: orange ↔ white ↔ blue via per-cell RGB | `lib/colors.ts` (`getColor`) | `lib/colors.ts` `divergingColor` for feature maps (stretch) |
| Legend: min label, gradient bar, max label | `components/ColorScale.tsx` | `ColorBar` for the mel spectrogram (dB, from `axes.value`) and for feature maps ([-1, 1]) |
| Heatmap as an SVG of unit rects with `preserveAspectRatio="none"` | `components/FeatureMap.tsx` | Adapted to a `<canvas>` for the mel spectrogram (60+ rows × 100s of columns); SVG is kept for small feature maps |
| Waveform as a polyline in a card | `components/Waveform.tsx` | Replaced by a min/max envelope from `waveform_peaks`, on the shared time axis |
| "Top predictions": label, percentage badge, progress bar | `app/page.tsx` | Per-criterion risk bars in Summary and Reasoning (with alarm/review threshold markers) |
| Visual language: stone neutrals, light borders, `Card`, thin type, small `text-xs` captions with shape/units | `app/page.tsx`, `styles/globals.css` | Design tokens; every chart gets a caption with its units |

Attribution comments (`Adapted from audio-cnn (MIT, © 2025 Andreas Trolle)`) sit in `components/audio/ColorBar.tsx`
and `lib/colors.ts`. Their model, training and Modal code are not used. Unlike their per-image min-max
normalisation, we normalise by the `db_min`/`db_max` shipped in the data, so colours are comparable across calls.

## 3. ai-video-sentiment-saas (Andreas Trolle, MIT) — conventions only

T3 stack: strict TypeScript, `~/` path alias, `src/` layout, `env.js` validation, `next lint` + `tsc --noEmit` as the
`check` script, Prettier with the Tailwind plugin, Geist font. We adopt: `typecheck` and `check` scripts, the
`@/` alias, one typed env module (`lib/env.ts`, only `DATA_MODE` and `API_BASE`), Geist. Drop: NextAuth, Prisma,
AWS S3/SageMaker, quota/credits, the video upload flow.

## 4. ai-video-sentiment-model, elevenlabs-clone — looked at, nothing taken

Training/deployment code (PyTorch, SageMaker, Make-An-Audio on Modal). No frontend to reuse. Dropped entirely.
