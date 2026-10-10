import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // In api mode the browser talks to Jules' FastAPI on 127.0.0.1 (SSH tunnel). Same-origin proxy avoids CORS.
  async rewrites() {
    const api = process.env.API_BASE ?? "http://127.0.0.1:8001";
    return process.env.NEXT_PUBLIC_DATA_MODE === "api" ? [{ source: "/api/:path*", destination: `${api}/api/:path*` }] : [];
  },
};

export default nextConfig;
