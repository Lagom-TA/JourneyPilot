import { defineConfig } from '@playwright/test';
import config from './playwright.config';

const baseURL = 'http://127.0.0.1:4173';

// 离线入口只启动当前源码的前端；漏拦截的 API 不能转发到本机正在运行的后端。
export default defineConfig({
  ...config,
  projects: config.projects?.filter(project => project.name === 'offline'),
  use: { ...config.use, baseURL },
  webServer: {
    command: 'npm run dev -- --config vite.offline.config.ts --host 127.0.0.1 --port 4173 --strictPort',
    url: baseURL,
    reuseExistingServer: false,
    env: {
      VITE_BASE: '/',
      VITE_API_BASE: '/api',
    },
  },
});
