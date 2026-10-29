# 保留地铁上下车站事实，核对换乘语义

- 编号：20261029-1917-transit-route-facts
- 状态：待真人验收
- 创建：2026-10-29 19:17
- 执行前先读：[工作目录 README](../README.md)、backend/tests/README.md、docs/architecture/overview.md、docs/invariants.md、AGENTS.md；前端类型需改时再读 frontend/README.md

## 1 用户反馈

> 在地铁当中，出发地和到达地应该是两个地铁站，而且我们的换乘是只算地铁的换乘的，如果是步行转地铁转步行，这不叫换乘，只有不同地铁线路之间才叫换乘

截图：`output/polish/20261029-1917-transit-route-facts/feedback-1.png`。用户圈出“北京西 → 东来顺饭庄（王府井店）”，要求改为实际地铁站。

## 2 现象与发生条件

市内接驳选择地铁，整段接驳从铁路车站／景点到饭店等 POI。整段起终点与实际地铁上下车站是两种不同事实，需要同时保留；前端卡片展示站点时不能拿整段终点代替。

## 3 根因

- `backend/travel_agent/integrations/routes/amap.py:290` 起原本已读取 departure_stop／arrival_stop 的真实站名与坐标，但 `:310`、`:311` 又把首末分段端点覆盖为查询起终点。若首末段恰为地铁段、无实际步行段，真实上下车站会丢失。`global_search.py:212`、`:219` 有同类覆盖。
- `backend/travel_agent/planning/itinerary/models.py:58` 起要求首末 segment 端点与 leg 端点相等。这是现有整段行程连续性约束，不能简单删除 Provider 的覆盖语句后让正式模型验证失效。
- 前端 `TransportLegCard.tsx:114` 又直接显示 leg 端点，因此即便中间分段有站点，也没有消费。前端消费由 `transport-display` 处理；本任务让真实站点能完整进入正式数据。
- `backend/travel_agent/planning/transport_semantics.py:58` 已忽略步行并识别同服务拆段；`TransportLeg.validate_route` 会用此规则重算。**未确认存在“步行被计入换乘”的后端 bug**。用户要求在此作为回归条件，不能重写已有正确语义。通用服务换乘可包含不同交通服务，地铁卡只展示地铁换线由前端任务处理，不能全局把铁路／公交换乘改成地铁专用计数。

## 4 方案

目标状态：一段地铁接驳同时保留整段 POI→POI 连接和实际地铁上下车站；正式消费者可以可靠区分，不需要猜站名。步行接驳与线路拆段不制造换乘。

必须做：

- 沿实际 Provider 响应→归一化 route→catalog→TransportLeg／segments→公开序列化核对站点身份，修复首末乘车段真实站点被 POI 覆盖的问题；Amap 与已有同类适配器使用一致的站点语义。
- 同时维持真实相邻行程起终点、connector 匹配、时间／距离／费用、坐标体系和地图几何。不得把地铁站替代 POI 作为整段接驳终点，导致行程到不了饭店；不得编造步行时长、距离、轨迹以满足模型相等约束。
- 优先复用已有结构；若确需独立承载 boarding/alighting 事实，本任务明确授权最小必要的**可选站点字段**及其 Python 模型、JSON 持久化读写、公开投影、TypeScript 类型调整。只保存 Provider 已给出的事实，旧 Bundle 缺字段可正常读取。保持单一事实源与清楚归属，不同时维护多套竞争站点字段。
- 上述最小可选字段变更不需要再次请求用户授权；记录字段来源、缺失语义和兼容验证。不得扩展为数据库 DDL、破坏性版本切换或新的路线查询服务。
- 站点缺失时诚实保留缺失；不能给饭店名加“站”、凭行政地址推断地铁站、用任意最近站假冒实际上下车站，或重新调用模型写站名。
- 用真实结构的离线 Provider 夹具覆盖有步行／零距离步行／无步行首末地铁段，验证已提供站点不丢失、未提供站点不编造；并确认步行→同一地铁线→步行为 0 次、同线拆段为 0 次、明确换两条地铁线为 1 次。
- 不重复建设换乘计数规则；若已有 helper 通过所需场景，保留并补充覆盖即可。向 `transport-display` 交接可用字段、站点可证实条件与缺失策略。

执行者自己决定：保真表示方式、最小可选字段是否必要及其具体归属、公共入口回归构造。必须通过当前模型验证，不在本任务里先写大规模模型迁移方案。

不许碰：旅行规划偏好、费用预算、供应商选择／新增查询、真实用户数据、铁路／飞机事实、地图坐标与几何含义、无关前端布局。不调用真实模型或 Provider，不提交不推送。既有工作区改动保留。

