# 第一站与出发地相同时，不生成同端点长途段并允许继续规划

- 编号：20261029-1439-origin-first-leg
- 状态：待真人验收
- 创建：2026-10-29 14:39
- 执行前先读：[工作目录 README](../README.md)、AGENTS.md、README.zh-CN.md、docs/architecture/overview.md、docs/invariants.md、backend/tests/README.md

## 1 用户反馈

> 还有就是为什么我们没有办法进行规划？是不是后端有问题？

截图：`output/polish/20261029-1439-origin-first-leg/feedback-1.png`。旅行摘要：深圳市出发，目的地深圳市、北京市，2026-10-29 至 2026-11-03，2 位成人。红条“旅行方案暂时无法生成，请稍后重试。”；过程区“调研已停止”，仅需求整理阶段已结束。

同批关联返工：`20261029-1252-generation-layout` 负责过程卡删重与终态文案，`20261029-1252-inline-intake` 负责页面交接；本任务独立修复实际规划失败。

## 2 现象与发生条件

受控旅行身份合法且第一站的 `place_id` 与出发地一致，后面还有其他目的地，例如深圳出发依次游览深圳、北京。需求归一化完成后，`research_brief_builder` 在构造长途交通段时抛验证错误；尚未进入计划审批和实际交通查询。

本地 `/tmp/journeypilot_logs/backend.log` 在 2026-10-29 14:27:57 记录该错误。14:30:07 后 API 正常退出，调查时 8001/8080 已不监听；当前服务未运行与截图中先前的业务失败应区分。无需通过重启解释或掩盖代码错误。

## 3 根因

- `backend/travel_agent/planning/requirements/identity_contracts.py:83–118` 允许出发地出现在目的地中；目的地之间仍须不同。这支持本地游览作为第一站，不能在前端临时禁止来规避后端错误。
- `planning/requirements/route_legs.py:63–64` 仅在首尾目的地都等于出发地时直接返回；`:92–100` 对其他情况无条件构造 `origin → destinations[0]`。首站为出发地但末站不是时，会构造同端点 outbound。
- `planning/research/provider_contracts.py:48–61` 正确要求长途段两端不同，所以抛出 `Provider route leg requires distinct endpoints`。该守卫不应放宽。
- `planning/research/brief_builder.py:64–67` 调用同一交通段构建函数判断是否需要长途调研，异常直接从 `brief_node.py:15` 传播至聊天失败处理，前端显示通用失败页。日志 `backend.log:117` 同轮模型调用为 `status=ok`；`:119–159` 的栈与上述代码完全一致，没有证据将本次失败归因于模型、数据库或外部交通服务。
- 该构建函数还被 `research/plan.py`、`itinerary/day_capacity.py`、`itinerary/prompts.py` 和 `delivery/report_projection.py` 消费，应在唯一交通段构建责任方修复，避免调用方各自过滤。

指挥已用合成 `PlaceIdentity` 在 `.venv/bin/python` 离线复现：四种输入都通过 `ControlledTripIdentity`；`origin=深圳，destinations=[深圳,北京]` 抛上述错误，`[北京,深圳]` 返回有效 outbound/inter_destination，`[深圳]` 无长途段，`[北京]` 返回普通 outbound/return。未调用模型、未连接或写入真实会话。

补充边界：同名但 `place_id` 不同的地点当前按不同端点处理，本轮保持该规则。另查到 `[北京,深圳]` 的返回出发地边当前是 inter_destination，`cross_day_return_required` 不会传给该边；这是现有角色/跨日语义缺口，独立于首站同端点异常。本轮保持既有角色，不顺手修复这个独立问题，也不宣称已经覆盖它。

## 4 方案

目标状态：在出发地先游览再去外地的多目的地规划可以正常生成调研简报和计划；不为相同身份的相邻地点研究长途交通，也不丢弃任何已选游览目的地。

必须做：

- 修正唯一长途段推导，使每个实际生成段都有不同的 `from_place_id/to_place_id`。以受控 `place_id` 判断相等，不按名称、坐标或模糊“同城”推断合并地点。
- 保留已选目的地、访问顺序与既有停留天数分配；深圳作为首站仍保留其游览日期。例中深圳/北京各分配三天时，实际离开深圳去北京的跨城边界应落在北京首个停留日 2026-11-01，不能因省掉空交通段而提前到第一天。
- 保留仍然必要的跨城和返程职责与对应服务日期。`[深圳,北京]` 中真实 A→B 边保持 inter_destination、服务日 11-01，独立 B→A return 边保持 11-03 及其 `cross_day_return_required` 标记；`[北京,深圳]` 保持现有 outbound/inter_destination 访问链，不额外创建零距离 return。本地单站与普通单站往返同样保留既有语义；不能因首站是本地而跳过全部交通研究。
- 在业务投影链验证：合法身份可以构建真实 `ResearchBriefV2`，并经现有 planner/transport scope 机制得到有效交通职责；不要只给低层函数加一条不抛异常断言。
- 保留 `ProviderRouteLegScope` 两端不同的合同、不改变公开 API/SSE/持久化结构，也不吞掉无关 `ValidationError` 或返回空计划假装成功。

执行者自己决定：边的遍历/跳过方式与定向用例组织。维持当前跨站职责角色含义，不因本次零距离边修复重新解释返程；若现有角色无法安全表达首站修复，报告后再决定，不引入第二套交通段来源。

不许碰：受控地点合法性、五站/十四天规则、用户目的地身份、预算与截止时间、计划门审批、前端展示、真实数据、付费服务和无关工作区改动。不提交不推送。

