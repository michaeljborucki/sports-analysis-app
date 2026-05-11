import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { SwrProvider } from "@/lib/swr";
import { NavShell } from "@/components/nav-shell";
import { CommandPaletteMount } from "@/components/command-palette-mount";
import { ShortcutOverlayMount } from "@/components/shortcut-overlay-mount";

// Geist Sans + Mono from Vercel. Each font's `variable` property injects a
// CSS custom property (`--font-geist-sans`, `--font-geist-mono`) that we
// consume in `globals.css` for the body font stack and the `.tabular`
// monospace utility. Geist Mono ships with tabular-style numerics, ss01,
// and the trading-desk friendly alternates we want for odds cells.

export const metadata: Metadata = {
  title: "Betting Site",
  description: "MLB odds aggregator + agent picks",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // suppressHydrationWarning on <html> + <body> narrowly silences attribute
  // mismatches injected by browser extensions (Dark Reader, Grammarly) or
  // Next 16's dev overlay (which adds `isolation: isolate` to body). It does
  // NOT suppress warnings for children — real hydration bugs still surface.
  //
  // `data-density="comfortable"` is the default density; Wave 2 will add a
  // user-facing toggle that flips this attribute at runtime. Density vars
  // (--row-h, --row-pad-y, --row-pad-x) cascade from globals.css.
  return (
    <html
      lang="en"
      data-density="comfortable"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body
        className="min-h-full flex flex-col bg-bg-0 text-text-1"
        suppressHydrationWarning
      >
        <SwrProvider>
          <NavShell>{children}</NavShell>
          <CommandPaletteMount />
          <ShortcutOverlayMount />
        </SwrProvider>
      </body>
    </html>
  );
}
