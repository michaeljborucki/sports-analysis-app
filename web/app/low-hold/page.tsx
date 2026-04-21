import { redirect } from "next/navigation";

/** Legacy URL — redirect to the consolidated /edges page in Low-Hold mode. */
export default function LowHoldLegacyPage() {
  redirect("/edges?modes=low_hold");
}
