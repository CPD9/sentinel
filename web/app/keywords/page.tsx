import { Configuration } from "@/components/settings/configuration";
import { SettingsTabs } from "@/components/settings/settings-tabs";
import { SettingsPage } from "@/components/settings/settings-view";

export default function Page() {
  return (
    <div className="space-y-5">
      <SettingsTabs />
      <SettingsPage
        description="What the system looks for: keyword families with their Swiss German variants, and one check per kind of fraud. Hit counts update live. No code needed.">
        <Configuration />
      </SettingsPage>
    </div>
  );
}
