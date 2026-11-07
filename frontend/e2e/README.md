# 浏览器端到端测试（Playwright）

端到端测试位于 `frontend/e2e/`，用于验证页面交互、工作台组件状态流转以及前后端联调。

运行前请先启动服务，并通过 `JOURNEYPILOT_APP_URL` 指定访问地址（默认为 `http://127.0.0.1:8080`）：
- **本地开发前端（`:8080`）**：由 `./run.sh start` 或 `npm run dev` 启动的 Vite 服务提供，包含 `/e2e/fixtures/*.html` 组件测试夹具。
- **构建产物入口（`:8001`）**：由 Docker Compose 或后端静态托管提供，适合运行面向完整应用的联调测试。

在 `frontend/` 目录下执行：

```bash
# 运行全部默认启用的测试
JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 npm run test:e2e

# 仅检查测试文件编译并列出所有用例
npx playwright test --list
```

## 用例与运行条件

| 测试文件 | 默认运行 | 适用环境与说明 |
|---|---|---|
| `smoke.spec.ts` | 是 | 完整应用；验证首页加载、`/api/health/ready` 与知识库接口连通性 |
| `mobile-navigation.spec.ts` | 是 | 完整应用；验证移动端抽屉导航与页面切换 |
| `home-inspiration.spec.ts` | 是 | 任意前端入口；拦截 `/api/` 验证首页灵感卡片与输入交互 |
| `planner-intake.spec.ts` | 是 | 任意前端入口；拦截 `/api/` 验证自由输入与条件表单 |
| `multi-round-intake.spec.ts` | 是 | 任意前端入口；拦截 `/api/` 验证多轮需求追问交互 |
| `generation-workspace.spec.ts` | 是 | Vite dev 服务（`:8080`）；通过本地夹具验证生成工作台四阶段交互 |
| `archive-workspace.spec.ts` | 是 | 任意前端入口；拦截 `/api/` 验证我的行程、偏好设置与个人资料管理 |
| `delivery-workspace.spec.ts` | 是 | 任意前端入口；拦截 `/api/` 与瓦片请求，验证地图、日程与阅读版联动 |
| `session-state.spec.ts` | 需 `JP_SESSION_STATE_E2E=1` | Vite dev 服务（地址须为 `http://127.0.0.1:<端口>`）；验证多会话状态切换与恢复 |
| `map-load-failure.spec.ts` | 需 `JP_MAP_LOAD_FAILURE_E2E=1` | Vite dev 服务（地址须为 `http://127.0.0.1:<端口>`）；验证地图瓦片加载降级提示 |
| `research-progress.spec.ts` | 需 `JP_COMPONENT_E2E=1` | Vite dev 服务（`:8080`）；验证调研进度与 SSE 事件流夹具 |
| `deployment-settings.spec.ts` | 需 `JP_DEPLOYMENT_URL=<URL>` | 自定义子路径与瓦片源的 Vite 服务；验证部署环境变量生效 |
| `workspace.spec.ts` | 写入用例需 `JP_WRITE_E2E=1` | 完整应用；测试真实知识库资料与旅行风格的增删改查 |
| `live-planning.spec.ts` | 需 `JP_LIVE_E2E=1` | 完整应用与可用大模型（可选 `JP_LIVE_DESTINATION=苏州`）；验证真实端到端行程生成 |
| `delivery-readonly.spec.ts` | 需 `JP_READ_RUN_ID=<run_id>` | 完整应用；对已生成的历史行程做只读渲染验证 |

## 常用运行命令

```bash
# 运行离线首页与需求输入测试
JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 \
  npx playwright test e2e/home-inspiration.spec.ts e2e/planner-intake.spec.ts e2e/multi-round-intake.spec.ts

# 运行生成工作台与研究进度组件夹具测试（需 Vite dev 服务 :8080）
JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 \
  npx playwright test e2e/generation-workspace.spec.ts

JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 \
  npx playwright test e2e/research-progress.spec.ts

# 运行会话状态与地图异常降级测试（需 127.0.0.1 的 Vite dev 服务）
JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 \
  npx playwright test e2e/session-state.spec.ts

JP_MAP_LOAD_FAILURE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 \
  npx playwright test e2e/map-load-failure.spec.ts

# 验证局域网子路径与自定义瓦片部署（先在终端 A 启动定制 Vite 服务，再在终端 B 运行测试）
HOST="$LAN_HOST" PORT=8082 VITE_BASE=/journeypilot/ \
  VITE_MAP_TILE_URL="http://$LAN_HOST:8082/custom-tile/{z}/{x}/{y}.png" \
  VITE_MAP_TILE_ATTRIBUTION="Offline Tile" npm run dev

JP_DEPLOYMENT_URL="http://$LAN_HOST:8082" npx playwright test e2e/deployment-settings.spec.ts

# 运行真实后端写入与真实模型规划测试
JP_WRITE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/workspace.spec.ts --workers=1

JP_LIVE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/live-planning.spec.ts --workers=1

# 验证已有行程的只读交付页面
JP_READ_RUN_ID=trip_xxx JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/delivery-readonly.spec.ts --workers=1
```

## 测试产物与报告

- 测试失败时，Playwright 会自动在 `test-results/` 下保存页面截图、执行 Trace 与录屏；当环境中存在 `CI` 变量时，还会生成 `test-results/playwright-junit.xml` 报告。
- `live-planning.spec.ts` 在运行真实规划时会额外归档 SSE 事件流、Run/Bundle 快照与导出的 PDF 文件，便于回溯分析。
