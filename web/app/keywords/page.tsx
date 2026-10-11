import { Configuration } from "@/components/settings/configuration";
import { SettingsTabs } from "@/components/settings/settings-tabs";
import { SettingsPage } from "@/components/settings/settings-view";

export default function Page() {
  return (
    <div className="space-y-5">
      <SettingsTabs />
      <SettingsPage
        description="Keywords point to passages, the checks decide. Hit counts update live as you edit.">
        <Configuration />
      </SettingsPage>
    </div>
  );
}
