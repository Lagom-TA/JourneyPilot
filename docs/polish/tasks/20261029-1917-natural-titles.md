# 最终阶段由模型写自然短标题，统一工作台与报告消费

- 编号：20261029-1917-natural-titles
- 状态：待真人验收
- 创建：2026-10-29 19:17
- 执行前先读：[工作目录 README](../README.md)、[参考与文案示例](../references/20261029-itinerary-redesign.md)、backend/tests/README.md、docs/architecture/overview.md、docs/invariants.md、frontend/README.md、AGENTS.md

## 1 用户反馈

> 还有就是说我们这个标题啊，你起的实在太不自然了。我觉得你应该派在最后的时候啊，在我们给出行程的时候，要派一个模型来写一小段标题，就限制在比如说10个字到15个字，让他写一小段自然的话，别整这种非常公式刻板化的标题

- `output/polish/20261029-1917-natural-titles/feedback-1.png`：总标题“北京市＋上海市 5 日”；每日主题“东来顺饭庄（王府井店）· 转场与游览”等。
- `feedback-2.png`：单日主题重复以上机械拼接。

## 2 现象与发生条件

正式行程交付后的总标题与每天主题。用户要求在给出行程前，基于已经确定的实际内容增加模型撰写步骤，目标约 10–15 字、自然中文。标题与每日主题都应纳入，日期、城市、天数仍以独立元信息清楚展示。

## 3 根因

- `backend/travel_agent/planning/itinerary/day_themes.py:46` 起取最多两个景点／餐饮名称，`:73` 起按实体数量选择“转场与游览／游览与美食”等后缀；`:114` 拼成固定句式。这是确定性模板，不是最终模型的自然文案。
- `backend/travel_agent/planning/itinerary/materialize.py:577` 无条件使用 derive_day_theme，因此只改组合 prompt 也不会改变正式每日主题。
- `frontend/src/features/travel/components/workspace/DeliveryWorkspace.tsx:369` 优先用受控目的地和天数拼总标题，遮住正式 `itinerary.title`。
- `backend/travel_agent/planning/delivery/report_projection.py:625` 另行生成“目的地 N 日旅行计划”，因此即便更新 itinerary.title，阅读版／PDF 仍可能保留模板。
- 组合入口 `planning/itinerary/node.py:151` 起已有物化、路线补齐和 day design 完成边界；报告投影与原子封存属于下游。标题应在最终内容确定、正式投影前生成，不能放到前端 render、下载或数据库事务重试里调用模型。
- `planning/itinerary/mutations/derived_fields.py:9` 的局部变更派生重算只更新 highlights 与费用摘要，不更新 theme；不能假定新增一次最终润色就自动覆盖所有后续编辑入口。

## 4 方案

目标状态：同一份行程中的总标题和每日主题都是根据真实安排写出的自然短句。日期／城市／天数各自呈现，不再承担总标题；阅读版和 PDF 读取同一个正式标题。

必须做：

- 增加明确的最终文案撰写步骤，在完整日程与接驳确定后、报告投影与 Bundle 封存前，一次批量生成总标题及所有每日主题。用户已要求增加该模型调用；应走项目现有模型 router、Run 预算、deadline 与调用台账，不新增密钥／供应商配置，不绕过调用配额。
- 优先复用现有 itinerary.title 与 day.theme 字段。标题润色只可修改这些文案，不允许模型改日期、目的地、实体身份、顺序、站点、时长、费用或其他正式事实。
- 以 10–15 个中文有效字符为目标，允许自然标点；明确字数口径。用完整短句描述当天真实内容，禁用“地点 A 与地点 B · 游览与美食”这类分类后缀、通用“探索／邂逅／解锁／臻享”口号和每一天同一种套话。不为凑字数塞入无意义词，也不使用字符串截断。
- 同时覆盖纯交通日、餐饮／住宿为主、单地点、跨城日和最多 14 天。模型输出用稳定 day_id 对应，不按不可靠的输出顺序写回，不能少一天、重复一天或把主题串日。
- 标题请求只包含完成写作所需的真实日程摘要。把 Provider 名称、地点说明等当作数据，不把其中的指令文字执行为写作要求。
- 这是轻量文案步骤，失败、超时、预算不足、结构不合法或缺日时，不应把已完成可交付行程整体变成失败。保留可信的已有 title/theme，并记录真实调用结果；不无界重试，不自动放宽 Run 配额。正常成功路径必须实际使用模型结果，不能永远走模板兜底。
- 让工作台在正式 Bundle 存在时优先展示正式 itinerary.title；日期／城市／天数另行保持可查。阅读版标题和每日主题、PDF 读取同一份正式结果，不再各自套模板。检查其他正式标题消费者；会话名称是独立既有语义，不为改行程标题改写所有历史会话。
- 标题随本次正式 Workspace／Bundle 保存，刷新、阅读／PDF、断线恢复与重试不重新生成。交付投影／持久化重试不能重复调用；天气刷新或单纯下载不触发模型。
- 用户要求调整并形成新行程时，新标题应基于新内容，在既有重新组合边界生成。对直接局部 mutation 等未经过模型组合的入口核实策略：不得在数据库事务或普通投影里偷偷调用模型，不能无证据宣称已覆盖全部入口。保留标题或同步内容的规则在执行记录说明。
- 若确需新增内部 task kind 或运行图节点，同步现有节点元数据与定向检查；优先复用合理的现有组合／摘要阶段，避免仅为一次文案调用增加完整 Agent 子系统。