## 5 停下来报告的情况

若必须破坏既有 Bundle 可读性、修改 SQL schema 或重定义通用 transfer_count 才能保存站点，给出具体约束证据并报告。最小可选站点字段和兼容读写已在本任务授权，不能仅以“涉及数据模型”机械受阻。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. Provider 给出的地铁上下车站可沿正式投影读到，首末段无步行时同样保真；整段 POI 起终点仍然正确。
2. 站点字段来源真实且语义明确，缺失不伪造；旧 Bundle 可读，新数据可序列化并经实际模型验证。
3. 步行与同线拆段均不计换乘，明确地铁换线计 1 次；通用其他服务换乘语义未被地铁展示要求误改。
4. 原几何、坐标、线路身份和时长／费用保留，没有添加虚构接驳段来绕验证。

### 6.2 必须运行的检查

仓库根目录：

- `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/integrations/routes/test_amap_paths.py backend/tests/integrations/routes/test_global_search_paths.py backend/tests/planning/itinerary/test_connector_route_completion.py backend/tests/planning/itinerary/test_revision.py -q`
- 对本任务实际修改的 Python 文件运行 `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend ruff check --config backend/pyproject.toml <实际改动文件>`，记录完整命令。
- 若公开投影／模型有新增字段，增加一条从真实 Provider 夹具经模型、公开序列化到读回的定向回归，验证旧字段缺失的兼容；在执行记录列出该用例并运行。
- 若触碰 TypeScript 类型：在 `frontend/` 运行 `npm run type-check`。

测试只替身外部 Provider 边界，不为私有 helper 的调用顺序写测试；现有 Provider 路径用例可扩展站点断言，不新增全面快照。

### 6.3 实屏证据（执行者提供）

本任务为站点事实保真，不单独要求截图；用户可见站名与换乘展示截图由关联 `transport-display` 提供。

### 6.4 真人验收（用户操作）

1. 关联交通展示任务完成后，看地铁主行 → 出发和到达均为实际地铁站；可查看进出站接驳，整段行程仍到达原目的地。
2. 对照一条步行进出站、一条真实换线行程 → 前者无换乘提示，后者只计算实际地铁换线。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 21:45 · pi / executor

- 改动摘要：
  - Provider 归一化在把首末段端点收敛到整段 POI 起终点之前，先读取真实上下车站，保存到可选 `boarding_stop` / `alighting_stop`。Amap 和 Transitous 都只保留 Provider 明确给出站名的站点；缺站名时留空，不借用 POI 名或最近站。
  - `TransportCandidate`、`TransportLeg`、公开行程投影、connector 证据字段和工具结果路由字段链路携带同一组可选站点；旧 Bundle 缺字段时按 `None` 读取。
  - 未重写换乘规则；补充回归确认步行进出站为 0 次、同线拆段为 0 次、不同地铁线为 1 次。`transfer_count` 继续复用 `count_service_transfers`。
  - 工具结果压缩对 routes 字典保留上限从 12 调到 16，避免新增的站点事实把 `segments` 截掉。
- 改动文件：
  - `backend/travel_agent/integrations/routes/amap.py`
  - `backend/travel_agent/integrations/routes/global_search.py`
  - `backend/travel_agent/planning/research/candidates.py`
  - `backend/travel_agent/planning/research/transport/local_routes.py`
  - `backend/travel_agent/planning/itinerary/models.py`
  - `backend/travel_agent/planning/itinerary/materialize.py`
  - `backend/travel_agent/planning/delivery/public/itinerary.py`
  - `backend/travel_agent/tools/content.py`
  - `backend/travel_agent/tools/governance.py`
  - `frontend/src/features/travel/types/itinerary.ts`
  - `backend/tests/integrations/routes/test_amap_paths.py`
  - `backend/tests/integrations/routes/test_global_search_paths.py`
  - `backend/tests/planning/itinerary/test_connector_route_completion.py`
  - `backend/tests/planning/test_transport_semantics.py`（新增）
