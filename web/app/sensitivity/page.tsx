import { SettingsPage } from "@/components/settings/settings-view";
import { Tuning } from "@/components/settings/tuning";
import { SettingsDraftProvider } from "@/lib/settings-draft";

export default function Page() {
  return (
    <SettingsPage title="Sensitivity"
      description="How strict SENTINEL is: where a call becomes an alarm or goes to review. Drag a slider to see the effect on the number of hits before you save. No code needed.">
      <SettingsDraftProvider><Tuning /></SettingsDraftProvider>
    </SettingsPage>
  );
}
