"use client";
// Language routing per speaker on a map of Switzerland (display only; scripts/dialect_map.py, docs/DIALECT.md).
// The point is to route a call to the right language model and reviewer, not to say where someone lives: regions
// are shaded by probability, there is never a pin, and nothing here feeds the decision.
import { Badge } from "@/components/ui/badge";
import { getDialect } from "@/lib/data";
import { CANTON_PATHS, LAKE_PATHS, SWISS_MAP_CREDIT, SWISS_VIEWBOX } from "@/lib/swiss-map-paths";
import type { DialectEstimate, SpeakerLanguage } from "@/lib/types";
import { useAsync } from "@/lib/use-async";

// Mirrors config/dialect_regions.json (tests/test_dialect.py checks they agree).
const SHORT: Record<string, string> = { de_ch: "German-speaking", fr_ch: "French-speaking", it_ch: "Italian-speaking" };
export const LANGUAGE_REGIONS: Record<string, { label: string; cantons: string[] }> = {
  de_ch: { label: "German-speaking Switzerland", cantons: ["ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "SO", "BS", "BL", "SH", "AR", "AI", "SG", "GR", "AG", "TG"] },
  fr_ch: { label: "French-speaking Switzerland (Romandie)", cantons: ["FR", "VD", "VS", "NE", "GE", "JU"] },
  it_ch: { label: "Italian-speaking Switzerland", cantons: ["TI"] },
};
export const BILINGUAL_CANTONS = ["BE", "FR", "VS", "GR"];
const DIALECT_LABELS: Record<string, string> = {
  ag: "Aargau", be: "Bern", bs: "Basel", gr: "Graubünden", lu: "Lucerne", sg: "St. Gallen", vs: "Valais (Upper Valais)", zh: "Zurich",
};
const REGION_OF: Record<string, string> = Object.fromEntries(
  Object.entries(LANGUAGE_REGIONS).flatMap(([r, v]) => v.cantons.map((c) => [c, r])),
);
const ROLE_COLOR = { advisor: "var(--advisor)", customer: "var(--customer)" } as const;
const ROLE_LABEL = { advisor: "Advisor", customer: "Customer" } as const;
const LANG_LABEL: Record<string, string> = { de: "German", fr: "French", it: "Italian", en: "English", other: "other" };
const pct = (p: number) => `${Math.round(p * 100)}%`;

export function LanguageRouting({ callId }: { callId: string }) {
  const st = useAsync(() => getDialect(callId), `dia:${callId}`);
  if (st.status === "loading" && !st.data) return null;
  if (st.status === "error") return null;                                  // optional view: never break the tab
  const d = st.data;
  return (
    <section aria-labelledby="lang-routing" className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="lang-routing" className="text-sm font-semibold">Language routing</h3>
        <Badge className="border-info text-info">Experimental · probability, not identity · not used in the decision</Badge>
        {d?.is_sample && <Badge className="border-review text-review">SAMPLE DATA · not a real estimate</Badge>}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Which language model and which reviewer this call needs. Shaded by probability per language region, never a location.
        Dialect inference is personal data under the Swiss nDSG; this view stays in the run folder.
      </p>
      {!d ? (
        <p className="mt-3 text-sm text-muted-foreground">No language estimate for this call (optional step: <code>scripts/dialect_map.py</code>).</p>
      ) : (
        <Estimate d={d} />
      )}
    </section>
  );
}

function Estimate({ d }: { d: DialectEstimate }) {
  const research = d.speakers.filter((s) => s.research_dialect);
  return (
    <>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        {(["advisor", "customer"] as const).map((role) => {
          const s = d.speakers.find((x) => x.role === role);
          return s ? <SpeakerMap key={role} s={s} unsupported={d.unsupported_languages ?? ["rm"]} /> : (
            <div key={role} className="rounded-md border border-dashed border-border p-3 text-xs text-muted-foreground">
              {ROLE_LABEL[role]}: not enough speech for a language estimate.
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-[11px] leading-snug text-muted-foreground">
        Method: {d.method}. Model: <code>{d.model}</code>.
        {d.validated_on.length > 0 && <> Validated on: {d.validated_on.join("; ")}.</>}
        {" "}Language regions at canton level by majority language; bilingual cantons (BE, FR, VS, GR) are hatched. {SWISS_MAP_CREDIT}.
      </p>
      {research.length > 0 && <ResearchPanel speakers={research} />}
    </>
  );
}

function SpeakerMap({ s, unsupported }: { s: SpeakerLanguage; unsupported: string[] }) {
  const color = ROLE_COLOR[s.role];
  const top = Object.entries(s.region_probs).filter(([r]) => r in LANGUAGE_REGIONS).sort((a, b) => b[1] - a[1]);
  const langs = Object.entries(s.language_probs).sort((a, b) => b[1] - a[1]);
  const pid = `hatch-${s.role}`;
  const label = `${ROLE_LABEL[s.role]}: ${top.slice(0, 3).map(([r, p]) => `${LANGUAGE_REGIONS[r].label} ${pct(p)}`).join(", ")}`;
  return (
    <figure className="m-0 max-w-[340px]">
      <figcaption className="mb-1 flex items-center justify-between gap-2 text-xs">
        <span className="font-semibold" style={{ color }}>{ROLE_LABEL[s.role]}</span>
        <span className="text-muted-foreground">{Math.round(s.speech_s)} s speech · confidence <b className="text-foreground">{s.confidence}</b></span>
      </figcaption>
      <svg viewBox={SWISS_VIEWBOX} role="img" aria-label={label} className="block h-auto w-full max-w-[340px]">
        <defs>
          <pattern id={pid} width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="4" stroke="var(--muted-foreground)" strokeWidth="0.6" strokeOpacity="0.45" />
          </pattern>
        </defs>
        {Object.entries(CANTON_PATHS).map(([c, path]) => {
          const p = s.region_probs[REGION_OF[c]] ?? 0;
          return (
            <g key={c}>
              <path d={path} fill="var(--muted)" stroke="none" />
              {p > 0.005 && <path d={path} fill={color} fillOpacity={0.12 + 0.78 * p} stroke="none" />}
              {BILINGUAL_CANTONS.includes(c) && <path d={path} fill={`url(#${pid})`} stroke="none" />}
              <path d={path} fill="none" stroke="var(--card)" strokeWidth="0.7" strokeLinejoin="round"><title>{`${c}: ${LANGUAGE_REGIONS[REGION_OF[c]]?.label ?? ""} ${pct(p)}`}</title></path>
            </g>
          );
        })}
        {LAKE_PATHS.map((d, i) => <path key={i} d={d} fill="var(--lane-bg)" stroke="none" aria-hidden />)}
      </svg>
      <ol className="mt-2 space-y-1 text-xs">
        {top.slice(0, 3).map(([r, p]) => (
          <li key={r} className="flex items-center gap-2">
            <span className="w-32 shrink-0 truncate" title={LANGUAGE_REGIONS[r].label}>{SHORT[r] ?? LANGUAGE_REGIONS[r].label}</span>
            <span className="h-1.5 flex-1 rounded-full bg-muted" aria-hidden>
              <span className="block h-full rounded-full" style={{ width: pct(p), background: color }} />
            </span>
            <span className="tabular w-10 text-right">{pct(p)}</span>
          </li>
        ))}
      </ol>
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        Language: {langs.map(([l, p]) => `${LANG_LABEL[l] ?? l} ${pct(p)}`).join(" · ")}
        {unsupported.includes("rm") && " · Romansh: not supported by Whisper"}
      </p>
      <p className="text-[11px] text-muted-foreground">Dialect: not determined.</p>
    </figure>
  );
}

function ResearchPanel({ speakers }: { speakers: SpeakerLanguage[] }) {
  const r0 = speakers[0].research_dialect!;
  return (
    <details className="group mt-3 rounded-md border border-border">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs font-semibold [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="transition-transform group-open:rotate-90 motion-reduce:transition-none">›</span>
        Research: dialect estimate
        <span className="font-normal text-muted-foreground">low confidence, not shown on the map</span>
      </summary>
      <div className="space-y-2 border-t border-border p-3 text-xs">
        <p role="note" className="rounded-md border border-review bg-review-bg p-2 text-review">
          {r0.warning}
        </p>
        <p className="text-muted-foreground">
          SwissDial classifier, cross-validated on held-out sentences: accuracy {pct(r0.cv_accuracy)} (95% CI {pct(r0.cv_ci95[0])}–{pct(r0.cv_ci95[1])}), chance {pct(r0.chance)}.
        </p>
        <div className="grid gap-2 md:grid-cols-2">
          {speakers.map((s) => (
            <div key={s.role}>
              <div className="font-semibold" style={{ color: ROLE_COLOR[s.role] }}>{ROLE_LABEL[s.role]}</div>
              <ol className="mt-0.5 space-y-0.5">
                {s.research_dialect!.top3.map((t) => (
                  <li key={t.region} className="flex justify-between gap-2"><span>{DIALECT_LABELS[t.region] ?? t.region}</span><span className="tabular">{pct(t.p)}</span></li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}