- 偏离方案及理由：采用任务已授权的“最小可选站点字段”，放在 transport leg 上而不是改写首末 segment 端点。这样接驳缺口匹配、POI 起终点、connector 连续性和地图几何都保持原合同；Provider 站点仍只有一个事实源。没有删除 `TransportLeg` 的端点相等校验，也没有编造进站步行段。
- 实际运行的检查与结果：
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/integrations/routes/test_amap_paths.py backend/tests/integrations/routes/test_global_search_paths.py backend/tests/planning/itinerary/test_connector_route_completion.py backend/tests/planning/itinerary/test_revision.py -q`：62 passed。
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/planning/test_transport_semantics.py -q`：3 passed。
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend ruff check --config backend/pyproject.toml <本任务实际修改的 Python 文件>`：All checks passed。
  - `cd frontend && npm run type-check`：通过。
  - 新增回归：Amap 无步行首末地铁段保留 Provider 上下车站、整段仍是 POI 起终点；Amap 缺站名不编造；Transitous 步行进出站保留上下车站；从 Provider 夹具经 candidate/leg、公开投影、`TransportLeg` 读回验证；删除两个新字段模拟旧 Bundle 可正常读取。
- 实屏证据：本任务不要求截图。用户可见站名交接给 `transport-display`：优先读取 `transport_legs[].boarding_stop` / `alighting_stop`，为 `null` 时不猜站名；主行站点可用它们，整段接驳仍用 `from_endpoint` / `to_endpoint`，换乘继续读 `transfer_count`。
- 遗留问题或需要指挥决定的事：前端 `transport-display` 的视觉消费不在本任务内；后端字段、缺失语义和旧 Bundle 兼容已就绪。

### 第 2 轮 · 2026-10-29 22:30 · pi / executor（审查修复）

- 改动摘要：
  - 修正 Amap 站点坐标转换顺序：`gcj02_to_wgs84` 返回的经纬度不再被反向赋给 `latitude` / `longitude`，Provider 站点可正常通过正式端点校验。
  - 收紧边界站点语义：只取第一条乘车段的上车站和最后一条乘车段的下车站；首段缺上车站或末段缺下车站时保留缺失，不再借用换乘站或前一段下车站。Amap 与 Transitous 归一化同步修正。
  - 交通候选替换时复制候选已承载的 `boarding_stop` / `alighting_stop`，避免 `SelectOptionMutation` 把正式行程段的站点事实清空。
  - 补充回归：站点坐标顺序、首末分段缺站、候选替换保留站点。
- 改动文件：
  - `backend/travel_agent/integrations/routes/amap.py`
  - `backend/travel_agent/integrations/routes/global_search.py`
  - `backend/travel_agent/planning/itinerary/mutations/transport.py`
  - `backend/tests/integrations/routes/test_amap_paths.py`
  - `backend/tests/integrations/routes/test_global_search_paths.py`
  - `backend/tests/planning/itinerary/test_connector_route_completion.py`
- 偏离方案及理由：无。只修复审查确认的站点事实问题，没有改动换乘计数、路线查询或几何语义。
- 实际运行的检查与结果：
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/integrations/routes/test_amap_paths.py backend/tests/integrations/routes/test_global_search_paths.py backend/tests/planning/itinerary/test_connector_route_completion.py backend/tests/planning/itinerary/test_revision.py -q`：64 passed。
  - 对实际修改的 Python 文件运行 `ruff check`：All checks passed。
- 实屏证据：本任务不要求截图；用户可见的混合交通展示由 `transport-display` 覆盖。
- 遗留问题或需要指挥决定的事：无。


### 第 3 轮 · 2026-10-29 · 主代理集成修复

- 改动摘要：Transitous 把 routeShortName 作为正式 line_name 的有效来源，班次号仍单独保留在 service_number。覆盖同 M1 线路不同 471／472 班次，以及 M1→M2 两条线路，避免前端被迫用班次猜线路。
- 改动文件：integrations/routes/global_search.py、tests/integrations/routes/test_global_search_paths.py。
- 偏离方案及理由：本轮复审发现线路事实保留不足，属同一 Provider 归一化责任方；未重定义通用 transfer_count。
- 实际运行的检查与结果：最终后端定向检查 83 passed；本轮 20 个新增／变化 Python 文件 ruff 全部通过，旧 Bundle 兼容与站点缺失语义保留。
- 实屏证据：前端混合线路与上下车站由 transport-display 最终截图覆盖。
- 遗留问题：Provider 不提供的站点／线路仍保持缺失，不编造。

## 8 指挥验收（指挥填写）

### 集成验收 · 2026-10-29

通过。首末实际乘坐段站点保真、缺站不借中间站、候选替换携带站点、坐标与旧 Bundle 兼容已核对；补充线路短名称归一化。最终 83 项后端定向测试及 20 文件 lint 通过。公开字段为已授权可选增量，无 SQL schema 改动。

本机服务已重启，8001 与 8080 就绪接口均 HTTP 200、status=ready。工作区既有改动保留，未提交、未推送。

## 9 真人验收（指挥代录）