执行者自己决定：现有 router 的合理模型档位、提示词、内部结构、调用位置、是否需要有上限的结构修复与校验细节。参考 `humanizer-zh` 原则写自然中文；文案示例见参考文档第 4 节，不能硬编码示例为生产标题。

不许碰：旅行实际安排、受控身份、价格／预算业务、模型配额上限、真实历史数据、数据库 schema、无关 API/SSE 和前端页面。不调用真实付费模型验证，除非用户另行要求真实端到端生成；本任务的产品调用实现已授权，测试使用外部模型边界替身。不提交不推送，保留既有工作区改动。

依赖与所有权：后端可独立推进；DeliveryWorkspace 等前端消费改动在 `workspace-visual` 完成后串行接入，不与视觉执行者同时改同一文件。API 字段沿用 title/theme，无需另造展示标题契约。

## 5 停下来报告的情况

若现有预算窗口完全无法容纳一次短文案调用，记录实际限制与降级结果；不能擅自增预算。若必须破坏 Bundle 版本合同或重命名持久化字段才能实现，先提供具体原因。正常接入现有模型 router、复用 title/theme 与调整前端消费在本任务范围内，不属于需再次批准的情况。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 成功路径在最终内容确定后批量调用模型，总标题与每一天主题写回正式结果，按 day_id 正确映射；没有随后又被旧模板覆盖。
2. 输出目标 10–15 字且自然完整，超长不截断；正常例子不再是“地点＋类别后缀”。自然程度由指挥看样例、用户看真实行程验收，不能靠关键词测试假装证明。
3. 仅文案字段变化，事实与实体标识不变。模型失败／缺日／预算不足不毁掉有效行程，重试有界。
4. 工作台、阅读版和 PDF 的总标题／每日主题一致；刷新、恢复、投影重试与下载无额外模型调用。
5. 使用现有预算、deadline、费用台账与模型配置。若新增运行节点则元数据覆盖正确；未增加节点不制造无消费者注册。

### 6.2 必须运行的检查

仓库根目录：

- 新增少量最终文案行为回归（建议 `backend/tests/planning/itinerary/test_title_writing.py`，执行者可选更合适的既有用例位置），覆盖成功写回／day_id 映射／事实不变、失败保留／预算拒绝、重复投影无额外调用。模型作为外部边界替身，内部用真实模型结构与投影链。
- `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/planning/itinerary/test_title_writing.py backend/tests/planning/itinerary/test_revision.py backend/tests/planning/delivery/test_pdf_export.py -q`；若选择其他测试路径，记录并运行实际等价命令。
- 对实际修改的 Python 文件运行 `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend ruff check --config backend/pyproject.toml <实际改动文件>`，记录完整命令。
- 若新增／修改运行图节点，再运行 `backend/tests/planning/test_node_presentation.py`；无该变化不重复扩大范围。

在 `frontend/` 下：

- `npm run type-check`
- `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'reading and map|desktop itinerary' --workers=1`

