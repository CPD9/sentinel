"use client";
// /demo starts the guided jury path (lib/demo.ts) at step 1 and lands on its first real screen.
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { DEMO_STEPS, setDemoStep } from "@/lib/demo";

export default function Page() {
  const router = useRouter();
  useEffect(() => { setDemoStep(0); router.replace(DEMO_STEPS[0].href); }, [router]);
  return <p className="text-sm text-muted-foreground">Starting the demo path…</p>;
}
