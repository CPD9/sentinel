"use client";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ThresholdCurve } from "@/lib/types";

/** Precision and recall against one threshold, with the saved value and the dragged value marked. */
export function CurveChart({ curve, dragged }: { curve: ThresholdCurve; dragged?: number }) {
  return (
    <div className="h-48 w-full" role="img" aria-label={`Precision and recall against ${curve.param}, ${curve.convention}`}>
      <ResponsiveContainer>
        <LineChart data={curve.points} margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis dataKey="threshold" type="number" domain={[0, 1]} tick={{ fill: "var(--axis)", fontSize: 11 }} label={{ value: `${curve.param.replaceAll("_", " ")} (0–1)`, position: "insideBottom", offset: -10, fill: "var(--axis)", fontSize: 11 }} />
          <YAxis domain={[0, 1]} tick={{ fill: "var(--axis)", fontSize: 11 }} width={52} label={{ value: "precision / recall (0–1)", angle: -90, position: "insideLeft", offset: 6, style: { textAnchor: "middle" }, fill: "var(--axis)", fontSize: 10 }} />
          <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", fontSize: 12 }} formatter={(v) => (typeof v === "number" ? v.toFixed(2) : "n/a")} />
          <Legend verticalAlign="top" height={20} iconSize={10} wrapperStyle={{ fontSize: 11 }} />
          <Line dataKey="precision" name="precision" stroke="var(--c-insider_trading)" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          <Line dataKey="recall" name="recall" stroke="var(--c-credential_sharing)" strokeWidth={2} strokeDasharray="5 3" dot={false} connectNulls={false} isAnimationActive={false} />
          <ReferenceLine x={curve.current} stroke="var(--axis)" strokeDasharray="2 3" label={{ value: dragged == null ? "current" : dragged === curve.current ? "saved = now" : "saved", fill: "var(--axis)", fontSize: 10, position: dragged != null && dragged < curve.current ? "insideTopRight" : "insideTopLeft" }} />
          {dragged != null && dragged !== curve.current && <ReferenceLine x={dragged} stroke="var(--foreground)" strokeWidth={2} label={{ value: "now", fill: "var(--foreground)", fontSize: 10, position: dragged < curve.current ? "insideTopLeft" : "insideTopRight" }} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
