# 20261029-1917 行程体验改动：集成验收

- 结论：五项任务代码验收通过，状态均为“待真人验收”。
- 实现方式：Workflow 四段串行实现覆盖五项任务，独立审查、修复与复审；主代理继续修复复审遗留并完成最终集成验收。
- 工作区：使用 `output/polish/20261029-1917-batch/baseline/` 核对本轮增量，保留已有改动。用户随后明确要求将全部待提交修改分组保存，按六笔提交组织（见 Git 日志）；提交不自动改变真人验收状态，未推送。

## 最终行为

1. 普通日程、旅中今天视图、地图 Marker／路线悬浮仅高亮。显式点击／键盘激活才定位；选中切换先退出旧详情，整个切换过程最多一块详情面板。
2. 桌面面板在 1280／1440／2000px 视口分别约 520／560／640px。全程为连续日目录，单日日头无独立卡片，天气与日期、周几、地点同行靠右。地图避让取实际面板右缘。
3. 高铁和飞机头部合并图标、班次和时间，高铁无站码；时长左、费用右，无重复标签。仅这两类隐藏路线按钮，其他方式保留既有操作。地铁显示 Provider 真实上下车站；混合模式标注真实首末乘坐方式；同线不同班次不算换线，0 换乘不显示。
4. 完整行程物化后，经现有 router 的 SUMMARY 档批量写总标题与所有每日主题，校验字符串及 10–15 有效字符，按 day_id 写回。预算／时限／结构失败保留既有文案，取消正常透传。工作台、阅读版与 PDF 使用同一正式 title/theme。

## 最终验证

- 后端 83 项定向测试通过：Amap／Transitous 归一化、接驳物化与候选替换、变更、自然标题、PDF、通用换乘语义。
- 本轮 20 个 Python 新增／变化文件 `ruff check` 全部通过。
- 前端类型检查通过；transportPresentation、mapModel、mapPlaces、workspaceTransition 共 39 项单测通过。
- 本轮最终 Playwright 定向 13/13 通过：普通日程、今天视图、无重叠详情切换、2000／1440／1280 布局、390px 的 1／14 天、交通展示、手机 Sheet 与阅读往返。末次仅调整阅读标题换行后，阅读往返单项再验通过。
- 补充审查后，路线详情改为断言新路线特有的 `24 分钟` 与 `9.2 公里`，避免只看见旧详情也算通过；普通日程与无重叠详情切换两项定向复验 2/2 通过，证据在 `output/polish/20261029-1917-batch/detail-content-e2e/`。
- 最终构建成功，产物与构建日志保存在本批次 output 内，未覆盖 backend/static。
- 本机已通过 run.sh 重新启动；8001 与 8080 的 `/api/health/ready` 均 HTTP 200、status=ready。
- 用户要求提交全部修改后，补充检查覆盖此前需求／规划流程：后端非数据库测试 747/747、会话数据库测试 13/13、前端单测 95/95、四套离线浏览器用例 64/64 全部通过；后端完整 lint、前端类型检查通过。提交前 diff 空白检查通过。测试日志在 `output/commit-20261029/`。

最终后端命令：

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/integrations/routes/test_amap_paths.py backend/tests/integrations/routes/test_global_search_paths.py backend/tests/planning/itinerary/test_connector_route_completion.py backend/tests/planning/itinerary/test_revision.py backend/tests/planning/itinerary/test_title_writing.py backend/tests/planning/delivery/test_pdf_export.py backend/tests/planning/test_transport_semantics.py -q
```

最终前端命令（frontend 下）：

```bash
npm run type-check
npm run test -- src/features/travel/model/transportPresentation.test.ts src/features/travel/model/mapModel.test.ts src/features/travel/model/mapPlaces.test.ts src/features/travel/model/workspaceTransition.test.ts
JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'desktop itinerary|mixed transport|today view|reading and map|phone itinerary layout|phone sheet|phone card selection|map detail switches' --workers=1 --output=../output/polish/20261029-1917-batch/final-e2e
VITE_OUT_DIR=../output/polish/20261029-1917-batch/build npm run build
```

## 实屏证据

以下截图来自最终真实组件，API／瓦片均使用隔离离线夹具。示例文案用于验证呈现与同源，不冒充真实模型输出；空白地图底色是瓦片拦截结果。

- [最终全程](../../../output/polish/20261029-1917-batch/final-overview-2000.png)
- [最终单日](../../../output/polish/20261029-1917-batch/final-day-2000.png)
- [最终阅读版](../../../output/polish/20261029-1917-batch/final-reading-2000.png)
- [高铁／飞机／地铁](../../../output/polish/20261029-1917-transport-display/transport-desktop-1440.png)
- [地铁换乘与混合方式](../../../output/polish/20261029-1917-transport-display/transport-metro-desktop-1440.png)
- [手机交通](../../../output/polish/20261029-1917-transport-display/transport-phone-390.png)
- [桌面与手机布局汇总](../../../output/polish/20261029-1917-batch/layout-contact-sheet.png)

## 真人验收与实际限制

- 打开已有行程，把鼠标移过多个地点／地图图标，确认无自动定位；点击后才定位和开详情。
- 查看全程与单日，确认面板宽度、目录、天气位置和交通简洁程度；手机可滚动、切日、打开详情。
- 下次完整生成时观察总标题和每日主题的自然度，并核对阅读版／PDF 一致。
- 本轮没有调用真实付费模型／Provider，也没有写真实会话。真实文案质量由下一次完整生成验收；历史行程不批量改名。
- 局部 mutation 保留正式文案快照；完整重新组合后再生成标题，数据库事务和投影重试中不调用模型。缺站点／线路／价格时不编造。
