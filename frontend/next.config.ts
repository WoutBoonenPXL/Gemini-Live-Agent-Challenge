import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",  // needed for Docker / Cloud Run
  reactStrictMode: true,
};

export default nextConfig;
