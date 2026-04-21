import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next.js 16 blocks cross-origin dev resources (HMR, /_next/*) by default;
  // `127.0.0.1` is treated as a different origin from `localhost`. Explicitly
  // whitelist both so HMR, static chunks, and dev-tool injection aren't
  // silently blocked — that blockage manifested as "stuck on Loading…" on
  // every page because the client JS didn't finish hydrating.
  allowedDevOrigins: ["127.0.0.1", "localhost", "192.168.1.153"],
};

export default nextConfig;
