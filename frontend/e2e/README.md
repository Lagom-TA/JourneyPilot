# 浏览器回归与端到端测试（Playwright）

测试按环境分为 `offline` 和 `integration` 两个原生 Playwright project。同一用例只属于其中一个项目；离线浏览器回归验证真实组件与浏览器交互，完整服务联调验证实际 API、部署与持久化。

在 `frontend/` 目录安装依赖与浏览器：

```bash
npm ci
npx playwright install chromium
```

## 离线浏览器回归

```bash
# 自动启动并在结束后关闭独立的 Vite 服务，不需要数据库或模型密钥
npm run test:e2e:offline

# 按受影响功能运行，仍使用同一套隔离服务
npm run test:e2e:offline -- e2e/research-progress.spec.ts e2e/research-progress-layout.spec.ts
npm run test:e2e:offline -- e2e/session-state.spec.ts
npm run test:e2e:offline -- e2e/map-load-failure.spec.ts
```

`playwright.offline.config.ts` 使用当前工作区源码启动 `http://127.0.0.1:4173`，由 Playwright 管理服务生命周期。端口已占用时明确失败，不复用可能属于其他版本的服务。测试中的 API、SSE 与瓦片使用夹具；专用 Vite 配置关闭 API 代理，并对漏拦截的 `/api` 请求明确返回 503，无法转发到正在运行的真实后端。`JOURNEYPILOT_APP_URL` 不改变这个隔离入口。

离线项目中所有用例直接执行，包括会话恢复、地图失败和研究进度，不需要额外的 opt-in 变量。

| 测试文件 | 保护的行为 |
|---|---|
| `home-inspiration.spec.ts` | 首页灵感、两种输入模式、地点搜索与键盘交互 |
| `planner-intake.spec.ts`、`planner-pending.spec.ts`、`multi-round-intake.spec.ts` | 需求输入、交接、等待、取消与多轮追问 |
| `generation-workspace.spec.ts` | 生成工作台阶段与研究方案操作 |
| `archive-workspace.spec.ts` | 我的行程、偏好、资料管理及失败反馈 |
| `delivery-workspace.spec.ts` | 地图、日程、阅读版联动与交付失败反馈 |
| `session-state.spec.ts` | 多会话隔离、断线恢复、审批与只读历史 |
| `map-load-failure.spec.ts` | 地图模块加载失败、日程可用与恢复 |
| `research-progress.spec.ts`、`research-progress-layout.spec.ts` | SSE 事件投影、任务详情、可读布局与键盘操作 |

布局测试保留无溢出、可读字号、触控范围、对齐与键盘操作保护。装饰边框、伪元素和具体留白值由界面设计决定，不固定为行为契约。

## 完整服务与部署联调

先通过 `./run.sh start` 或 Docker Compose 启动完整服务，再指定 Vite 代理入口或构建产物入口：

```bash
JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 npm run test:e2e:integration
```

这个命令连接已有服务，不自动启动离线 Vite。实际写入、真实模型调用、历史行程读取与特殊部署仍各自显式启用。

| 测试文件 | 运行条件与保护的行为 |
|---|---|
| `smoke.spec.ts` | 默认执行；首页挂载、readiness 组件状态和非法上传拒绝 |
| `mobile-navigation.spec.ts` | 默认执行；移动导航、焦点与页面切换 |
| `workspace.spec.ts` | 默认检查导航与恢复；写入用例需 `JP_WRITE_E2E=1`，只创建和清理自身测试资料与风格 |
| `live-planning.spec.ts` | 需 `JP_LIVE_E2E=1` 和可用模型；验证真实规划并产生供应商费用 |
| `delivery-readonly.spec.ts` | 需 `JP_READ_RUN_ID=<run_id>`；检查已有交付及 PDF |
| `deployment-settings.spec.ts` | 需 `JP_DEPLOYMENT_URL=<URL>`；检查子路径、定制瓦片与非安全 HTTP 环境 |

```bash
# 真实后端写入
JP_WRITE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npm run test:e2e:integration -- e2e/workspace.spec.ts --workers=1

# 真实模型规划，可通过 JP_LIVE_DESTINATION 指定目的地
JP_LIVE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npm run test:e2e:integration -- e2e/live-planning.spec.ts --workers=1

# 已有行程的只读交付
JP_READ_RUN_ID=trip_xxx JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npm run test:e2e:integration -- e2e/delivery-readonly.spec.ts --workers=1

# 定制部署：终端 A 启动，终端 B 运行测试
HOST="$LAN_HOST" PORT=8082 VITE_BASE=/journeypilot/ \
  VITE_MAP_TILE_URL="http://$LAN_HOST:8082/custom-tile/{z}/{x}/{y}.png" \
  VITE_MAP_TILE_ATTRIBUTION="Offline Tile" npm run dev

JP_DEPLOYMENT_URL="http://$LAN_HOST:8082" \
  npm run test:e2e:integration -- e2e/deployment-settings.spec.ts
```

`npm run test:e2e` 同时选择两个项目，并连接 `JOURNEYPILOT_APP_URL`（默认 `http://127.0.0.1:8080`）。使用该入口跑全部用例时，应提供带真实 API 代理的 Vite 服务，既能加载 `/e2e/fixtures/*.html`，也能处理完整服务联调。仅提供构建产物的 `:8001` 入口应选择 `test:e2e:integration`。

## 收集、验证与报告

```bash
npm run type-check                  # TypeScript 类型检查，包括配置、规格与组件夹具
npm run test:e2e:offline -- --list    # 只收集离线用例，不启动服务、不执行断言
npm run test:e2e:integration -- --list
```

- `--list` 只证明用例可以收集；类型检查、浏览器执行与完整服务验收分别报告。
- CI 禁止 `.only`，失败可重试一次以保留诊断证据；首次失败后重试成功仍使门禁失败，不以重试隐藏不稳定行为。
- 失败截图、Trace 与录屏写入 `test-results/`；设置 `CI` 时额外生成 `test-results/playwright-junit.xml`。
- `live-planning.spec.ts` 还会归档 SSE 事件、Run/Bundle 快照和 PDF。
- 环境未满足或主动跳过的用例不计为通过。离线结果证明前端行为，真实供应商、数据库与定制部署需要对应联调结果。
