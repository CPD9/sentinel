import { redirect } from "next/navigation";

// Keywords moved under Settings (Nik's design 07).
export default function Page() {
  redirect("/settings/keywords");
}
