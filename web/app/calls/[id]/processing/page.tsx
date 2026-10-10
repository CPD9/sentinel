"use client";
import { use } from "react";
import { ProcessingView } from "@/components/processing/processing-view";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ProcessingView callId={id} />;
}
