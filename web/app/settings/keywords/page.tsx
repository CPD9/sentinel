import { Configuration } from "@/components/settings/configuration";
import { SettingsPage } from "@/components/settings/settings-view";

export default function Page() {
  return (
    <SettingsPage title="Keywords"
      description="Keyword families with their Swiss German variants (dashed). The number on each word is how many passages it matches; it updates live.">
      <Configuration />
    </SettingsPage>
  );
}
