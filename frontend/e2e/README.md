# 端到端测试

先把一套 JourneyPilot 跑起来，再用 `JOURNEYPILOT_APP_URL` 指向入口。Compose 的网页入口通常是 `http://127.0.0.1:8001`；`run.sh` 的前端入口是 `http://127.0.0.1:8080`。命令在 `frontend/` 下执行（Node 版本见 `frontend/.nvmrc`）。

```bash
JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 npm run test:e2e
```

`test:e2e` 是裸 `playwright test`，会执行所有未 skip 的用例。带 `JP_*` 开关的用例未开启时显示 skipped；skipped 不代表已验证。默认 e2e 不在 CI 中；只想检查 spec 能否编译/列出时：

```bash
npx playwright test --list
```

## 用例与前置条件

| 文件 | 默认执行 | 前置条件 | 外部依赖 |
|---|---|---|---|
| `smoke.spec.ts` | 是 | 完整应用 | 读取 `/api/health/ready` 与 `/api/knowledge/*` |
| `mobile-navigation.spec.ts` | 是 | 完整应用 | 页面与本地 API |
| `home-inspiration.spec.ts` | 是 | 可打开页面（Vite dev 或已构建应用） | 无；`/api/` 在浏览器内拦截 |
| `planner-intake.spec.ts` | 是 | 可打开页面 | 无；`/api/` 在浏览器内拦截 |
| `multi-round-intake.spec.ts` | 是 | 可打开页面 | 无；`/api/` 在浏览器内拦截 |
| `session-state.spec.ts` | `JP_SESSION_STATE_E2E=1` | 可打开页面 | 无；`/api/` 与地图瓦片在浏览器内拦截 |
| `map-load-failure.spec.ts` | `JP_MAP_LOAD_FAILURE_E2E=1` | 可打开页面 | 无；只模拟瓦片失败 |
| `f3-workspace.spec.ts` | 无 | 可打开页面 | 无；正式工作台组件，API 在浏览器内拦截 |
| `f4-workspace.spec.ts` | 无 | 可打开页面 | 无；正式交付工作台，API 与瓦片在浏览器内拦截 |
| `research-progress.spec.ts` | `JP_COMPONENT_E2E=1` | 可打开页面 | 无；使用本地组件样例 |
| `deployment-settings.spec.ts` | `JP_DEPLOYMENT_URL=<局域网 HTTP 地址>` | 单独启动指定子路径和自定义瓦片的 Vite 服务 | API 与瓦片在浏览器内拦截 |
| `workspace.spec.ts` | 部分；写入用例需 `JP_WRITE_E2E=1` | 完整应用 | 真实资料库与风格写入；只删除本次唯一命名的测试数据 |
| `live-planning.spec.ts` | `JP_LIVE_E2E=1` | 完整应用与可用模型 | 调用真实付费模型，并保留新建旅行 |
| `delivery-readonly.spec.ts` | `JP_READ_RUN_ID=<run_id>`（也接受 `JP_EDIT_RUN_ID`） | 同一会话中较早的已完成测试行程 | 只读；不写入、不撤销 |

## 常用命令

```bash
# 三个纯离线首页/工作台用例，只需要可打开的页面
JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 \
  npx playwright test e2e/home-inspiration.spec.ts e2e/planner-intake.spec.ts e2e/multi-round-intake.spec.ts

# 生成工作台、查询来源与 SSE 状态
JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 \
  npx playwright test e2e/f3-workspace.spec.ts e2e/research-progress.spec.ts

# 离线会话与地图工作区
JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 \
  npx playwright test e2e/session-state.spec.ts

# 局域网 HTTP、子路径与自定义瓦片；LAN_HOST 为本机局域网地址
HOST="$LAN_HOST" PORT=8082 VITE_BASE=/journeypilot/ \
  VITE_MAP_TILE_URL="http://$LAN_HOST:8082/custom-tile/{z}/{x}/{y}.png" \
  VITE_MAP_TILE_ATTRIBUTION="Offline Tile" npm run dev
# 在另一终端执行；测试会拦截 API 和瓦片请求
JP_DEPLOYMENT_URL="http://$LAN_HOST:8082" npx playwright test e2e/deployment-settings.spec.ts

# 真实资料库与风格 CRUD
JP_WRITE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/workspace.spec.ts --workers=1

# 真实付费生成：上海到苏州，当前日期后四天，两日一晚；追问时选择测试选项并提交。
JP_LIVE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/live-planning.spec.ts --workers=1

# 只读查看一个已完成的 run
JP_READ_RUN_ID=trip_xxx JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/delivery-readonly.spec.ts --workers=1
```

## 证据与失败处理

- 截图、JSON 几何数据与附件写入 `test-results/e2e-evidence/`；trace、video、junit 报告也在 `test-results/` 下，均已被 Git 忽略。
- 完整规划用例保存 SSE、Run/Bundle 快照、截图、PDF 与浏览器诊断；原始材料可能包含真实请求和服务结果，只能留在忽略目录。
- 模型输出不确定，外部服务也可能失败。完整规划用例最多等待 35 分钟；失败时先区分应用故障、上游失败与选择器错误，不通过放宽交付要求或改用模拟响应让用例通过。
- 冒烟测试允许 readiness 返回 503，以检查降级响应合同；判断部署可用仍须确认 `/api/health/ready` 返回 200 且 `status=ready`。
