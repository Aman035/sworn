/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: the dashboard reads committed result files at build time and needs no
  // server. That keeps deployment free and, more importantly, means what you see is a
  // pinned snapshot rather than a live query nobody can reproduce.
  output: 'export',
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
