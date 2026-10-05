import path from "node:path";

import type { NextConfig } from "next";

// URL Railway backend — dibaca dari env NEXT_BACKEND_URL saat build.
// Di Vercel: set NEXT_BACKEND_URL = https://aiasistent-production.up.railway.app
// Di local dev: fallback ke localhost:8000
const BACKEND_URL =
  process.env.NEXT_BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Pin root tracing ke folder frontend agar Next tidak salah menebak root
  // dari lockfile nyasar di direktori home (mis. ~/package-lock.json).
  outputFileTracingRoot: path.join(__dirname),

  // Proxy /api/* dan /health/* ke backend (Railway di prod, localhost di dev).
  // Dengan ini, NEXT_PUBLIC_API_BASE bisa tetap "" (relative URL),
  // sehingga request browser tidak kena CORS lintas-origin.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
      {
        source: "/health/:path*",
        destination: `${BACKEND_URL}/health/:path*`,
      },
    ];
  },
};

export default nextConfig;
