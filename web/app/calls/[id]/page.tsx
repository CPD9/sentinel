"use client";
import { use } from "react";
import { CallDashboard } from "@/components/call/call-dashboard";
import { isTab } from "@/lib/tabs";

export default function Page({
  params, searchParams,
}: { params: Promise<{ id: string }>; searchParams: Promise<{ tab?: string; win?: string; seg?: string }> }) {
  const { id } = use(params);
  const q = use(searchParams);
  return <CallDashboard id={id} tab={isTab(q.tab) ? q.tab : "summary"} sel={{ win: q.win, seg: q.seg }} />;
}
