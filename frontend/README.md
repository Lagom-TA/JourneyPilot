# JourneyPilot 前端

JourneyPilot 的 Web 旅行工作台前端，基于 React 18、TypeScript、Vite、Tailwind CSS、Leaflet 与 Motion 构建，配合 FastAPI + LangGraph 后端提供交互式行程规划与地图探索体验。

## 目录结构

- `src/features/`：按业务领域（`chat`、`travel`、`knowledge`、`preferences`、`presets`）组织组件、接口调用与模型定义。
- `src/components/ui/`：通用的无业务耦合基础界面组件。
- `src/app/`：应用外壳、整体布局、路由导航、会话管理与全局状态。
- `src/lib/`：HTTP 客户端、运行时配置、地图底图配置、动效参数与通用工具函数。
- `src/styles/`：按页面与工作台模块拆分的样式表。

## 核心数据流与状态

- **REST 与配置解析**：所有 HTTP 请求统一经过 `src/lib/http.ts`，由 `src/lib/runtimeConfig.ts` 根据 `VITE_API_BASE` 解析接口前缀（默认为 `/api`）。
- **流式规划会话（SSE）**：`src/features/chat/api/streamChat.ts` 消费 `POST /api/chat-stream` 事件流，`src/app/session/` 负责维护各会话的流生命周期、断线恢复与多会话并行快照。
- **全局状态与交付物**：`src/app/state/` 提供集中式的状态 reducer 与 Context Provider。规划完成后，前端接收完整的 `DeliveryBundle`，统一驱动日程表、交互地图、阅读版、资料来源与天气面板。

## 样式与视口

- **样式组织**：`src/index.css` 定义全局 CSS 变量（颜色、圆角、阴影、动效与层级 token）及基础样式；`src/styles/` 存放首页、档案页与工作台布局样式；动效时长与缓动统一定义在 `src/lib/motion.ts`，交通方式配色集中在 `src/features/travel/model/transportPresentation.ts`。
- **响应式断点**：`breakpoints.json` 定义 Tailwind 与 JS 共享的断点（`sm` 640px、`md` 768px、`lg` 1024px、`xl` 1280px、`2xl` 1536px）。
- **字体加载**：通过 Fontsource 本地加载 Inter（西文）、Noto Sans SC（中文正文与粗体标题）及 Noto Serif SC（衬线装饰标题）。

全局浮层与面板遵循统一的 `z-index` 层级规划：

| Token | 数值 | 用途 |
|---|---:|---|
| `--z-map-empty` | 900 | 地图空状态提示 |
| `--z-map-controls` / `--z-map-detail` | 1000 / 1001 | 地图缩放控件与地点详情卡片 |
| `--z-recovery` | 1050 | 移动端状态恢复提示 |
| `--z-workspace-panel` / `--z-sheet` | 1100 | 工作台浮动面板与移动端底部抽屉 |
| `--z-navigation-scrim` / `--z-navigation-drawer` | 1110 / 1120 | 移动端导航遮罩与抽屉菜单 |
| `--z-recovery-desktop` | 1150 | 桌面端状态恢复提示 |
| `--z-reading` / `--z-dialog` | 1200 | 阅读版抽屉、模态对话框、弹出层与日历 |
| `--z-destination-menu` | 1400 | 目的地搜索候选下拉列表 |

## 本地开发

在 `frontend/` 目录下执行（推荐 Node 22，见 `.nvmrc`）：

```bash
npm ci
npm run dev   # 访问 http://localhost:8080
```

开发服务器默认将 `/api` 代理至 `http://127.0.0.1:8001`。若后端运行在其他地址，可通过环境变量指定代理目标：

```bash
VITE_PROXY_TARGET=http://127.0.0.1:9000 npm run dev
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `VITE_API_BASE` | 浏览器发起请求的 API 路径前缀 | `/api` |
| `VITE_PROXY_TARGET` | Vite 开发服务器的 `/api` 代理目标地址 | `http://127.0.0.1:8001` |
| `VITE_BASE` | 子路径部署时的前端基础路径 | `/` |
| `VITE_OUT_DIR` | 构建产物输出目录 | `../backend/static` |
| `VITE_MAP_TILE_URL` | Leaflet 瓦片地址模板（支持 `{s}/{z}/{x}/{y}`） | 高德地图瓦片 |
| `VITE_MAP_TILE_ATTRIBUTION` | 地图底图署名 HTML | 高德地图署名 |
| `VITE_MAP_TILE_DATUM` | 底图瓦片坐标系（`gcj02` 或 `wgs84`） | `gcj02` |

`VITE_BASE` 与 `VITE_MAP_TILE_*` 在启动开发服务器或执行构建时读取；切换为 OpenStreetMap 等 WGS-84 底图时，请将 `VITE_MAP_TILE_DATUM` 设为 `wgs84`。配置示例见 `.env.example`。

## 检查与构建

```bash
npm run type-check   # 运行 TypeScript 类型检查
npm run lint         # 运行 ESLint 代码检查
npm run test         # 运行 Vitest 单元测试
npm run build        # 构建生产产物至 ../backend/static
npm run check        # 依次执行 type-check、lint、test 与 build
```

子路径构建示例：

```bash
VITE_BASE=/journeypilot/ VITE_OUT_DIR=dist npm run build
```

Playwright 浏览器端到端测试说明请参阅 [e2e/README.md](e2e/README.md)。
