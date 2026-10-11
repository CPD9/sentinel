import { AlertTriangle, Check, Eye, Loader2, OctagonAlert, XCircle, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { CRITERION_LABEL, SPEAKER_COLOR, criterionColor } from "@/lib/colors";
import { humanize } from "@/lib/format";
import type { CallStatus, Criterion, Decision, Speaker } from "@/lib/types";
import { cn } from "@/lib/utils";

/** alarm = red on a soft red tint; review = amber, dashed outline, eye icon (never alarm-styled); no_alert = grey. Sentence case. */
export function DecisionBadge({ decision, size = "md" }: { decision: Decision | null; size?: "sm" | "md" | "lg" }) {
  if (!decision) return <span className="text-xs text-muted-foreground">–</span>;
  const sz = size === "lg" ? "px-3 py-1 text-sm" : size === "sm" ? "px-1.5 py-0 text-[11px]" : "";
  if (decision === "alarm")
    return <Badge className={cn("border-alarm/35 bg-alarm-bg font-semibold text-alarm", sz)}><OctagonAlert className="size-3.5" aria-hidden />Alert</Badge>;
  if (decision === "review")
    return <Badge className={cn("border-dashed border-review bg-review-bg font-semibold text-review", sz)}><Eye className="size-3.5" aria-hidden />Review</Badge>;
  return <Badge className={cn("border-noalert/30 bg-noalert-bg font-medium text-noalert", sz)}><Check className="size-3.5" aria-hidden />No alert</Badge>;
}

export function StatusPill({ status, stage }: { status: CallStatus; stage?: string | null }) {
  if (status === "processing")
    return <Badge className="border-info/40 bg-info-bg text-info"><Loader2 className="size-3 animate-spin motion-reduce:animate-none" />processing{stage ? ` · ${stage}` : ""}</Badge>;
  if (status === "queued") return <Badge className="text-muted-foreground"><Clock className="size-3" />queued</Badge>;
  if (status === "error") return <Badge className="border-alarm/50 text-alarm"><XCircle className="size-3" />error</Badge>;
  return <Badge className="text-muted-foreground">done</Badge>;
}

/** Red chip whenever a stage failed. Never hidden. */
export function StageErrorChip({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <Badge className="border-alarm/60 bg-alarm-bg text-alarm" title="One or more pipeline stages failed">
      <AlertTriangle className="size-3" />stage error{count > 1 ? ` ×${count}` : ""}
    </Badge>
  );
}

export function CriterionChip({ criterion, className }: { criterion: Criterion | string; className?: string }) {
  return (
    <Badge className={className}>
      <span aria-hidden className="inline-block size-2 rounded-full" style={{ background: criterionColor(criterion) }} />
      {CRITERION_LABEL[criterion as Criterion] ?? humanize(criterion)}
    </Badge>
  );
}

export function SpeakerChip({ speaker }: { speaker: Speaker }) {
  return (
    <Badge style={{ color: SPEAKER_COLOR[speaker], borderColor: SPEAKER_COLOR[speaker] }}>{speaker}</Badge>
  );
}

export function CounterChip() {
  return <Badge className="bg-muted text-muted-foreground">counter</Badge>;
}
