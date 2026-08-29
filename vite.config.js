import { defineConfig } from 'vite';
import { ViteImageOptimizer } from 'vite-plugin-image-optimizer';

export default defineConfig({
  plugins: [
    ViteImageOptimizer({
      png: { quality: 80 },
      jpeg: { quality: 80 },
      webp: { quality: 80 },
    }),
  ],
  // 👇 ここからを追加（サーバーからブラウザへ「UTF-8だよ」と強制通知する）
  server: {
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
    },
  },
  // 👇 ここも追加（CSSや文字の最適化で日本語が壊れるのを防ぐ）
  esbuild: {
    charset: 'utf8',
  },
});
