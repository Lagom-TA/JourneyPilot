# 05：围绕完整行程精简交付，并统一地图与可靠保存

- 编号：20261101-0035-generation-05-concise-delivery
- 状态：待代码验收
- 创建：2026-11-01 00:35
- 顺序：第 5 项，依赖 [04](20261101-0035-generation-04-composition-feedback.md) 代码验收通过
- 执行前先读：[本批总览](../discussions/20261031-generation-chain/README.md)、[工作目录 README](../README.md)、`AGENTS.md`、`frontend/README.md`、`backend/tests/README.md`、`frontend/e2e/README.md`

## 1 用户反馈

> 缺口其实是我们的行程当中出现空缺，而不是行程的辅助信息当中有空缺。

> 有价格就有，没有就没有，就算了。

最终只需清楚的地点、顺序、时间与必要衔接。推荐理由简短且只出现一份，不展开选点过程、偏好匹配解释或景点内部怎么玩。研究资料可以丰富，最终展示保持精简。

## 2 现象与发生条件

报告投影可能把同一推荐理由同时写到 summary 和 details，还生产缺失价格等提醒；前端再用规则隐藏部分文字，PDF 另有展示逻辑。组合中的定位失败可能直接替换地点，地图略过无坐标项。保存完成的机制已有基础，但需要在新的方案数据上保持真实可读取的交付。

## 3 根因

- `backend/travel_agent/planning/delivery/report_projection.py:355`、`:384`、`:448`：重复理由、解释与未知费用提醒的生产。
- `frontend/src/features/travel/components/workspace/FullReportView.tsx:31`、`:168`：后置隐藏与附加说明。
- `backend/travel_agent/planning/delivery/pdf_export.py:330`：PDF 分别读取多种文案。
- `backend/travel_agent/planning/itinerary/composition.py:80`、`itinerary/locations.py:209`：组合内定位和自动替换。
- `backend/travel_agent/planning/delivery/map_projection.py:68`：无坐标地点被略过。
- `backend/travel_agent/planning/delivery/persistence.py:86`：已有同事务提交、读回与完成保证。
- `backend/travel_agent/planning/delivery/assembly.py:63`：初始哈希与后续天气建议的组装顺序需随最终结果核对。

## 4 方案

目标状态：交付主体是连贯行程，辅助资料可选，日程、地图、阅读版和 PDF 来自同一份可保存、可重新打开的结果。

必须做：

1. 组合按当前需求判断实际安排是否落实、前后是否衔接。自由时间与休息属于正常安排；未安排的必要内容由组合补查或反馈返研。无独立评分、逐条核销或额外审批。
2. 精简组合文案、投影源和全部视图。推荐理由至多一份简短表达；删除重复选点理由、偏好匹配和内部取舍解释，不写景点内部详细游玩攻略。用户主动提问时另行回答。
3. 价格、详细介绍等辅助信息有就用，没有直接省略。不强制补齐、不占位、不生成缺失提醒、不自动触发补查或返研。时间信息按安排需要表达，实际交通成本仍用于衔接。
4. 在方案确定后统一准备入选地点与路线的地图数据，复用研究和补查所得。不能只因坐标查询失败就偷偷换掉选定地点；保留有用日程项，已有地图内容继续可用。明显影响实际安排的差异交回组合调整，辅助展示缺项不把整份内容判为失败。
5. 日程、报告、地图与 PDF 从同一结果生成，避免重复改写同一方案和依靠正则过滤掩盖上游文案。可选字段在数据与展示层都可省略。
6. 保持交付提交、读回、Run 完成和事件的一致性。参与哈希和存储的内容先完整组装，读回应能通过真实存储校验；长过程或返研后也能读取正确完成事件。只修直接影响本批交付的缺陷，不扩展为运行系统重构。
7. 返研仍无法补齐行程时保留有效成果，说明实际未安排的部分；页面不标作完整方案。保存或读取失败与内容问题分别准确处理，不能把成功落盘的结果改成失败。

执行者自己决定：最终行程字段、时间粒度、简短理由位置、地图准备节点组织和缺坐标项的低噪声呈现。现有报告与交付类型可按目标简化，必要字段变化在范围内。

不许碰：无关页面、地图交互既有有效行为与视觉素材、真实用户数据、私有配置。保留版本、可靠保存和实际费用计量。

## 5 停下来报告的情况

需要删除用户已有旅行或破坏现有持久化内容时报告。普通投影字段改写、地图准备位置调整、旧测试清理及直接交付缺陷修复已授权。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 行程安排清楚，简短推荐理由不重复，不出现攻略长文和内部选点解释。
2. 缺价格与介绍仍能交付，不生产占位或缺失提示。
3. 地图对应选定安排，定位失败不静默替换地点，衔接信息影响日程。
4. 所有视图使用同一结果，提交与读回成功后才显示完成，刷新可恢复。

### 6.2 必须运行的检查

