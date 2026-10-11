"use client";
// Model arena: leaderboard (scripts/arena.py), blind duel with local Elo, and the governed learning loop.
import { ErrorCard, SkeletonBlock } from "@/components/shell/states";
import { getArenaLeaderboard, getArenaPool } from "@/lib/data-arena";
import { useAsync } from "@/lib/use-async";
import { Duel } from "./duel";
import { Leaderboard } from "./leaderboard";
import { LoopDiagram } from "./loop-diagram";

export function ArenaView() {
  const board = useAsync(getArenaLeaderboard, "arena-board");
  const pool = useAsync(getArenaPool, "arena-pool");
  return (
    <div className="stage-in mx-auto max-w-7xl space-y-10 py-4">
      <div className="space-y-2">
        <h1 className="text-headline font-semibold tracking-tight">Model arena</h1>
        <p className="max-w-3xl text-lead text-muted-foreground">
          The same judge prompt, the same 62 fictional case calls, several open-weight models. Production stays self-hosted;
          a challenger only replaces it after a measured win here and an officer&apos;s approval.
        </p>
      </div>

      <section aria-label="Leaderboard" className="space-y-3">
        <h2 className="text-lg font-semibold">Leaderboard</h2>
        {board.status === "error" ? <ErrorCard error={board.error} onRetry={board.reload} />
          : board.data ? <Leaderboard data={board.data} /> : <SkeletonBlock rows={6} />}
      </section>

      <section aria-label="Blind duel" className="space-y-3">
        <h2 className="text-lg font-semibold">Blind duel</h2>
        {pool.status === "error" ? <ErrorCard error={pool.error} onRetry={pool.reload} />
          : pool.data ? <Duel pool={pool.data} /> : <SkeletonBlock rows={6} />}
      </section>

      <section aria-label="Governed learning loop" className="space-y-3">
        <h2 className="text-lg font-semibold">Governed learning loop</h2>
        <LoopDiagram />
      </section>
    </div>
  );
}
