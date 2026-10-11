"use client";

// Grounded chat over one call (scope "call") or the whole run (scope "all"). Only claims that passed the pipeline's
// evidence checker are shown; each cites transcript segments that play on click. The conversation lives in this
// component's state only and is gone on reload.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Loader2, MessageSquareQuote, Pause, Play, Send, ShieldCheck, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { askCopilot, clipUrl, type CopilotCitation, type CopilotClaim, type CopilotEvent, type HistoryTurn } from "@/lib/data-copilot";
import { fmtTime, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { speakerLabel } from "@/lib/explain";

type Turn = {
  q: string; claims: CopilotClaim[]; dropped: string[]; status: "queued" | "running" | "done" | "error";
  notInCall: boolean; retried: boolean; error: string | null; model: string | null; selfHosted: boolean | null; wallMs: number | null;
};

const DROP_LABEL: Record<string, string> = {
  uncited: "no citation", "empty quote": "no quote", "no segment ids cited": "no citation",
  "unknown segment id": "segment does not exist", "quote not in cited segments": "quote not found in the cited segment",
  "speaker mismatch": "wrong speaker", "unknown call": "call not in this run",
};

export function CopilotChat({ scope, callId, suggestions, onCite, placeholder }: {
  scope: "call" | "all"; callId?: string; suggestions: string[]; placeholder: string;
  /** call scope: highlight + play the cited segments on the call page's shared player */
  onCite?: (segmentIds: string[]) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const abort = useRef<AbortController | null>(null);
  const busy = turns.some((t) => t.status === "queued" || t.status === "running");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [turns]);

  const ask = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    setInput("");
    const history: HistoryTurn[] = turns.filter((t) => t.status === "done").slice(-2).map((t) => ({
      q: t.q, claims: t.claims.map((c) => ({ claim: c.text, call_id: c.citations[0]?.call_id, segment_id: c.citations[0]?.segment_id ?? "", quote: c.citations[0]?.quote ?? "" })),
    }));
    const idx = turns.length;
    setTurns((ts) => [...ts, { q: question, claims: [], dropped: [], status: "running", notInCall: false, retried: false, error: null, model: null, selfHosted: null, wallMs: null }]);
    const update = (fn: (t: Turn) => Turn) => setTurns((ts) => ts.map((t, i) => (i === idx ? fn(t) : t)));
    const ac = new AbortController();
    abort.current = ac;
    const onEvent = (e: CopilotEvent) => {
      if (e.type === "queued") update((t) => ({ ...t, status: "queued" }));
      else if (e.type === "start") update((t) => ({ ...t, status: "running", model: `${e.provider} · ${e.model}`, selfHosted: e.self_hosted }));
      else if (e.type === "claim") update((t) => ({ ...t, claims: [...t.claims, e] }));
      else if (e.type === "dropped") update((t) => ({ ...t, dropped: [...t.dropped, e.reason] }));
      else if (e.type === "retry") update((t) => ({ ...t, retried: true }))
      else if (e.type === "not_in_call") update((t) => ({ ...t, notInCall: true }));
      else if (e.type === "done") update((t) => ({ ...t, status: "done", wallMs: e.wall_ms }));
      else if (e.type === "error") update((t) => ({ ...t, status: "error", error: e.detail }));
    };
    try {
      await askCopilot(scope === "call" ? { scope, call_id: callId ?? "", question, history } : { scope, question, history }, onEvent, ac.signal);
      update((t) => (t.status === "running" || t.status === "queued" ? { ...t, status: "done" } : t));
    } catch (e) {
      update((t) => ({ ...t, status: "error", error: ac.signal.aborted ? "stopped" : e instanceof Error ? e.message : String(e) }));
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" aria-label="Suggested questions">
        {suggestions.map((s) => (
          <button key={s} type="button" disabled={busy} onClick={() => void ask(s)}
            className="rounded-full border border-border bg-card px-3 py-1 text-sm hover:bg-muted disabled:opacity-50">{s}</button>
        ))}
      </div>

      {turns.length > 0 && (
        <ol className="space-y-4" aria-live="polite">
          {turns.map((t, i) => <TurnView key={i} turn={t} scope={scope} onCite={onCite} />)}
        </ol>
      )}
      <div ref={endRef} />

      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void ask(input); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} maxLength={1000} placeholder={placeholder} aria-label="Question"
          className="h-9 min-w-0 flex-1 rounded-md border border-border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        {busy
          ? <Button type="button" variant="outline" onClick={() => abort.current?.abort()}><Square className="size-3.5" />Stop</Button>
          : <Button type="submit" disabled={!input.trim()}><Send className="size-3.5" />Ask</Button>}
      </form>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <ShieldCheck className="size-3.5" aria-hidden />
        Answered by the self-hosted model, only from this {scope === "call" ? "call" : "run"}. Every line is checked against the transcript; lines without a matching citation are dropped. Nothing is saved.
      </p>
    </div>
  );
}