- `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning/delivery/test_map_projection.py backend/tests/planning/delivery/test_cost_presentation.py backend/tests/planning/delivery/test_pdf_export.py backend/tests/planning/test_workflow_boundaries.py -q`
- 新增或合并隔离 PostgreSQL 的定向交付检查到 `backend/tests/db/test_generation_delivery.py`：`JP_TESTS_REQUIRE_POSTGRES=1 .venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/db/test_generation_delivery.py -q`。覆盖完整 Bundle（含非空天气建议）组装、真实提交后重新读回与内容哈希校验，以及长过程完成事件的读取恢复；使用随机测试库，不访问用户已有旅行。
- `npm --prefix frontend run type-check`
- `npm --prefix frontend run test -- src/features/travel/model/mapModel.test.ts src/features/travel/model/costPresentation.test.ts`
- 本地前端启动后，在 `frontend/` 执行：`JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 npx playwright test e2e/session-state.spec.ts --workers=1 --output=../output/polish/20261101-0035-generation-05-concise-delivery/playwright`。

使用缺价格、单份理由、个别无坐标的代表场景。真实数据库事务检查使用隔离测试库；未运行不得记为通过。删除仅保护重复文案或定位失败自动替换的旧断言。

### 6.3 实屏证据（执行者提供）

保存同一虚构方案的桌面行程、阅读版及手机地图，覆盖无价格场景；检查重复理由、长解释和缺失占位。导出一份相同数据 PDF，按适用技能检查真实渲染。证据位于本任务 `output/polish/`。

### 6.4 真人验收（用户操作）

1. 打开一份生成结果 → 日程清楚，推荐理由简短、没有反复解释。
2. 查看阅读版、地图并导出 PDF → 内容一致，缺辅助资料不影响使用。
3. 刷新重新打开 → 保存结果仍在，界面保持一致。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-11-01 22:37 · ZCode／GPT-6.1-terra（DeepSeek 工作流信息收集，Grok 4.7 代码验收）

- 改动摘要：组合先确定地点，再集中准备定位与路线；移除定位失败时替换地点的逻辑，无坐标地点留在日程和地图投影。精简组合提示、条目投影、阅读版和 PDF；缺价直接省略，理由只展示一份。将实际未安排事项随行程保存并在日程、阅读版和 PDF 展示。天气建议生成后重新计算 Bundle 哈希，允许首轮天气版本 0；长流程通过正式交付事件接口恢复终态。同步交付及工作台合同版本。
- 改动文件：`backend/travel_agent/planning/{delivery, itinerary, weather, costs}` 相关模块、`conversation/chat/delivery.py`；`backend/tests/db/test_generation_delivery.py` 和相应定向测试；`frontend/src/features/travel/`、`frontend/src/app/session/` 对应组件、模型与合同，`frontend/e2e/session-state.spec.ts` 及夹具。完整文件以 Git 差异为准。
- 偏离方案及理由：无。第 04 项文档仍为“待代码验收”；Grok 已只读核对，未发现阻塞本项的代码问题，未修改第 04 项文档。
- 实际运行的检查与结果：后端 6.2 定向检查 19 passed；隔离 PostgreSQL 检查 1 passed（天气建议、提交后重新读回、500 条以上事件恢复及 PDF）；前端 type-check 通过；地图、费用与合同版本 vitest 23 passed；组合地点与返研测试 41 passed；离线浏览器套件 46 passed、10 failed。新增场景污染共享夹具导致的地图失败已修正，新增场景与原地图测试单独复测 2 passed；其余 9 项在隔离的原始提交 `4a74b8a` 上全部复现失败，涉及会话切换、取消和旧方案确认断言。
- 实屏证据：`output/polish/20261101-0035-generation-05-concise-delivery/` 中的桌面日程、桌面阅读版、手机地图和 `concise-fixture.pdf`；相同虚构数据见 `fixture-bundle.json`。PDF 两页已渲染检查；自动 PDF 质量脚本因缺少 PyMuPDF 未运行。
- 遗留问题或需要指挥决定的事：离线浏览器套件 9 项既有失败仍需后续处理。

### 第 2 轮 · 2026-11-01 23:42 · ZCode／GPT-6.1-terra（按 Grok 4.7 代码验收返工）

- 改动摘要：统一返研上限后的组合提示，明确要求将仍无法安排的事项逐条写入对应日期的 `day_design.unresolved`，避免只写入不会进入交付的 `rationale`。
- 改动文件：`backend/travel_agent/planning/itinerary/prompts.py`、`backend/tests/planning/itinerary/test_research_feedback.py`。
- 偏离方案及理由：无。
- 实际运行的检查与结果：返研行为测试 10 passed；相关 Python 静态检查与 `git diff --check` 通过。测试确认返研后的提示携带正确字段，且未安排事项保留到行程。
- 实屏证据：沿用第 1 轮证据。
- 遗留问题或需要指挥决定的事：离线浏览器套件 9 项既有失败仍需后续处理；真实付费模型联调留待本批统一验收。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
