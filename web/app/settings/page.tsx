import { redirect } from "next/navigation";

// "Settings" was split into Sensitivity and Keywords & checks; old links land on Sensitivity.
export default function Page() {
  redirect("/sensitivity");
}
