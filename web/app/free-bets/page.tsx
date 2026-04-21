import { redirect } from "next/navigation";

/** Legacy URL — redirect to the consolidated /edges page in Free-Bet mode. */
export default function FreeBetsLegacyPage() {
  redirect("/edges?modes=free_bet");
}
