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
- 不同会话的运行流独立保存；切换会话时保留各自的实时快照，停止当前会话不会中断其他会话。
- 状态：`src/app/state/` 只有唯一 reducer 与 provider；会话切换、恢复、清空与正式 Bundle 确认都经过同一更新边界。
- 正式交付只接受完整 `DeliveryBundle`，过程事件可以流式；报告、行程、地图、来源与天气来自同一份交付记录。
- 交付以地图画幅呈现全程，城市导航按连续停留段分组，单日展开为日程与地图对页；地图保持挂载并按上下文保留视野。手机日程面板为非模态的两档面板，拖动手柄时持续跟手，释放后按位置与速度吸附，地图按半屏可见区域避让。阅读版以不透明侧向表面进入，Esc 或返回按钮关闭后恢复入口焦点与地图视野。未安排事项按天关联，资料缺口与事实来源按需展开。

## 行程与个人资料

`PageShell` 与 `styles/archive.css` 组织开放档案页，页面统一滚动；偏好分类在桌面标题下与手机标题后显示。行程按会话收拢生成记录，当前与历史共用正式会话恢复边界。选择旅行风格通过 `useStartNewTrip` 新建旅行；首页只在有选择或失效提示时显示风格上下文。资料正文默认只读，编辑与取消明确分开，保存失败保留草稿。文件上限来自 `/api/config` 的 `ingest.max_upload_bytes`，上传仍由服务端最终校验。

## 样式与视口

- `src/index.css` 定义全局 token、基础样式和共享过程样式；`src/styles/` 按首页、应用壳、开放档案、行程列表与工作台分文件，由 `src/main.tsx` 按顺序加载。全局组件和复杂布局使用语义类，组件内部的简单排列使用 Tailwind 工具类。
- 颜色、圆角、阴影、CSS 动效和全局层级使用 `src/index.css` 的 token；Motion 使用 `src/lib/motion.ts` 中的秒制时长与缓动，交通方式颜色集中在 `src/features/travel/model/transportPresentation.ts`。
- `breakpoints.json` 定义 Tailwind 与 JS 共用的 `sm` 640、`md` 768、`lg` 1024、`xl` 1280 和 `2xl` 1536 像素断点。CSS 媒体查询使用相同边界；480、1440、1800 像素和高度 760 像素是局部布局的补充条件。
- 字体通过 Fontsource 本地加载：Inter 处理拉丁字符，Noto Sans SC 处理中文正文；档案页和主要交付标题使用 Noto Sans SC 粗体；衬线标题优先使用本地 14 字子集，缺失字符回退到完整的 Noto Serif SC，最后回退系统字体。字体使用 `font-display: swap`。

全局层级以同一层叠上下文内的数值为准；组件内部的 0–50 只控制局部层叠。

| token | 值 | 用途 |
|---|---:|---|
| `--z-map-empty` | 900 | 地图空状态 |
| `--z-map-controls` / `--z-map-detail` | 1000 / 1001 | 地图控件和地点详情 |
| `--z-recovery` | 1050 | 移动端恢复提示 |
| `--z-workspace-panel` / `--z-sheet` | 1100 | 行程浮面板和底部抽屉 |
| `--z-navigation-scrim` / `--z-navigation-drawer` | 1110 / 1120 | 移动导航遮罩和抽屉 |
| `--z-recovery-desktop` | 1150 | 桌面端恢复提示 |
| `--z-reading` / `--z-dialog` | 1200 | 阅读层、模态框、弹出层和日历 |
| `--z-destination-menu` | 1400 | 目的地搜索候选 |

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
| `VITE_MAP_TILE_DATUM` | 瓦片坐标系：`gcj02` 或 `wgs84` | `gcj02` |

`VITE_BASE` 和 `VITE_MAP_TILE_*` 在 Vite 启动或前端构建时读取；修改后需要重启开发服务器或重新构建。更换底图时，按瓦片提供方的坐标系设置 `VITE_MAP_TILE_DATUM`；WGS-84 底图应设为 `wgs84`，无效值会导致地图配置初始化失败。子路径部署还需要静态服务器或反向代理把该路径映射到前端产物，后端默认只提供根路径。示例见 `.env.example`。

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
