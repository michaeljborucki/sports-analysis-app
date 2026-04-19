import { redirect } from "next/navigation";

export default function Page() {
  // Default landing: MLB odds. Will expand to a dashboard once multi-sport
  // coverage grows beyond a handful.
  redirect("/odds/mlb");
}
