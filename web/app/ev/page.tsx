import { redirect } from "next/navigation";

/** Legacy URL — redirect to the consolidated /edges page in +EV mode. */
export default function EvLegacyPage() {
  redirect("/edges?modes=ev");
}
