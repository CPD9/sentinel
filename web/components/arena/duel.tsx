"use client";
// Blind duel: one case call, two anonymous models' verdicts and citations. The officer votes; names are revealed after
// the vote; Elo updates from the local vote log. No gold label is shown here.
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { computeElo, getArenaTranscript, loadVotes, saveVotes, type ArenaPool, type ArenaVerdict, type Vote, type VoteOutcome } from "@/lib/data-arena";
import { CRITERION_LABEL } from "@/lib/colors";
import type { Criterion } from "@/lib/types";

const DECISION_STYLE: Record<string, { label: string; bg: string; fg: string }> = {
  alarm: { label: "Alarm", bg: "var(--alarm-bg)", fg: "var(--alarm)" },
  review: { label: "Review", bg: "var(--review-bg)", fg: "var(--review)" },
  no_alert: { label: "No alert", bg: "var(--ok-bg)", fg: "var(--ok)" },
};
const mmss = (s: number | null) => (s == null ? "–" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`);

interface Match { callId: string; a: string; b: string }

/** Random case call + pair; 70% of the time prefer a pair that disagrees on the decision (more informative). */
function pickMatch(pool: ArenaPool, prev?: Match): Match | null {
  const calls = Object.keys(pool.calls).filter((c) => Object.keys(pool.calls[c]).length >= 2);
  if (!calls.length) return null;
  const wantDisagree = Math.random() < 0.7;
  for (let tries = 0; tries < 50; tries++) {
    const callId = calls[Math.floor(Math.random() * calls.length)];
    const models = Object.keys(pool.calls[callId]);
    const i = Math.floor(Math.random() * models.length);
    let j = Math.floor(Math.random() * (models.length - 1));
    if (j >= i) j += 1;
    const m: Match = { callId, a: models[i], b: models[j] };
    const disagree = pool.calls[callId][m.a].decision !== pool.calls[callId][m.b].decision;
    if (prev && prev.callId === m.callId && tries < 49) continue;
    if (!wantDisagree || disagree || tries > 40) return m;
  }
  return null;
}

function VerdictCard({ name, v, revealed, model }: { name: string; v: ArenaVerdict; revealed: boolean; model: string }) {
  const d = DECISION_STYLE[v.decision] ?? DECISION_STYLE.review;
  const crit = v.criterion && v.criterion !== "none" ? CRITERION_LABEL[v.criterion as Criterion] ?? v.criterion : null;
  return (
    <div className="elevated flex flex-col gap-3 rounded-2xl p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow">{name}</p>
        <span className={`text-xs ${revealed ? "font-medium text-foreground" : "text-muted-foreground"}`}>{revealed ? model : "hidden until you vote"}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md px-2 py-0.5 text-sm font-semibold" style={{ background: d.bg, color: d.fg }}>{d.label}</span>
        <span className="tabular text-sm text-muted-foreground">risk {v.risk.toFixed(2)}</span>
        {crit && <span className="text-sm text-muted-foreground">· {crit}</span>}
      </div>
      <p className="text-sm leading-relaxed">{v.reason || <span className="text-muted-foreground">no reason given</span>}</p>
      <div className="space-y-2">
        <p className="eyebrow">Citations ({v.citations.filter((c) => c.valid).length}/{v.citations.length} valid)</p>
        {v.citations.length === 0 && <p className="text-sm text-muted-foreground">none</p>}
        {v.citations.map((c, i) => (
          <div key={i} className="rounded-lg bg-muted/50 p-2.5 text-sm">
            <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
              <span style={{ color: c.valid ? "var(--ok)" : "var(--alarm)" }}>{c.valid ? "✓ verified in transcript" : `✗ ${c.drop_reason ?? "invalid"}`}</span>
              <span className="tabular">{c.segment_id} · {mmss(c.start_s)}–{mmss(c.end_s)}</span>
            </div>
            <p>“{c.quote}”</p>
            {c.text && c.text !== c.quote && <p className="mt-1 text-xs text-muted-foreground">line: {c.text}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function Duel({ pool }: { pool: ArenaPool }) {
  const [votes, setVotes] = useState<Vote[]>([]);
  const [match, setMatch] = useState<Match | null>(null);
  const [voted, setVoted] = useState<VoteOutcome | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const [transcript, setTranscript] = useState<{ id: string; lines: { id: string; text: string; start_s: number }[] } | null>(null);

  useEffect(() => {
    // Client-only: localStorage and Math.random must not run during server render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVotes(loadVotes());
    setMatch(pickMatch(pool));
  }, [pool]);

  useEffect(() => {
    if (!showTranscript || !match || transcript?.id === match.callId) return;
    let alive = true;
    getArenaTranscript(match.callId).then((t) => alive && setTranscript({ id: match.callId, lines: t.segments }), () => {});
    return () => { alive = false; };
  }, [showTranscript, match, transcript?.id]);

  const elo = useMemo(() => computeElo(pool.models, votes), [pool.models, votes]);
  const ranked = Object.entries(elo).sort((x, y) => y[1].elo - x[1].elo);

  if (!match) return <p className="text-sm text-muted-foreground">No call has verdicts from two models yet.</p>;
  const va = pool.calls[match.callId][match.a];
  const vb = pool.calls[match.callId][match.b];

  const vote = (o: VoteOutcome) => {
    const next = [...votes, { call_id: match.callId, a: match.a, b: match.b, outcome: o, at: new Date().toISOString() }];
    setVotes(next);
    saveVotes(next);
    setVoted(o);
  };
  const nextDuel = () => {
    setMatch(pickMatch(pool, match));
    setVoted(null);
    setShowTranscript(false);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">Call <b className="tabular text-foreground">{match.callId}</b> · which verdict would you rather act on?</p>
          <button className="text-sm text-muted-foreground underline-offset-2 hover:underline" onClick={() => setShowTranscript((s) => !s)}>
            {showTranscript ? "Hide transcript" : "Show transcript"}
          </button>
        </div>
        {showTranscript && (
          <div className="max-h-64 overflow-y-auto rounded-xl bg-muted/50 p-3 text-sm">
            {transcript?.id === match.callId
              ? transcript.lines.map((l) => <p key={l.id} className="py-0.5"><span className="tabular mr-2 text-xs text-muted-foreground">{l.id} {mmss(l.start_s)}</span>{l.text}</p>)
              : <p className="text-muted-foreground">Loading…</p>}
          </div>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <VerdictCard name="Model A" v={va} revealed={voted != null} model={match.a} />
          <VerdictCard name="Model B" v={vb} revealed={voted != null} model={match.b} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {voted == null ? (
            <>
              <Button onClick={() => vote("a")}>A is better</Button>
              <Button onClick={() => vote("b")}>B is better</Button>
              <Button variant="outline" onClick={() => vote("tie")}>Tie</Button>
              <Button variant="outline" onClick={() => vote("both_bad")}>Both bad</Button>
            </>
          ) : (
            <>
              <span className="text-sm text-muted-foreground">Vote saved in this browser. A was <b className="text-foreground">{match.a}</b>, B was <b className="text-foreground">{match.b}</b>.</span>
              <Button onClick={nextDuel}>Next duel</Button>
            </>
          )}
        </div>
      </div>
      <aside className="elevated h-fit space-y-3 rounded-2xl p-4">
        <div className="flex items-baseline justify-between">
          <p className="eyebrow">Officer Elo</p>
          <span className="tabular text-xs text-muted-foreground">{votes.length} vote{votes.length === 1 ? "" : "s"}</span>
        </div>
        <ol className="space-y-1.5 text-sm">
          {ranked.map(([m, r], i) => (
            <li key={m} className="flex items-baseline justify-between gap-2">
              <span className="truncate"><span className="tabular mr-1.5 text-muted-foreground">{i + 1}</span>{m}</span>
              <span className="tabular shrink-0">{Math.round(r.elo)} <span className="text-xs text-muted-foreground">({r.games})</span></span>
            </li>
          ))}
        </ol>
        <p className="text-xs text-muted-foreground">K = 32, start 1000; “both bad” moves nobody. Votes never leave this browser.</p>
        {votes.length > 0 && (
          <button className="text-xs text-muted-foreground underline-offset-2 hover:underline" onClick={() => { setVotes([]); saveVotes([]); }}>Reset votes</button>
        )}
      </aside>
    </div>
  );
}
