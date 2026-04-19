import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { SwrProvider } from "@/lib/swr";
import { NavShell } from "@/components/nav-shell";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

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
  return (
    <html
      lang="en"
      className={`${inter.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body
        className="min-h-full flex flex-col bg-bg-0 text-text-1"
        suppressHydrationWarning
      >
        <SwrProvider>
          <NavShell>{children}</NavShell>
        </SwrProvider>
      </body>
    </html>
  );
}
