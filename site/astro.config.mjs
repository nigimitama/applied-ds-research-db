import { defineConfig } from "astro/config";

// GitHub Pages(プロジェクトサイト)では SITE_BASE=/applied-ds-research-db を設定する
const base = process.env.SITE_BASE || "/";
export default defineConfig({
  site: process.env.SITE_URL || "https://nigimitama.github.io",
  base,
  trailingSlash: "always",
  build: { format: "directory" },
});
