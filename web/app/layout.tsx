import type { Metadata } from "next";
import { JetBrains_Mono, Schibsted_Grotesk } from "next/font/google";
import "./globals.css";
import { SwrProvider } from "@/lib/swr";
import { NavShell } from "@/components/nav-shell";
import { CommandPaletteMount } from "@/components/command-palette-mount";
import { ShortcutOverlayMount } from "@/components/shortcut-overlay-mount";

// Schibsted Grotesk for UI text, JetBrains Mono for numbers only (spec:
// docs/superpowers/specs/2026-10-02-gunmetal-redesign.md §2). Self-hosted
// by next/font; the CSS variables feed --font-sans / --font-mono.
const sans = Schibsted_Grotesk({
  subsets: ["latin"],
  variable: "--font-schibsted",
  display: "swap",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Betting Site",
  description: "Sports odds aggregator and edge finder",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // suppressHydrationWarning on <html> + <body> narrowly silences attribute
  // mismatches injected by browser extensions (Dark Reader, Grammarly) or
  // Next 16's dev overlay (which adds `isolation: isolate` to body). It does
  // NOT suppress warnings for children — real hydration bugs still surface.
  //
  // `data-density="comfortable"` is the default; useDensity() flips it at
  // runtime from the stored preference.
  return (
    <html
      lang="en"
      data-density="comfortable"
      className={`${sans.variable} ${mono.variable} h-full antialiased`}
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
