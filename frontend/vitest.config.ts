import { defineConfig } from 'vitest/config';

// 单测是 node 环境下的纯函数测试，不需要 DOM，因此不引入 jsdom。
// 不复用 vite.config.ts：react 插件、代理与 manualChunks 对测试都无必要，
// 也不应让 build 配置影响测试行为。
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    // Playwright 的 e2e 规格不在这里跑（它需要一个真实浏览器和一套跑着的服务）。
    exclude: ['e2e/**', 'node_modules/**'],
    reporters: process.env.CI ? ['default', 'junit'] : ['default'],
    outputFile: { junit: 'test-results/vitest-junit.xml' },
  },
});