用正式形状离线 Bundle 的自然标题验证 UI 不被 identityTitle 覆盖；阅读／PDF 的同源由后端真实投影断言支撑。不要写完整 prompt 的字符串快照，不在这轮调用真实付费模型。

### 6.3 实屏证据（执行者提供）

同一 5 天离线 Bundle 的工作台总标题、单日主题、阅读版标题和 PDF 首页；附实际标题列表与字数口径。截图能证明呈现与一致性，测试替身样例不能作为真实模型文案质量已验收的证据。真实生成质量待用户后续生成时验收。

### 6.4 真人验收（用户操作）

1. 下次生成完整行程 → 总标题和每日主题用约 10–15 字自然中文描述实际安排，不再出现机械分类后缀。
2. 打开某天、阅读版、PDF，再刷新工作台 → 标题一致，没有每次打开都换名字。
3. 调整行程并完成新一版 → 主题跟得上新安排，日期、地点、交通等事实不被标题润色改动。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 21:45 · pi / executor

- 改动摘要：
  - 新增正式文案步骤 `write_itinerary_copy`：在每日路线、接驳和 day design 确定后、正式投影前，一次批量请求总标题和全部每日主题；按稳定 `day_id` 写回，只改 `itinerary.title` 与 `day_plans[].theme`。
  - 复用现有 router 的 `TaskKind.SUMMARY` 快模型档位、Run 预算、deadline 和调用台账；没有新增 task kind、节点、密钥或供应商配置。
  - 失败、超时、预算拒绝或结构缺日时保留已有 title/theme；结构问题最多修复一次，预算拒绝不重试。成功路径使用模型结果，不永久走模板。
  - 报告投影标题改为读取正式 `itinerary.title`，PDF 与阅读版读取同一份报告文档；工作台在正式 Bundle 存在时优先显示 `itinerary.title`，日期/城市/天数放到紧邻的元信息行。
  - 局部 mutation 的规则：正式文案是组合阶段生成的快照，事务内不调用模型也不伪装刷新；局部 mutation 保留原文案，下一次完整重新组合基于新内容重新生成。已在 `mutations/derived_fields.py` 写明并由用例固定。
- 改动文件：
  - `backend/travel_agent/planning/itinerary/title_writing.py`（新增）
  - `backend/travel_agent/planning/itinerary/node.py`
  - `backend/travel_agent/planning/delivery/report_projection.py`
  - `backend/travel_agent/planning/itinerary/mutations/derived_fields.py`
  - `frontend/src/features/travel/components/workspace/DeliveryWorkspace.tsx`
  - `frontend/e2e/session-state.spec.ts`
  - `backend/tests/planning/itinerary/test_title_writing.py`（新增）
  - `backend/tests/planning/itinerary/test_revision.py`
