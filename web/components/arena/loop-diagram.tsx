// The governed learning loop. Status tags say what exists today and what is design only.
const Tag = ({ s }: { s: "built" | "design" | "here" }) => (
  <span
    className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
    style={s === "design" ? { background: "var(--review-bg)", color: "var(--review)" } : s === "here" ? { background: "var(--info-bg)", color: "var(--info)" } : { background: "var(--ok-bg)", color: "var(--ok)" }}
  >
    {s === "design" ? "design, not built" : s === "here" ? "this page" : "built"}
  </span>
);

function Box({ title, body, s, accent }: { title: string; body: string; s: "built" | "design" | "here"; accent?: boolean }) {
  return (
    <div className={`elevated rounded-xl p-3 ${accent ? "ring-1 ring-[var(--ok)]" : ""}`}>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2"><b className="text-sm">{title}</b><Tag s={s} /></div>
      <p className="text-xs leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}

const Arrow = ({ label }: { label?: string }) => (
  <div className="flex items-center justify-center gap-1 py-1 text-xs text-muted-foreground lg:flex-col lg:py-0" aria-hidden>
    <span className="lg:hidden">↓</span><span className="hidden lg:inline">→</span>{label && <span>{label}</span>}
  </div>
);

export function LoopDiagram() {
  return (
    <div className="space-y-4">
      <div className="grid items-center gap-2 lg:grid-cols-[1fr_auto_1.2fr_auto_1fr_auto_1fr_auto_1fr]">
        <Box s="built" title="Officer feedback" body="One click per call: correct, false alarm, missed (pipeline/feedback.py). Stays on this machine." />
        <Arrow />
        <div className="space-y-2">
          <Box s="built" title="Threshold suggestions" body="suggest.py: the smallest config change that fixes the most flagged errors, verified by re-deciding every call; the officer previews and applies." />
          <Box s="design" title="Few-shot bank" body="Only officer-confirmed case calls become examples for a candidate prompt. Never uploads, never unconfirmed calls." />
        </div>
        <Arrow />
        <Box s="built" title="Candidate" body="Another open-weight model on the same case calls (built: scripts/arena.py), or a new prompt + few-shot bank (design)." />
        <Arrow label="measured win?" />
        <Box s="here" title="Arena" body="Leaderboard on calls the candidate was not tuned on: AUC with CI, false alarms, misses, citation validity. A win must clear the CI, not just the point estimate." />
        <Arrow label="+ approval" />
        <Box s="design" accent title="Promotion gate → production" body="The candidate replaces the self-hosted production model only after the arena win AND an officer's sign-off, and only once it runs on our own servers." />
      </div>
      <div className="rounded-xl p-3 text-sm" style={{ background: "var(--ok-bg)", color: "var(--ok)" }}>
        <b>Uploads never leave this machine.</b> An uploaded call goes only through the self-hosted pipeline. It never enters the arena,
        the remote lane, or the few-shot bank. The remote lane exists only for the fictional case calls, behind the policy gate
        (explicit opt-in + open-weight allowlist); the arena refuses any call id that is not in the case manifest.
      </div>
    </div>
  );
}
