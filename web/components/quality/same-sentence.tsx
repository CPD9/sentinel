"use client";
// "Same sentence, two verdicts": two calls in which a customer reads six digits aloud. The passage is found in each
// call's own transcript at runtime (six digits, spoken or written as numbers); the verdicts come from the result, the
// AI judge's file and the strategy comparison. The conclusion line is computed from those verdicts, never written ahead.
import { Pause, Play } from "lucide-react";
import { useRef, useState } from "react";
import { audioUrl, getCall, getJudge, getMethods, getTranscript } from "@/lib/data";
import { SAME_SENTENCE_PAIR } from "@/lib/demo";
import { DECISION_LABEL } from "@/lib/explain";
import { fmtTime } from "@/lib/format";
import type { Decision, TranscriptSegment } from "@/lib/types";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

const W = "(?:null|eins|ein|eis|zwei|zwo|drei|drü|vier|fünf|füf|sechs|sächs|sieben|sibe|acht|neun|nün|nüün|\\d)";
const DIGITS = new RegExp(`\\d{6}|${W}(?:[\\s,.\\-–]+${W}){5,}`, "i");

async function load(id: string) {
  const [call, tr, judge, methods] = await Promise.all([getCall(id).catch(() => null), getTranscript(id).catch(() => null), getJudge(id).catch(() => null), getMethods(id).catch(() => null)]);
  const segs = tr?.segments ?? [];
  const i = segs.findIndex((s) => DIGITS.test(s.text));
  return { id, decision: call?.kind === "result" ? call.data.decision : null, segs: i < 0 ? [] : segs.slice(Math.max(0, i - 2), i + 2), hit: i < 0 ? null : segs[i].id,
    judge, factsRules: methods?.methods.find((m) => m.id === "S3")?.decision ?? null };
}

export function SameSentence() {
  const [a, b] = SAME_SENTENCE_PAIR;
  const data = useAsync(() => Promise.all([load(a), load(b)]), `same:${a}:${b}`);
  if (!data.data || data.data.some((d) => !d.hit)) return null;        // nothing to show for this run: no dead panel
  const [x, y] = data.data;
  const same = (k: (d: typeof x) => Decision | null | undefined) => k(x) != null && k(x) === k(y);
  const conclusion = same((d) => d.judge?.decision)
    ? `The AI judge does not tell them apart yet: ${DECISION_LABEL[x.judge!.decision]} for both.${!same((d) => d.factsRules) && x.factsRules && y.factsRules ? ` Facts → rules did (${DECISION_LABEL[x.factsRules]} vs ${DECISION_LABEL[y.factsRules]}, on reference transcripts), but overall it ranks calls no better than chance.` : ""}`
    : `Same words, two verdicts: the AI judge says ${DECISION_LABEL[x.judge?.decision ?? "no_alert"]} for one and ${DECISION_LABEL[y.judge?.decision ?? "no_alert"]} for the other.`;
  return (
    <section aria-labelledby="same-h" className="elevated space-y-4 rounded-[var(--radius-panel)] p-6">
      <div>
        <p id="same-h" className="eyebrow">Same sentence, two situations</p>
        <p className="text-lead font-semibold">A customer reads six digits aloud. Is it a live login code or an old sample?</p>
      </div>
      <div className="grid gap-5 lg:grid-cols-2">{[x, y].map((d) => <Side key={d.id} d={d} />)}</div>
      <p className="text-body font-medium text-review">{conclusion}</p>
    </section>
  );
}

function Side({ d }: { d: Awaited<ReturnType<typeof load>> }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const hit = d.segs.find((s) => s.id === d.hit) as TranscriptSegment;
  const url = audioUrl(d.id);
  const toggle = () => {
    const el = audio.current;
    if (!el) return;
    if (playing) { el.pause(); return; }
    el.currentTime = Math.max(0, (d.segs[0].start_s ?? hit.start_s ?? 0));
    void el.play().catch(() => {});
  };
  const tone = (x: Decision | null | undefined) => (x === "alarm" ? "text-alarm" : x === "review" ? "text-review" : "text-noalert");
  return (
    <div className="space-y-3 rounded-xl border border-border p-4">
      <div className="flex items-center justify-between gap-3">
        <a href={`/calls/${d.id}`} className="font-mono font-semibold underline-offset-4 hover:underline">{d.id}</a>
        {url && hit.start_s != null && (
          <button type="button" onClick={toggle} aria-pressed={playing} className="inline-flex items-center gap-1.5 rounded-full border border-foreground/60 px-3 py-1 text-sm hover:bg-muted">
            {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}{playing ? "pause" : `play from ${fmtTime(d.segs[0].start_s)}`}
          </button>
        )}
        {url && <audio ref={audio} src={url} preload="none" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
          onTimeUpdate={(e) => { const end = d.segs.at(-1)?.end_s; if (end != null && e.currentTarget.currentTime > end + 0.5) e.currentTarget.pause(); }} />}
      </div>
      <ol className="space-y-1 text-sm">
        {d.segs.map((s) => (
          <li key={s.id} className={cn("grid grid-cols-[3rem_1fr] gap-2", s.id === d.hit ? "font-semibold" : "text-muted-foreground")}>
            <span className="tabular">{fmtTime(s.start_s)}</span><span lang="gsw">“{s.text}”</span>
          </li>
        ))}
      </ol>
      <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">AI judge (shipped)</dt><dd className={cn("font-semibold", tone(d.judge?.decision))}>{d.judge ? DECISION_LABEL[d.judge.decision] : "no verdict in this run"}</dd>
        <dt className="text-muted-foreground">Facts → rules</dt><dd className={cn("font-semibold", tone(d.factsRules))}>{d.factsRules ? `${DECISION_LABEL[d.factsRules]} (reference transcripts)` : "–"}</dd>
      </dl>
      {d.judge && <p lang="de" className="text-sm text-muted-foreground">Judge&rsquo;s reasoning: “{d.judge.reason}”</p>}
    </div>
  );
}
