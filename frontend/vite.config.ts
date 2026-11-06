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
          // 将 Markdown 渲染依赖与应用入口分开加载，便于长期缓存。
          // 动画功能通过动态导入按需加载。
          if (id.includes('node_modules')) {
            // 交互效果依赖独立分包，避免界面更新影响其缓存。
            if (/[/\\]node_modules[/\\](thinking-orbs)[/\\]/.test(id)) {
              return 'interaction-vendor';
            }
            // React 框架依赖独立分包，便于长期缓存。
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
