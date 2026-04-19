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
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-bg-0 text-text-1">
        <SwrProvider>
          <NavShell>{children}</NavShell>
        </SwrProvider>
      </body>
    </html>
  );
}
