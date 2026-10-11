import { Configuration } from "@/components/settings/configuration";
import { SettingsPage } from "@/components/settings/settings-view";

export default function Page() {
  return (
    <SettingsPage title="Keywords"
      description="What Sentinel looks for: keyword families with their Swiss German variants, and one check per kind of fraud. Hit counts update live. No code needed.">
      <Configuration />
    </SettingsPage>
  );
}
