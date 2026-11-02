import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // 子路径部署时通过环境变量覆盖 base / 输出目录：
  //   VITE_BASE=/journeypilot/ VITE_OUT_DIR=dist npm run build
  base: process.env.VITE_BASE || '/',
  server: {
    host: process.env.HOST || '0.0.0.0',
    port: Number(process.env.PORT) || 8080,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8001',
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: process.env.VITE_OUT_DIR || '../backend/static',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // react-markdown 生态是 chat 首屏 Markdown 的静态依赖，拆成懒加载会
          // 拖慢首帧；这里把它整棵第三方依赖树独立成 vendor chunk，与入口并行
          // 下载并获得稳定长缓存。motion 的 domMax 由 LazyMotion + CanvasMotion
          // 动态 import 自动拆成 motion-features chunk，不要在此把它拉回主包。
          if (id.includes('node_modules')) {
            // Keep the interaction libraries independently cacheable after UI changes.
            if (/[/\\]node_modules[/\\](thinking-orbs)[/\\]/.test(id)) {
              return 'interaction-vendor';
            }
            // react / react-dom / scheduler：全站最稳定的框架内核，独立成
            // react-vendor chunk——长缓存命中率最高，且把它从 app 入口移出后
            // 入口 minified raw 降到 500kb 阈值下，消除体积警告。
            if (/[/\\]node_modules[/\\](react|react-dom|scheduler|use-sync-external-store)[/\\]/.test(id)) {
              return 'react-vendor';
            }
            if (
              /[/\\]node_modules[/\\](react-markdown|remark-gfm|remark-|rehype-|mdast-|micromark|unified|vfile|property-information|hast-|unist-|decode-named-character-reference|character-entities|comma-separated-tokens|space-separated-tokens|html-url-attributes|trim-lines|ccount|escape-string-regexp|markdown-table|zwitch|longest-streak|devlop|bail|is-plain-obj|trough|extend|estree-util-is-identifier-name)/.test(
                id
              )
            ) {
              return 'markdown-vendor';
            }
          }
        },
      },
    },
  }
})