## 5 停下来报告的情况

若修复必须改变交通职责角色的公开/持久化合同、重新分配目的地停留天数，或依赖同名地点/不同 provider 的隐式合并，先报告。若实际运行身份并非首站与出发地同一 `place_id`，需重新定位，不能扩大成模糊地点去重。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 合法的“深圳出发，深圳 → 北京，六日”可通过简报和规划职责投影，不抛同端点异常；深圳仍是第一站，跨城边界日期保持 11 月 1 日，末站北京返回深圳的实际职责保留。
2. 本地单站无长途段，普通异地单站仍有 outbound/return，末站即出发地不再重复增加返程；所有生成段两端不同。
3. 现有交通段消费者使用同一修复结果；Provider 合同未放宽，身份/日期/预算/审批真值未改变。

### 6.2 必须运行的检查

在仓库根目录运行：

- `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/planning/requirements/test_control_plane.py -q -k 'transport_scopes or same_city or origin_first'`
- `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend ruff check backend/travel_agent/planning/requirements/route_legs.py backend/tests/planning/requirements/test_control_plane.py`

在现有 control-plane 业务用例中补充首站等于出发地的多站输入（命名包含 `origin_first` 或按实际测试名调整命令），经真实简报/计划/transport scope 构造断言边、服务日期与游览身份。保留已有同城与异地业务回归；若实现触及额外消费者，再补该责任方的最小定向检查。按 `backend/tests/README.md` 只在真正外部边界使用替身，不 mock 内部投影链，不调用真实模型或写真实用户数据。

### 6.3 实屏证据（执行者提供）

本轮后端修复不强制请求真实付费规划。需提供离线业务链的可核对职责与日期结果，明确验证范围：到达有效计划不代表已经验证完整外部调研与交付。若同时验证浏览器，使用本地合成事件，不把夹具成功描述为真实服务成功。

### 6.4 真人验收（用户操作）

1. 在正常运行的服务中选择深圳出发，依次选择深圳、北京，六日，确认开始 → 不再在需求整理后因同端点交通段直接失败，能继续到计划确认。
2. 按现有计划门确认调研 → 使用正常规划流程观察后续阶段；若出现其他上游错误，按具体新错误记录，不能将其视作本次同端点问题复现。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 14:51 · Codex

- 改动摘要：在唯一长途段推导处跳过首站与出发地相同产生的同端点 outbound，保留其余跨城与返程职责、角色和既有停留天数分配；补充经真实 `ResearchBriefV2`、planner transport scope 与 day shell 投影的业务链用例。
- 改动文件：`backend/travel_agent/planning/requirements/route_legs.py`；`backend/tests/planning/requirements/test_control_plane.py`（只新增 `origin_first` 用例，保留该文件原有改动）；本任务文档状态行与本节执行记录。
- 偏离方案及理由：无。
- 实际运行的检查与结果：
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/planning/requirements/test_control_plane.py -q -k 'transport_scopes or same_city or origin_first'`：7 passed，37 deselected。
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend ruff check backend/travel_agent/planning/requirements/route_legs.py backend/tests/planning/requirements/test_control_plane.py`：All checks passed。
  - 额外回归：同一测试文件全量 `44 passed`（0.49s）。
  - 修复前合成复现：`[深圳,北京]` 抛 `Provider route leg requires distinct endpoints`；修复后同一输入得到 `inter_destination 深圳→北京 2026-11-01` 与 `return 北京→深圳 2026-11-03`，所有段两端不同。
  - 离线业务链脚本核对：`ResearchBriefV2` 成功构建，planner 产出对应 transport scopes；`[深圳,北京]` 的 day shell 为深圳 10-29～10-31、北京 11-01～11-03，返程 `cross_day_required=True`；`[北京,深圳]` 保持 `outbound 10-29` + `inter_destination 11-01`，无额外 return。
- 实屏证据：`output/polish/20261029-1439-origin-first-leg/repro-before.log`、`repro-after.log`、`pytest-targeted.log`、`pytest-control-plane.log`、`ruff.log`、`offline-business-chain.log`（脚本为 `offline-business-chain.py`）。本轮只验证离线业务链的职责与日期，不代表已验证完整外部调研、真实 Provider 调用或交付；未调用真实付费模型、未连接或写入真实会话。
- 遗留问题或需要指挥决定的事：无。按任务要求保留 `[北京,深圳]` 既有的 inter_destination 返程角色/跨日语义，不扩展处理；未启动真实规划或浏览器验收。

## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-29 · 指挥

- 结论：通过，转待真人验收。
- 已对照 `output/polish/execution-baseline-20261029-144803` 核对本轮差异：唯一交通段推导只省略同端点 outbound，前序身份、需求归一化等工作区改动未混入本轮结论；Provider 两端不同守卫保持原样。
- 日期、角色与业务链通过：首站深圳的三天停留保留，深圳→北京 inter_destination 为 11-01，北京→深圳 return 为 11-03 并保留显式跨日标记；末站即出发地保留原角色且无额外同端点段。
- 独立审查与指挥均抽查规定 pytest 选择；指挥实际运行 `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/planning/requirements/test_control_plane.py -q -k 'transport_scopes or same_city or origin_first'`，7 passed、37 deselected。执行者 ruff 与全文件 44 项检查记录已核对。
- 验证范围：离线真实简报/plan/transport scope/day shell 投影；没有将其描述为真实外部调研或完整交付成功。真人步骤见第 6.4 节，待同批前端返工后一起交付体验。

## 9 真人验收（指挥代录）
