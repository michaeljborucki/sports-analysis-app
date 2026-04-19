"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const tabs = [
  { href: "/odds/mlb", label: "Odds" },
  { href: "/picks/mlb", label: "Picks" },
];

export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border-subtle bg-bg-1">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6">
          <div className="text-sm font-semibold tracking-wide">
            <span className="text-accent">◆</span>{" "}
            <span className="text-text-1">betting site</span>
          </div>
          <nav className="flex gap-5 text-sm">
            {tabs.map(t => (
              <Link
                key={t.href}
                href={t.href}
                className={clsx(
                  "py-1 transition-colors",
                  pathname === t.href
                    ? "text-text-1 border-b-2 border-accent"
                    : "text-text-2 hover:text-text-1"
                )}
              >
                {t.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto text-xs text-text-3 tabular">MLB · laptop build</div>
        </div>
      </header>
      <main className="flex-1 max-w-[1600px] mx-auto w-full px-6 py-4">
        {children}
      </main>
    </div>
  );
}
