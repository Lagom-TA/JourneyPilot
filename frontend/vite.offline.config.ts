import { defineConfig } from 'vite';
import config from './vite.config';

export default defineConfig({
  ...config,
  server: { ...config.server, proxy: {} },
  plugins: [
    ...config.plugins ?? [],
    {
      name: 'offline-api-boundary',
      configureServer(server) {
        // 未被夹具接管的请求明确失败，且不触达开发者正在运行的后端。
        server.middlewares.use('/api', (_request, response) => {
          response.statusCode = 503;
          response.setHeader('content-type', 'application/json');
          response.end(JSON.stringify({ detail: 'Offline API requests must be mocked by test fixtures' }));
        });
      },
    },
  ],
});
