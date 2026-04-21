import { redirect } from "next/navigation";

/** Legacy URL — redirect to the consolidated /edges page in Arb-only mode. */
export default function ArbitrageLegacyPage() {
  redirect("/edges?modes=arb");
}
