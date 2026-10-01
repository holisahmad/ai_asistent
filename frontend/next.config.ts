import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin root tracing ke folder frontend agar Next tidak salah menebak root
  // dari lockfile nyasar di direktori home (mis. ~/package-lock.json).
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
