import { redirect } from "next/navigation";

// Sensitivity moved under Settings (Nik's design 05).
export default function Page() {
  redirect("/settings/threshold");
}
