import { Suspense } from "react";
import { SkeletonBlock } from "@/components/shell/states";
import { Tuning } from "@/components/settings/tuning";
import { SettingsDraftProvider } from "@/lib/settings-draft";

// Suspense: Tuning reads ?draft_alarm= (demo path) with useSearchParams.
export default function Page() {
  return <SettingsDraftProvider><Suspense fallback={<SkeletonBlock rows={6} />}><Tuning /></Suspense></SettingsDraftProvider>;
}