function TurnView({ turn, scope, onCite }: { turn: Turn; scope: "call" | "all"; onCite?: (segs: string[]) => void }) {
  const counts = turn.dropped.reduce<Record<string, number>>((m, r) => ({ ...m, [r]: (m[r] ?? 0) + 1 }), {});
  return (
    <li className="space-y-2">
      <p className="ml-auto w-fit max-w-[85%] rounded-lg bg-muted px-3 py-1.5 text-sm font-medium">{turn.q}</p>
      <div className="space-y-2 rounded-lg border border-border bg-card p-3">
        {turn.claims.map((c, i) => (
          <div key={i} className="space-y-1.5">
            <p className="flex gap-2 text-sm leading-relaxed"><MessageSquareQuote className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />{c.text}</p>
            <ul className="space-y-1 pl-6">
              {c.citations.map((ct) => (
                <li key={`${ct.call_id}:${ct.segment_id}`} className="flex flex-wrap items-center gap-2">
                  <Citation c={ct} scope={scope} onCite={onCite} />
                  <span className="text-xs italic text-muted-foreground">“{ct.quote}”</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {(turn.status === "running" || turn.status === "queued") && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
            {turn.status === "queued" ? "Waiting for the model (one question at a time)…" : turn.claims.length ? "Checking the next line…" : "Reading the call…"}
          </p>
        )}
        {turn.status !== "running" && turn.status !== "queued" && turn.claims.length === 0 && !turn.error && (
          <p className="text-sm font-medium">Not in this {scope === "call" ? "call" : "set of calls"}.</p>
        )}
        {turn.error && <p className="text-sm text-alarm">Could not answer: {turn.error}</p>}
        {(turn.dropped.length > 0 || turn.model) && (
          <p className="text-xs text-muted-foreground">
            {turn.dropped.length > 0 && <>Dropped {turn.dropped.length} unverified line{turn.dropped.length > 1 ? "s" : ""} ({Object.entries(counts).map(([r, n]) => `${n}× ${DROP_LABEL[r] ?? humanize(r)}`).join(", ")}){turn.retried ? ", asked the model once more" : ""}. </>}
            {turn.model && <>{turn.model}{turn.selfHosted ? " · self-hosted" : ""}{turn.wallMs != null ? ` · ${(turn.wallMs / 1000).toFixed(1)} s` : ""}</>}
          </p>
        )}
      </div>
    </li>
  );
}

function Citation({ c, scope, onCite }: { c: CopilotCitation; scope: "call" | "all"; onCite?: (segs: string[]) => void }) {
  const label = `${scope === "all" ? `${c.call_id} · ` : ""}${c.start_s != null ? fmtTime(c.start_s) : c.segment_id} · ${speakerLabel(c.speaker)}`;
  const title = `${c.segment_id}: “${c.text}”`;
  if (scope === "call")
    return (
      <button type="button" onClick={() => onCite?.([c.segment_id])} title={title}
        className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-0.5 font-mono text-xs hover:bg-muted">
        <Play className="size-3" aria-hidden />{label}
      </button>
    );
  return <CrossCallCitation c={c} label={label} title={title} />;
}

function CrossCallCitation({ c, label, title }: { c: CopilotCitation; label: string; title: string }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const url = clipUrl(c.call_id, c.start_s, c.end_s);
  const toggle = () => {
    const a = ref.current;
    if (!a) return;
    if (playing) { a.pause(); return; }
    if (c.start_s != null) a.currentTime = Math.max(0, c.start_s - 1);
    void a.play();
  };
  return (
    <span className="inline-flex items-center overflow-hidden rounded-md border border-border bg-background font-mono text-xs" title={title}>
      {url && (
        <>
          <button type="button" onClick={toggle} aria-label={playing ? "Pause" : `Play ${label}`} className="px-1.5 py-0.5 hover:bg-muted">
            {playing ? <Pause className="size-3" /> : <Play className="size-3" />}
          </button>
          <audio ref={ref} src={url} preload="none" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
            onTimeUpdate={(e) => { if (c.end_s != null && e.currentTarget.currentTime > c.end_s + 1) e.currentTarget.pause(); }} />
        </>
      )}
      <Link href={`/calls/${c.call_id}?seg=${encodeURIComponent(c.segment_id)}`} className={cn("px-2 py-0.5 hover:bg-muted hover:underline", url && "border-l border-border")}>{label}</Link>
    </span>
  );
}
