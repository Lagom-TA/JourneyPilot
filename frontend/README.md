# JourneyPilot 前端

JourneyPilot 的旅行工作台前端：React 18 + TypeScript + Vite + Tailwind CSS + Leaflet + Motion。开发时直接对接本地 FastAPI + LangGraph 后端。

## 目录

- `src/features/`：按聊天、旅行、知识库、偏好设置和预设划分功能；每个功能自带组件、API 与类型。
- `src/components/ui/`：无业务依赖的共享界面组件。
- `src/app/`：应用壳、布局、导航、会话与全局状态。
- `src/lib/`：HTTP 客户端、运行时配置、格式化与通用工具。

## 请求与会话

- 所有 REST 请求经 `src/lib/http.ts`；`src/lib/runtimeConfig.ts` 用 `VITE_API_BASE` 解析 API 前缀（默认 `/api`）。
- 聊天流：`src/features/chat/api/streamChat.ts` 消费 `POST /api/chat-stream`（SSE）；`src/app/session/` 负责流归属、断线恢复与事件处理。
- 状态：`src/app/state/` 只有唯一 reducer 与 provider；会话切换、恢复、清空与正式 Bundle 确认都经过同一更新边界。
- 正式交付只接受完整 `DeliveryBundle`，过程事件可以流式；报告、行程、地图、来源与天气来自同一份交付记录。

## 本地运行

以下命令在 `frontend/` 目录执行（Node 版本见 `.nvmrc`，最低 20.19）：

```bash
npm ci
npm run dev   # http://localhost:8080
```

`vite.config.ts` 把 `/api` 代理到 `http://127.0.0.1:8001`；后端在其它地址时改代理目标：

```bash
VITE_PROXY_TARGET=http://127.0.0.1:9000 npm run dev
```

`VITE_API_BASE` 是**浏览器实际请求的 API 前缀**（默认 `/api`）；构建给独立域名/端口使用时才需要改成绝对地址，并同步配置后端 CORS。LLM provider key 只应放在后端环境中，不要写进前端 `.env`。

## 环境变量

| 变量 | 作用 | 默认值 |
|---|---|---|
| `VITE_API_BASE` | 浏览器请求的 API 前缀 | `/api` |
| `VITE_PROXY_TARGET` | 开发服务器 `/api` 代理目标 | `http://127.0.0.1:8001` |
| `VITE_BASE` | 子路径部署时的 Vite `base` | `/` |
| `VITE_OUT_DIR` | 构建输出目录 | `../backend/static` |
| `VITE_MAP_TILE_URL` | Leaflet 瓦片地址（支持 `{s}/{z}/{x}/{y}`） | 现网高德瓦片 |
| `VITE_MAP_TILE_ATTRIBUTION` | 底图署名 HTML | 高德地图署名 |

示例见 `.env.example`。

## 检查与构建

```bash
npm run type-check   # tsc --noEmit（app 与 node 两套配置）
npm run lint         # ESLint
npm run test         # Vitest 单元测试
npm run build        # 产物写入 ../backend/static（VITE_OUT_DIR 可覆盖）
npm run check        # type-check + lint + test + build（CI 同款）
```

子路径部署：

```bash
VITE_BASE=/journeypilot/ VITE_OUT_DIR=dist npm run build
```

端到端（Playwright）用例、开关与证据位置见 [e2e/README.md](e2e/README.md)。
