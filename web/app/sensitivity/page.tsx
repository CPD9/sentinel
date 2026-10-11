import { SettingsTabs } from "@/components/settings/settings-tabs";
import { Tuning } from "@/components/settings/tuning";
import { SettingsDraftProvider } from "@/lib/settings-draft";

// Tuning renders its own title row, so Reset / Save can sit next to the title.
export default function Page() {
  return (
    <div className="space-y-5">
      <SettingsTabs />
      <SettingsDraftProvider><Tuning /></SettingsDraftProvider>
    </div>
  );
}
