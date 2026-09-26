/** @type {import('next').NextConfig} */

// A GitHub Pages *project* site is served from https://<user>.github.io/<repo>/, so every
// absolute path the export emits — `/_next/...`, `/hooks` — has to be prefixed or it 404s.
// Driven by an env var rather than hard-coded so `npm run dev` still serves from `/`.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';

const nextConfig = {
  // Static export: the dashboard reads committed result files at build time and needs no
  // server. That keeps deployment free and, more importantly, means what you see is a
  // pinned snapshot rather than a live query nobody can reproduce.
  output: 'export',
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  basePath,
  assetPrefix: basePath || undefined,
  // Directory-style URLs, so `/hooks` resolves to `/hooks/index.html` on a plain static
  // host that does no extensionless-path rewriting.
  trailingSlash: true,
};

export default nextConfig;
