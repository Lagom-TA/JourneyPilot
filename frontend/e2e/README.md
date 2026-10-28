# 真实端到端测试

先启动一套配置完成的 JourneyPilot。默认套件（冒烟、移动导航、home-inspiration）连接页面与 `/api/`；带 `JP_*` 开关的用例按各自说明运行。Compose 的网页入口通常是 `http://127.0.0.1:8001`；`run.sh` 的前端通常是 `http://127.0.0.1:8080`。

在 `frontend/` 下执行：

```bash
# 页面加载、readiness 结构、文件拒绝边界、导航与刷新。
JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 npm run test:e2e

# 真实资料库与风格 CRUD；只删除本次唯一命名的测试数据。
JP_WRITE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/workspace.spec.ts --workers=1

# 会调用真实付费模型，并保留新建的旅行供核对。
# 上海 → 苏州，当前日期后两天起，两天一晚。
JP_LIVE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/live-planning.spec.ts --workers=1

# 只传入已完成的测试旅行；全程只读，不创建或撤销直接编辑。
JP_READ_RUN_ID=trip_替换为测试运行ID JOURNEYPILOT_APP_URL=http://127.0.0.1:8001 \
  npx playwright test e2e/delivery-readonly.spec.ts --workers=1
```

未显式开启的写入、付费和交付修改用例会显示 **skipped**，不代表已经验证。冒烟测试允许 readiness 返回 503，以检查降级状态的响应合同；判断部署可用仍须确认 `/api/health/ready` 为 200、`status=ready`。

完整规划测试覆盖真实地点候选、日期输入、审批前刷新恢复、确认调研、持久化终态、两天行程/住宿/交通、SSE 与 Bundle 身份一致、报告 PDF 下载、交付后刷新以及移动端报告。审批前读取尚不存在的 Bundle 返回 404 是接口合同；只有恢复审批期间对应 Run 的这个响应被排除，交付后的 404 仍会失败。

通过 `--output=../temp/本轮目录` 分开保存各轮证据，避免默认输出目录在下一次运行时被清理。完整规划用例保存 SSE、Run/Bundle 快照、截图、PDF 和浏览器诊断；失败另存 Playwright trace/video。这些原始材料可能包含真实请求和服务结果，应保留在忽略目录，勿提交。

模型输出具有不确定性，外部服务也可能失败。完整用例最多等待 15 分钟；失败须区分应用故障、上游失败和测试选择器错误，不应通过放宽交付要求或改用模拟响应来让测试通过。资料或风格操作若在超时过程中中断，检查本轮唯一名称并仅清理对应测试记录。

研究进度组件回归使用明确标注的本地样例，覆盖 JSON 防泄露、并行 Agent 状态、查询详情与移动布局；不请求模型或修改会话。先启动 Vite 开发服务器，再运行：

```bash
JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 \
  npx playwright test e2e/research-progress.spec.ts
```

home 首页灵感轮播回归在浏览器内拦截 `/api/` 返回本地夹具数据，覆盖默认风格卡片与条件表单；同样只需要 Vite 开发服务器：

```bash
JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 \
  npx playwright test e2e/home-inspiration.spec.ts
```

离线会话与地图工作区回归使用本地两日西安夹具，覆盖连续地点卡、三类地点 Marker、真实路径与端点示意、悬浮定位、详情焦点、日期与图层、阅读版地图实例以及移动 Sheet。API 与地图瓦片都在浏览器内拦截，不访问外部服务，也不修改会话。先启动 Vite 开发服务器，再运行：

```bash
JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 \
  npx playwright test e2e/session-state.spec.ts
```