- 偏离方案及理由：没有新增运行节点或 `TaskKind`，复用 `SUMMARY` 作为轻量文案档位。`test_revision.py` 增加 autouse 替身跳过文案步骤，使既有“接驳选择不调用模型”用例仍只验证原意图；最终文案由 `test_title_writing.py` 单独覆盖。
- 实际运行的检查与结果：
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/planning/itinerary/test_title_writing.py backend/tests/planning/itinerary/test_revision.py backend/tests/planning/delivery/test_pdf_export.py -q`：44 passed。
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/planning/delivery -q`：9 passed。
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend ruff check --config backend/pyproject.toml <本任务实际修改的 Python 文件>`：All checks passed。
  - `cd frontend && npm run type-check`：通过。
  - `cd frontend && JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'reading and map|desktop itinerary' --workers=1`：2 passed。
  - 用例覆盖成功写回与 day_id 映射、事实字段不变、失败保留且有界重试、预算拒绝不重试、缺日一次修复、重复公开投影不追加模型调用、局部 mutation 保留文案、报告标题与每日主题同源。
- 实屏证据：`output/polish/20261029-1917-natural-titles/workbench.png`、`reading.png`、`report.pdf`、`report-page-1.png`。使用正式形状的 5 天离线 Bundle，只替换文案字段，不写产品数据。
  - 总标题：`北京上海五日文化慢行记`（11 个有效字符）。
  - 每日主题：`到北京先吃顿东来顺火锅`（11）、`从故宫慢慢走到景山看落日`（12）、`在颐和园慢慢逛上大半天`（11）、`去天坛古树下听一听风声`（11）、`上海博物馆看完再去豫园`（11）。
  - 字数口径：去掉空白和标点后的字符数；允许自然标点。截图中的文案是隔离夹具，只证明工作台/阅读版/PDF 同源和标题优先级，不作为真实模型文案质量已验收的证据。
- 遗留问题或需要指挥决定的事：真实生成质量需用户下次完整生成时验收；未调用真实付费模型。局部 mutation 采用“保留文案、完整重组再生成”的明确策略，未在事务内或投影重试中偷偷调用模型。

### 第 2 轮 · 2026-10-29 22:30 · pi / executor（审查修复）

- 改动摘要：
  - 文案结构校验改为严格要求字符串：对象标题、数组主题、非字符串 `day_id` 不再被 `str()` 强制写入正式文案。
  - 增加有效字数校验：总标题与每日主题按去空白、标点后的字符数必须在 10–15 之间；超长不截断，而是触发一次有界结构修复，仍不合法时保留原有 title/theme。
  - 修复提示和系统提示同步说明字符串与有效字数要求；补充非法结构、过短、过长输入保留旧文案的回归。
- 改动文件：
  - `backend/travel_agent/planning/itinerary/title_writing.py`
  - `backend/tests/planning/itinerary/test_title_writing.py`
- 偏离方案及理由：把“10–15 字为目标”落为明确的有效字数校验，避免任意对象或极端长短文案进入正式标题；仍保留自然标点，不截断用户可见文案。
- 实际运行的检查与结果：
  - `UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project backend pytest -c backend/pyproject.toml backend/tests/planning/itinerary/test_title_writing.py backend/tests/planning/itinerary/test_revision.py backend/tests/planning/delivery/test_pdf_export.py -q`：48 passed。
  - 对实际修改的 Python 文件运行 `ruff check`：All checks passed。
  - `cd frontend && npm run type-check`：通过。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'reading and map|desktop itinerary' --workers=1`：包含在最终 8 passed 运行中，通过。
- 实屏证据：沿用第 1 轮 `output/polish/20261029-1917-natural-titles/` 下的工作台、阅读版与 PDF 截图；本轮只收紧后端校验，没有改动标题呈现或夹具文案。
- 遗留问题或需要指挥决定的事：真实模型文案质量仍待用户下次完整生成时验收。


### 第 3 轮 · 2026-10-29 · 主代理集成修复

- 改动摘要：将提示词示例改为符合 10–15 有效字数的自然句子；标题步骤与节点显式透传 RunCancelled，用户取消不再被吞为文案失败或重试。增加关闭 composition 窗口时保留旧文案且不重试，以及取消一次后透传的回归。阅读版封面标题增加平衡换行，减少单字孤行。
- 改动文件：itinerary/title_writing.py、itinerary/node.py、tests/planning/itinerary/test_title_writing.py、frontend/src/index.css。
- 偏离方案及理由：文案失败允许降级，运行取消属于控制信号，必须保留；排版调整直接服务短标题阅读。
- 实际运行的检查与结果：最终后端定向测试 83 passed（包含标题、Provider、正式交付与变更）；前端类型检查及最终构建通过，阅读版往返回归通过。未调用真实付费模型。
- 实屏证据：output/polish/20261029-1917-batch/final-overview-2000.png、final-day-2000.png、final-reading-2000.png；同一份 5 天正式形状离线 Bundle，文案为示例，只证明同源呈现。PDF 正式投影由后端用例和前两轮证据支撑。
- 遗留问题：真实模型文案质量待真人下一次完整生成验收；局部 mutation 保留已有文案，完整重新组合再生成。不会批量重写历史行程。

## 8 指挥验收（指挥填写）

### 集成验收 · 2026-10-29

通过代码验收。已核对最终物化后批量写入、day_id 映射、有效字数与类型、预算／时限降级、取消透传、工作台／报告／PDF 同源及投影重试无模型调用。采用 SUMMARY 档合理。真实模型文案自然度未以离线夹具冒充验收；局部 mutation 保留文案的策略接受，完整组合时重写。

本机服务已重启，8001 与 8080 就绪接口均 HTTP 200、status=ready。工作区既有改动保留，未提交、未推送。

## 9 真人验收（指挥代录）
