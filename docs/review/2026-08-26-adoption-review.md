# 对照吸收审查：JourneyPilot 该从 codex 与 openpi 学什么

日期：2026-08-26。代码基线：`main @ 5524f388`。
参照仓库：codex（`~/Code/codex-main`，与上一轮审查所用 `~/Downloads` 副本同版本，Cargo.toml 与 CHANGELOG 逐字节一致）；openpi（`~/Code/openpi`）。
除注明外，JourneyPilot 的 `file:line` 相对 `src/travel_agent/`，为本轮审查当日实际所见。

---

## 1. 这份报告回答什么

一个问题：对照 codex 与 openpi 的工程实践，JourneyPilot 的 Agent 构建在代码工程上应该吸收什么。

边界先说死。本轮只做代码工程优化，不改行为链里 Agent 的既定行为——路由结果、门的裁决、模型调用、任何运行时语义都不能变；允许的是类型化、模块搬移、表迁配置、加测试、加观测。上一轮报告（`2026-08-26-agent-architecture-review.md`）第七节的八组观察是本轮的锚，第八节的缺陷清单只作背书引用，不重复开票。`docs/design/comparative-study.md` §4.4 已定案的四条 `last_error` 协议缺陷同样不重证，本文只给能接住它们的方案。

建议分三档。必做：不做会持续产生新缺陷，或有 F-xx 缺陷背书且成本可控。值得做：收益明确，可排期。不做：参照仓库有、但对本仓形态（单机单进程 asyncio + LangGraph 状态图、单次 Run 墙钟封存、四道确定性门）不成立，理由写足——"不做"是一等产出，不是凑数。

### 1.1 基线在审查期间动了

上一轮报告锚定 `5fbb2b29`。本轮审查进行中，两个 commit 落了主干：`510d5236` 新建 `workflows/node_names.py`——49 行、零仓内依赖的节点名真源，22 个节点名常量加 `WORKER_NODES`、`RESEARCH_WORKER_NODES`、`CHECKPOINT_GATE_NODES`，`travel_planning.py:66-92` 改为逐个 re-export，`run_control.py:26-29`、`candidate_gate.py:82`、`artifact_gate.py:30` 改 import 真源；`5524f388` 把 `chat.py:46` 与 `chat_stream_handlers` 里的 `_CHECKPOINT_GATE_NODES` 死副本也换成真源 import。

后果有三条。上一轮的 F-12（`_RESEARCH_WORKERS` 两份定义）与 F-16（`_CHECKPOINT_GATE_NODES` 死副本）已消。`travel_planning.py` 的 plan_gate 区块从 `:327-448` 位移到 `:324-445`。最值得记的是第三条：本仓自己走通了"协议真源提成零依赖叶子模块"这条路，判据写在 `node_names.py:1-8` 的 docstring 里（下游反向 import 会成环，所以这张表独立成叶子）。本文 2.1 的头号建议就是把同一手法用到第二张表上——路径可行性不再需要论证。副作用也有一条：既有守卫测试的一条断言因此退化成同源互测，见 4.1。

### 1.2 方法与证据强度

三段流水线。12 个读码代理（sonnet 1M 上下文）分维度定点读三个仓库，笔记落 `tmp/review2/`（12 份，gitignored）；5 个分析代理（Opus）按维度组产出吸收建议，每组附承重断言清单；5 个核实代理（Opus）逐条把断言带回源码对抗核查，另抽查正文引用、逐条审查建议是否越过"不改行为"的约束。

核实的账面：56 条承重断言，31 条 CONFIRMED、25 条 CORRECTED、零 REFUTED。全部修正已吸入本文正文——凡与分析底稿冲突处，以核实后的事实为准。分析与核实阶段做过三类现场实验（LangGraph 语义实验、pytest 实跑、ruff 规则实验），正文标"实测"；实验的临时改动均已还原。核实还点名了一批"看似纯工程、实为行为或对外可见变更"的建议，正文对这些逐条加【行为标注】——它们仍可能值得做，但必须按行为变更立项，不许搭纯搬移的车。

维度覆盖：上一轮第七节的八组（模块切分、协议类型化、状态所有权、配置声明化、工具治理、prompt 管理、测试钉法、编排与台账），加本轮新开的四组（Agent 主循环与调度、错误分类与恢复链、可观测性、测试组织）。章节安排：第 2 章结构与协议，第 3 章配置、工具与 prompt，第 4 章测试，第 5 章主循环、编排与台账，第 6 章错误与可观测性，第 7 章三档汇总与动手顺序，第 8 章方法与勘误。

---

## 2. 模块切分、协议类型化、状态所有权

### 2.1 A-1｜失败协议的前缀与词表提成零依赖叶子模块（必做）

**我们的观察。** 失败协议的依赖方向是写方 → 读方。`agents/worker_errors.py:13-16` 写着 `from .orchestrator.provider_failure import _DETERMINISTIC_MARKERS, _TRANSIENT_MARKERS`，`:17` 紧接着还 import `research_packet_output`——而 `research_packet_output.py:65` 又反过来 import `provider_failure`，除了写读两方的 2-环，还有一个 3-环候着。读方导不进写方的常量，后果全在明面上：六个前缀常量定义在写方（`worker_errors.py:19-24`，`_KNOWN_PREFIXES` 在 `:26-33`），`provider_failure.py:89-93` 把其中五个重敲成字面量，`classify_provider_failure` 的分支条件（`:116/:126/:131/:136/:146`）再敲一遍。更糟的一份证据是 `_QUERY_MISS_MARKERS` 已经分叉：写方三条（`worker_errors.py:35-39`），读方一条（`provider_failure.py:27-29`），两份都是模块私有名，谁也不知道另一份存在。`provider_failure.py:31-33` 的注释其实把判据写清楚了——"A classification that depended on which layer saw the string first is not a classification"——这个判据只在 marker 词表上落了地，前缀词表够不着，因为前缀在依赖方向的下游。

**参照的做法。** codex 的 `protocol` crate 是纯类型仓库：54 个业务与传输 crate 依赖它，它自己只依赖 10 个工具型 `codex-*` crate（`protocol/Cargo.toml:18-27`），逐个查过无一反向依赖 protocol 或 core——方向反了 Cargo 直接编译不过（`core/Cargo.toml:62` 已声明依赖 protocol）。值得注意的是 codex 在这条物理约束之外没有任何专门的分层检查：`deny.toml:220-257` 的白名单只管第三方 wrapper，`cargo shear`（`.github/workflows/rust-ci.yml:85-103`）只查未使用依赖，`.github/CODEOWNERS` 全文 17 行没给 `protocol/` 单独一行。openpi 侧，`extensions/shared/tool-surface.ts` 是工具可见性唯一真源、12 个扩展 import 它，"跨扩展只准 import shared/" 是约定不是工具强制。两个参照在这一点上给的是同一个答案：边界由拓扑保证，检查工具只在语言不提供拓扑约束时补位。Python 属于后者。

**吸收建议。** 新建 `src/travel_agent/agents/failure_protocol.py`，形状照抄 `node_names.py`：docstring 第一句声明零仓内依赖、失败协议词表唯一真源、纯数据不承载逻辑。进：六个 `PREFIX_*` 常量与 `KNOWN_PREFIXES` 元组、两份 marker 词表、两份 query-miss 词表、`ProviderFailureCategory` Literal 与 `ProviderFailureClassification` dataclass。不进：`format_worker_last_error`（写方逻辑）、`classify_provider_failure` 与 `is_provider_or_model_failure`（读方逻辑）、`_already_prefixed`（写方幂等判定）。import 方向变成 `failure_protocol` ← `worker_errors`、← `provider_failure`，叶子自己零仓内 import；三个 researcher 节点与两道门的 import 面一字不动。

三条行为不变的红线，这是本条最容易做错的部分。其一，两份 query-miss 词表必须以两个不同的名字并存（如 `WRITER_QUERY_MISS_MARKERS` 三条、`CLASSIFIER_QUERY_MISS_MARKERS` 一条）——合成一份是行为变更，写方多认或读方少认短语都会改掉某些 Run 的分类结果；搬动的全部收益是让分歧从"两个私有名互不知情"变成"一屏之内两个名字明显不一致"，不多不少。其二，`_EXPLICIT_EXTERNAL_FAILURE_MARKERS`（`provider_failure.py:89-104`）的前缀部分要从显式命名的子集常量派生（`KNOWN_PREFIXES` 去掉 `PREFIX_WORKER_FAILED`），不许直接展开全表——把 `worker_failed:` 纳进去就是修 §4.4 缺陷一，那是另一张票。派生式写出来之后，"为什么 `worker_failed:` 被排除"第一次有了可以落注释的位置。其三，读方替换字面量时要盯住大小写：`classify_provider_failure` 的比较发生在 `casefold()` 之后，常量若不是全小写会静默失配，把一类失败改判成 `:166-169` 的 incomplete 兜底——这是本条搬移里唯一直接落在门裁决路径上的生产改动，核实阶段特意点了名。

边界强制用 ruff 的 TID251 banned-api 加 per-file-ignores，实测可用（ruff 0.16.3）：它认相对 import（`from ..failure_protocol import X` 在 src 布局下被解析为全名并报出），白名单精确到文件。`pyproject.toml:110-113` 现在是 `select = ["E", "F"]`，加 `TID251` 一项；per-file-ignores 块已存在（`:115-118`），给写读两个文件各加一行豁免。CI 已在跑 `ruff check src/ tests/ scripts/`（`.github/workflows/pr.yml:39`），禁令落地即进门禁。TID251 管不了反方向（叶子自己不许 import 仓内模块），补一条十行 AST 测试——本仓已有同构先例 `tests/db/test_api_has_no_ddl.py:28-32`，读源码文本断言某类语句不出现。

选址在 `agents/` 而不是 `entities/`，依据是实测的 import 代价：`entities/__init__.py:2` 那句 `from .state import ...` 让 `import entities.contract_base` 拉起 960 个模块（含 langgraph 全家），而 `import provider_failure` 只要 47 个，在 `agents/` 下放叶子只加 3 个。把一个 189 行的纯分类器变成 langgraph 的传递下游，这个代价没有理由付。

配套测试一条，形状必须写对。对六个前缀参数化，快照它们在两个读方下的当前结论——`classify_provider_failure(prefix + 中性载荷)` 的 category 与 reason_code、`is_provider_or_model_failure` 的布尔值——逐行断言等于今天的实测值。两个坑是核实阶段实测出来的：载荷不能用 "upstream said no" 这类句子（"upstream" 本身是 `_TRANSIENT_MARKERS` 成员，会把两行期望翻成 transient）；断言不能写成"每个前缀都落进非兜底分类"——`worker_failed:` 今天就落兜底（`incomplete` / `provider_incomplete_result`，`provider_failure.py:166-169`）、`is_provider_or_model_failure` 返回 False，那条断言今天就是红的，改绿等于修 §4.4 缺陷一。正确的写法是把这个既成事实原样钉进表里，旁边引用缺陷编号。这条测试顺带填掉 §4.4 缺陷四（该协议在 `tests/` 下零引用）。

**代价。** 新文件 40~50 行，写读两方各改 import 段，`pyproject.toml` 加三行，一条 AST 测试加一条参数化快照测试。半天以内，零行为变更，风险集中在两条红线上。

**档位与理由：必做。** 拓扑不变则新缺陷持续产生——query-miss 词表已分叉一次、前缀字面量已抄两处，这是方向问题不是纪律问题；`510d5236` 已用同一手法消掉 F-12/F-16，可行性有现成判例；它还是 §4.4 四条缺陷任何一条的修复前置——读方拿不到写方常量，就没有地方判断"五个前缀在两个读方的结论是否一致"。

### 2.2 A-2｜state 字段所有权表加 AST 写点守卫（必做）

**我们的观察。** `TravelAgentState` 实测 97 个字段、必填 0 个，30 个带 reducer。reducer 定义"并发写怎么合并"；无 reducer 的 67 个字段走 `LastValue` 通道，同一 superstep 收到两个值直接抛 `InvalidUpdateError`（langgraph `channels/last_value.py:56-64`）——并发这一维引擎管住了。引擎完全不管的是另一维：跨节点、跨 superstep 的顺序写，谁有资格写。现状靠注释，且同一句告诫在两处逐字重复（`composition_repair.py:21-24` 与 `delivery_quality_gate.py:675-681`）——这不是文档冗余，是一条不变量缺机械落点的症状。

写点规模实测过（AST 扫描 `agents/`、`workflows/`、`services/state_invalidation.py` 里 `return {…}` 字面量的键）：74 个字段有写点、134 个（字段, 模块）对、25 个模块；39 个字段单写方、35 个多写方。多写方里有几条要单独确认的：`candidate_gate_route`/`candidate_gate_status` 除 candidate_gate 外还被 `itinerary_planner/node.py` 写，`last_error` 四个写方，`agent_status` 六个。扫描盲点是 `return {**helper(...)}` 展开，范围内 13 处（全仓 34 处）。

**参照的做法。** codex 把"最多一个运行中任务"写进类型（`Mutex<Option<ActiveTurn>>`），不可迁移——原因不是 Python 没有锁，是性质不同：它管并发独占，我们要管的是写资格，四个节点顺序各写一次 `last_error`，任何锁都不会反对。openpi 把"不能写"做成"拿不到那个工具"（`child-session.ts:25-31` 与 `:59-97` 的双名单，26 项排除），这在我们工具层已有对应物（`filter_tools_for_agent`），state 字段层没有——节点返回值是普通 dict，没有能力可以缺席。openpi 真正可迁移的是它给"没有类型可用的边界"配的守卫：`child-session.test.ts:533-538` 注释写明扫描是 source-based 的（新工具还没接线就要被抓到）；正则扫全部 `registerTool(...)`，`:716-748` 与双名单做双向集合断言；扫描看不见的工厂式注册用 `KNOWN_FACTORY_TOOLS` 白名单 fail-closed 兜住（`:672-692`），报错文本自带修法。这就是"为什么测试断言是本仓的对应物"的完整论证：openpi 面对同性质边界，选的正是源码扫描加 fail-closed 白名单。

**吸收建议。** 两个新文件。`workflows/state_ownership.py`：一张 `STATE_FIELD_OWNERS: dict[str, frozenset[str]]`，约 74 行，每个多写方字段旁边写一行"为什么有第二个写方"——`state_invalidation` 合法地清十余个字段、`itinerary_planner` 写 `candidate_gate_route`，这些是真实设计选择，写下来之后第三个写方出现时才有依据判该不该批。`tests/test_state_ownership.py` 四件事：正向（扫描命中的每个写点必须在表里，报错给出加表指引）；反向元测试（表里每条都必须被扫描命中，挡"节点删了表没删"，机制同 `test_invariants_doc.py` 的零引用防护）；盲点 fail-closed（`KNOWN_UPDATE_HELPERS` 白名单登记那 13 处 `**` 展开，扫到名单外的展开即失败，形状照 openpi）；给整条守卫一个 INV 编号写进 `docs/invariants.md`，invariants 门禁顺带保证它不被删。同 PR 删掉 `delivery_quality_gate.py:675-681` 那半段重复告诫，改成引用 INV 编号——`docs/invariants.md:5` 写的就是这个用途。

**代价。** 本文最贵的一条：表要人工过一遍（扫描给候选，"合法的第二写方还是漏网"必须人判），按 134 对估一到两天。风险低，纯新增测试。迁移可分两步：先锁 39 个单写方字段（一天内，且已能挡住"新节点顺手写不属于它的字段"这个主要失效模式），35 个多写方标 TODO 放行，第二步逐个确认。

**档位与理由：必做。** 它是 F-01、F-13 这类问题能长期共存的结构原因之一：字段被第二个模块写了，没有任何东西出声。也要诚实说清钉不住什么：它管"谁能写 `artifact_status`"，管不住"`artifact_gate_route` 的合法取值有哪些"——后者是枚举化问题，另一张票。

### 2.3 A-3｜`TravelAgentState` 补 `extra="forbid"`（必做，带行为标注）

**我们的观察。** `state.py:668` 是 `model_config = {"arbitrary_types_allowed": True}`。同仓 19 个 entity 模块继承 `StrictModel`（`entities/contract_base.py`，`extra="forbid", frozen=True`），贯穿全图的那个契约是唯一不适用严格性的。

**参照的做法。** openpi 的 agent 类型 frontmatter 只认 6 个 key，未知 key 拒绝整份文件（`agent-types.ts:81-88`、`:384-390`），拒绝理由写在注释里（`:75-79`）：拼错的键在危险方向上失败——`tool:` 留下 `tools` 未定义，孩子继承全部工具。codex 侧是 TOML 的 `deny_unknown_fields`。同一条原则：拼错的键静默变成"没设这个限制"。

**实测结论：可行，且立刻兑现。** 把 `state.py:668` 临时加上 `"extra": "forbid"` 跑全量（`tests/ --ignore=tests/db`，收集 255 条）：250 通过、5 失败，失败全部来自 `tests/test_run_command_contract.py` 六处 `TravelAgentState(run_id=..., user_message="x")`（`:197/:224/:259/:274/:305/:328`）——`user_message` 不是字段，真名是 `user_query`。今天这个值被静默丢弃，那五个测试一直在一个比自己以为的更空的 state 上做断言。这是开关自己抓出来的第一批存量债。（另有一条墙钟敏感测试 `test_slow_normalization_calls_share_one_operation_budget` 在整目录跑时闪红一次、单跑三次通过，与本改动无关，如实记录。）

与 LangGraph 的交互逐条验证过。checkpoint 恢复不炸：通道恢复只遍历当前 channel spec 取值（langgraph `pregel/_checkpoint.py:70-76`），checkpoint 里多出的键进不了 `schema(**input)`（`graph/state.py:1533-1534`）；实测往 InMemorySaver checkpoint 注入废弃字段后 resume 正常。旧 checkpoint 构造不失败：97 字段必填 0。`probe_checkpoint` 那条路（`travel_planning.py:828` 的 `model_validate(snapshot.values)`，全仓唯一整包校验点）实测不含注入的额外键。

但必须写清它买不到什么。实测 LangGraph 1.1.3 对节点返回的未知 key 既不抛也不 warn——键在写通道那层就没有对应 channel，在 pydantic 之前就被丢掉。所以 `extra="forbid"` 只盖"直接构造 `TravelAgentState`"这一面（生产四处：`travel_planning.py:864/:928`、`fast_answer.py:78/:119`，关键字已逐一核对合法），盖不住"节点返回值写错字段名"这个真正的高频风险——后者只有 2.2 的 AST 守卫盖得住。两条成对做才闭合；单做本条会制造"字段名已被类型系统看住"的错觉，比不做更危险。

【行为标注】这不是纯加固：加开关后，直接构造 state 时的未知键从静默丢弃变成 `ValidationError`。今天的四个生产构造点不触发，但这是行为变更，PR 里要点名。配套测试修法取零风险版：把六处 `user_message="x"` 直接删掉参数（保持这五个测试今天实际的语义——空 query），不要改成 `user_query="x"`——那会让被测路径从空 query 变成非空 query，是否等价没有证据。

**代价。** 生产一行、测试删六个参数，半小时。`model_config` 旁留注释写明覆盖面与不覆盖面，指向 2.2。

**档位与理由：必做。** 判据是"不做会持续产生新缺陷"：开关当场抓出六处已存在的错字段名调用，说明这条路正在被走错且走错无声。成本半小时。唯一要坚持的是不把它宣传成比实际更强的保证。

### 2.4 A-4｜plan_gate 搬出图定义文件（必做）

**我们的观察。** `travel_planning.py:1-15` 的 docstring 自称"仅负责图结构"，实际住着约 300 行 plan_gate 实现，占这个 998 行文件的三成：修改额度常量（`:126`）、门禁开关读取（`:140-155`）、计划文本序列化（`:156-182`）、77 行的 interrupt 载荷构造 `_build_plan_gate_payload`（`:184-260`，含与前端的 `gate`/`decision_options` 约定）、52 行的八条前置契约校验 `_validate_plan_gate_contract`（`:262-313`）、本地词表 `_projection_only_amendment`（`:315-322`）、122 行的节点体（`:324-445`）与路由函数（`:448-455`）。同层其他节点全部各自成模块（四道门在 `agents/orchestrator/`，budget_estimate、delivery 两节点、weather、draft 各在 `workflows/` 下），plan_gate 是唯一例外。

**参照的做法。** codex 的 `core-api/src/lib.rs` 用 `#![deny(private_bounds, private_interfaces, unreachable_pub)]` 强制自己确实只是门面；openpi 的 25 个扩展 `index.ts` 只做注册，实现在同目录其他文件。两个仓库都不靠 docstring 自律，靠一个可检查的形状。（core-api 这个门面层本身不值得抄，见 2.7；这里参照的只是"入口文件只做装配"这一点。）

**吸收建议。** 新建 `workflows/plan_gate.py`，上述区块整体搬入，`travel_planning.py` 改一行 import，`add_node(NODE_PLAN_GATE, plan_gate_node)` 一字不改。选址 `workflows/` 而非 `agents/orchestrator/`：plan_gate 的依赖里 `seal_minimum_delivery_draft` 与 `RunCancelled` 都在 `workflows/` 内，搬过去零新增跨层边；搬去 orchestrator 虽不成环但要新增两条 `agents → workflows` 边，换来的只是"五道门一个目录"的观感——而 plan_gate 与四道确定性门性质不同：唯一调 `interrupt()` 的节点，载荷是前端接口契约。归在一起会掩盖这个差别。

搬动风险三条，逐条有答案。在飞的 interrupt 不受影响：LangGraph 的 task_id 由 (checkpoint_id, checkpoint_ns, step, 注册节点名, PULL, triggers) 派生（`pregel/_algo.py:593-600`，PUSH 分支 `:913-920`），不含函数的 `__module__`/`__qualname__`，注册名真源已在 `node_names.py:19`——停在 plan_gate 上的 checkpoint 在部署后照样 resume。`_projection_only_amendment` 逐字复制、不许顺手统一：它与 `intent_amendments.classify_amendment` 是 F-02 那条可复现分叉的两端，统一是行为变更，函数上加一句"分歧见 F-02，不要在此处修"。F-08（两个入口对门禁开关的计算不对称）不解决也不加剧：开关计算留在 `travel_planning.py`，搬移 PR 的 docstring 点明这条，免得下一个人以为 plan_gate 模块已经自洽。

**代价。** 机械搬移加一条 import，一到两小时，零行为变更。额外收益有具体锚点：`_validate_plan_gate_contract` 的八条契约校验目前零测试，搬出后从"import 一次拉起整张图"变成"import 一个模块"就能构造输入去测——F-29 那条推演的验证路径正好需要这个。F-11 已把"新增子域必须新建模块"定为增量规则，plan_gate 是这条规则唯一的现存反例。

**档位与理由：必做。** 单看像洁癖，实际是把一批零测试的契约校验第一次变成可测的，且成本以小时计。

### 2.5 B-1｜`_DEEP_WORKER_NODES` 收进 `node_names`（值得做）

**我们的观察。** `chat_stream_handlers.py:23-28` 的四元素集合与 `node_names.WORKER_NODES`（`node_names.py:34-39`）逐字相同，是 `510d5236` 之后残留的最后一份 worker 名单副本。顺带修正分析底稿的一处虚构：该文件 `:22` 的注释只有一句 "# Node sets used by handlers."，并没有"避免循环 import"的辩护——不存在需要推翻的理由，直接换。

**吸收建议与代价。** 改成 `frozenset(WORKER_NODES)`，同段的 `_PROGRESS_STEP_NODES`、`_FINAL_OUTPUT_NODES` 成员换 `NODE_*` 常量（表留在原处——它们表达"这个流处理器关心哪些节点"，不是节点名真源）。半小时。

【行为标注】换源后 SSE 的 agent_progress 分帧集合从此跟着 `WORKER_NODES` 走：今天等值，将来加第五个 worker 时会同时改变流式输出的分帧行为。方向大概率正确（新 worker 本来就该进流式进度），但这属于运行时可观测语义的耦合面扩大，commit message 里要写明，不能当纯常量收编。

### 2.6 归并说明：三条建议移到别章

结构组还提出三条，与其他维度组重叠，正文归并到主张更完整的一侧：`amendment_continuations` 与图节点集合的守卫并入 4.2（测试组给出了图内省的正确形状）；`trace.py` 的 `NODE_PHASES` 接真源并钉 F-31 并入 6.4（核实发现它必须拆成守卫与行为票两半）；交付层异常的共同祖先与 `reason_code` 载荷并入 6.5 的 B-13（基类与枚举划分归错误组主张，且核实判定不立公共基类）。

### 2.7 不做的五条

**C-1｜import-linter 全仓分层契约。** 三条理由。本仓现在写不出一份诚实的分层契约：`entities/trip_run.py:21` import `infrastructure.row_values`、`delivery_quality_gate` import `workflows.composition_repair`、`travel_planning.py` import 五层，contracts 文件第一天就要开十几条豁免，豁免多到那个程度的分层契约是文档不是约束。真正承重的边界是个位数（失败协议、节点名、state 所有权），ruff TID251 逐条禁令已能表达，零新依赖零新 CI 步骤。codex 自己也没有这层工具——它的边界强度来自 Cargo 编译期无环，那是免费的；照抄"引入分层检查工具"实际是照抄一件 codex 没做的事。复议条件：TID251 禁令长到十条以上，或出现"某层整体不许 import 另一层"这种无法逐模块枚举的规则。

**C-2｜新建顶层 `protocol/` 包。** 不是因为仓库小，是因为同一模式已有落法：`510d5236` 把节点名落成 `workflows/node_names.py`，2.1 把失败协议落成 `agents/failure_protocol.py`——就近的包内叶子。再开顶层包就是一个模式两种落法，比放错位置更难维护。还有一条实测理由：顶层包意味着新开一个必须永远为空的 `__init__.py`，而本仓已有 `__init__.py` 变重的教训（`entities/__init__.py:2` 让五行的 `contract_base` 背上 960 个模块的 import 成本）。复议条件：零依赖叶子长到四个以上且开始互相引用时，收包并给 `__init__.py` 加"必须为空"的测试。

**C-3｜codex `core-api` 式纯 re-export 门面。** 决定性事实是现场核实的：codex 自己的生产消费者全部绕过它——`grep -l 'codex-core-api' */Cargo.toml` 只命中它自身与 `thread-manager-sample`，50 多个内部 crate 直接依赖 `codex-core`。这个门面定位是给外部 SDK 消费者的，而我们连这个场景都没有（单机单进程，对外面是 HTTP + SSE，`api/` 层已在做同一件事）。不做，不设复议条件。

**C-4｜`assert_never` 加 mypy 门禁的穷举 match 等价物。** 两条理由，第二条是本轮新查到的。本仓没有类型检查门禁（dev 依赖只有 pytest 系加 ruff，CI 只跑 ruff 与 pytest），没有静态检查器的 `assert_never` 只是运行时 raise，而"新增枚举值某处没处理"的典型症状恰是那条分支永远不被走到；补一道 mypy 门禁是 101k 行仓库上另一个数量级的工程。更要紧的是 codex 自己在工具曝光这条协议上的穷举保证也不是编译器给的：`ToolExposure` 六个 variant（`tools/src/tool_executor.rs:51-80`），全仓消费走 `is_direct()`/`is_deferred()`/`is_available_in_code_mode()` 三个方法或值比较，业务代码对它零穷举 match；穷举性全靠 `is_available_in_code_mode` 内部那一个无 `_` 的六分支 match（`:94-97`）自我保证——另一处 `spec_plan.rs:230-242` 的 match 对的是 (bool,bool,bool) 元组且 `:241` 带 `_` 兜底臂，加第七个 variant 那里也不会报编译错。实际形状是"只有一处做穷举投影、其余间接调用"，而这个形状用测试就能等价实现——2.1 那条参数化快照表就是它，代价差三个数量级。

**C-5｜把 `TravelAgentState` 拆成子状态模型。** LangGraph 的 channel 在字段层展平（`graph/state.py:1520-1534`），拆成三个子模型后 channel 面一点不变——要么仍是 97 个平铺字段，要么变三个大 channel 而失去逐字段 reducer 与 `InvalidUpdateError` 并发保护——只多一层 mapping。真正想解的"谁能写"由 2.2 解、"未知字段"由 2.3 解；拆模型解的是"文件长"，而 `state.py` 668 行在本仓排不进长度问题前五（`candidate_gate.py` 2792 行）。不做。

---

## 3. 配置声明化、工具治理、prompt 管理

先把判据写出来，因为本仓 config 层自己已经写清了迁与不迁的标准，只是从没用到 config 目录之外。其一，容器型字段走 YAML、不开环境变量入口（`config/env.py:38-42` 原话：用一个字符串表达一张价格表，得到的是又一门需要自己解析器的小语言）。其二，一份坏文件该不该让进程起不来，看它治理什么——`config/providers.py:94-96` 对 preset 校验失败选了 `logger.error` 加 continue，理由是它只影响"帮你填配置"；这条判据的另一半从没被写下来：治理收窄的表坏掉必须硬失败，因为它的静默降级方向是放开。其三，仓库自带的声明放 `configs/`，用户配置放 `config.yaml`——`configs/providers/*.yaml` 五份由 `providers.py:81-101` 单独加载，不是 `Settings` 字段，用户改不动。按这三条走，答案不是"三张表都迁 config"。

### 3.1 A-5｜`_AGENT_TOOL_POLICY` 迁 `configs/tool_policy.yaml`（必做，带行为标注）

**我们的观察。** 表在 `agents/utils.py:275-323`，四个 worker 键，值是 `servers`/`deny_tools`/`extra_tools` 三个集合。它有两个消费方，不是一个：`filter_tools_for_agent`（`:419-487`，三层收窄的最后一层）；`_WORKER_AGENTS = set(_AGENT_TOOL_POLICY.keys())`（`:495`），在 `apply_tool_exposure:547-552` 里判"这个 agent 算不算 worker"，进而决定 deferred 曝光是否生效——这张表的键集同时是工具白名单索引和"谁走按需曝光"的名单，上一轮只提了第一个消费方。三条今天成立、零测试触碰的跨表关系：键集等于 `WORKER_NODES`；三个 policy 的 `servers` 并集落在内置 11 个 MCP server 之内（其中 `baidu-maps` 与 `open-meteo` 不被任何 worker 引用——后者还在 `tools/temporal.py:149-162` 被钉了启动期 schema 合同，一个没人消费的 server 的 schema 不合会让它进 error 态）；`candidate_gate._ALTERNATIVE_TOOLS` 的 20 条推荐工具全部要在对应 worker 的允许面内，否则补研轮推荐的工具在 gateway 被拦。

**参照的做法。** codex 的 config crate 有 87 处 `deny_unknown_fields` 钉在叶子结构体上，顶层另有 `strict_config.rs` 基于 serde_ignored 收集未匹配字段并带 TOML 行列号报错——但同一份笔记也记下了反例：角色 TOML 复用同一个目标类型却走不严格的那条路（`core/src/config/mod.rs:1992-2001` 只 `try_into()`）。可吸收的不是"codex 严格"这个印象，是"严格校验必须钉在每条加载路径上，否则会出现一条没人测的降级路径"。openpi 的 6-key 白名单与未知 key 拒绝整份文件（2.3 已引）是镜像：他们的静默失败方向是放开，我们的是收紧，方向不同，"静默"一样。

**吸收建议。** 新增 `configs/tool_policy.yaml`（表体一一对应，`agents/utils.py:281-284` 那段"destination 是唯一被允许 ask_user 的 worker"之类的判据注释原样搬进 YAML 注释）；新增 `config/tool_policy.py`：`AgentToolPolicy(StrictConfig)` 加 `ToolPolicyFile(StrictConfig)`，`load_tool_policy()` 用 `lru_cache` 读盘校验，校验失败 raise `ConfigError`——与 `providers.py` 的吞错是刻意分叉，理由进 docstring（preset 坏了影响"帮你填配置"，policy 坏了影响"谁能碰哪个 provider"）。`agents/utils.py` 两处引用改读 loader；`_WORKER_AGENTS` 保持模块级求值（`_WORKER_AGENTS = frozenset(load_tool_policy().agents)`），不改成每次调用——这一点是核实阶段点名的：它牵动 `should_defer`，而 deferred 改变送给模型的 tool schemas 与 system prompt，属模型调用面，必须保持 import 期一次求值的现状形状。

"白拿"三件事要说实话：未知字段硬失败真白拿（`StrictConfig` 加 `loader._describe_validation_error` 的"字段路径 + 当前值"报错格式）；来源报告拿不到（`EffectiveConfig.sources` 只覆盖 `Settings` 树，要自己带一个 `source: Path`，成本一行）；文档同步要在 `cli/main.py:737-745` 的 artifacts 字典加一项、写一个约 30 行的生成器，换来 `test_generated_config_docs_are_committed` 那条门禁自动覆盖——是一件工作，不是副产品。

等价性验证是本条关键。`filter_tools_for_agent` 对输入保序（`:459-475` 单遍 append），判定依赖的集合实际是四个，不是三个——模块级 `_SCOPED_NON_MCP_TOOLS`（`:325`）在本地工具分支（`:469`）与 policy 未命中分支（`:438-448`，那是一条独立的第二 return）都参与判定。它不迁移，方案里要显式声明它不动；在此前提下，三个迁移集合逐元素相等加键集相等，就推出任意输入下输出逐字节相等。落法三步：迁移前把当前表 dump 成 `tests/fixtures/agent_tool_policy_baseline.json` 提交（此后只有明确的策略变更允许改它）；迁移后 `load_tool_policy()` 规范化比对，键集单列断言；再加一份"四个 agent × 合成全量工具列表 → 输出名字序列"的行为 fixture 做冗余确认。`deny_tools: {"*"}` 是魔法字符串（`:453-454`），首轮照抄不改形状——改成 `deny_all: bool` 会让等价性从"集合相等"退化成"要论证行为相等"。

【行为标注】loader raise 引入一个今天不存在的启动失败模式：字面量表永远在，YAML 文件可以缺失或损坏。这是有意的 fail-closed 选择（治理收窄的表坏掉不该静默放行），但它是启动语义变更，PR 里点名，invariants 里立条目。

**代价。** YAML 约 40 行、schema 约 30 行、loader 约 25 行、两处引用改动、测试与 fixture 约 120 行、文档生成器约 30 行。半天到一天。

**档位与理由：必做。** F-25 背书（改策略必须改代码）、F-17 说明后果不可见。真正抬进必做档的是第二个消费方：一张同时决定工具白名单和曝光策略的表，四个键零守卫，加第四个 researcher 时两处静默降级——工具面归零、曝光策略也不认它。

### 3.2 A-6｜工具同名注册：先让冲突可见（必做），再谈硬失败（行为票）

**我们的观察。** `ToolRegistry.register`（`tools/registry.py:99-125`）第 117 行无条件覆盖，日志只有一句 debug（`:124`）。注册顺序：`builders.py:199` 先内置三个本地工具、`:207` 再 MCP，而 11 个 MCP server 是 `asyncio.gather` 并发初始化（`mcp_manager.py:537-540`）——同名 MCP 工具之间谁赢看调度。后果不是少一个工具，是治理面翻转：`filter_tools_for_agent` 按 `source` 分支（`:467-475`），一个 MCP server 若暴露 `global_place_search` 这个名字，会把 `builtin_tools.py:236` 那条本地注册的 `source`/`server_name`/executor 一起换掉；那个工具还带手写 manifest（`builtin_tools.py:245-258`，`allow_offline_fallback=False`，注释写明它与 `_FALLBACK_MAP` 里"没有这一条"是同一条约定的两半），覆盖后 manifest 走 `infer_tool_manifest` 按 category 推断（`entities/tool_gateway.py:227`，search 类推成 True），"地点身份不接受替身"的约定静默失效。

**参照的做法。** codex 是三层不是一条规则：可信路径冲突走 `error_or_panic`（debug 构建 panic、release 记 error，两种构建都不插入，先注册者保留，`core/src/tools/registry.rs:307-331`）；外部工具永不 panic，warn 加不插入，首个冲突名记进 `self.first_collision`（`:341-372`）；是否升级成用户可见错误由 turn 级开关决定。三层对应"开发者 bug / 运行时正常但不理想 / 用户要求严格"。

**吸收建议——按行为约束切成两半。** 本轮能做的是可见性：`register` 在命中已存在名字时记账（registry 加 `collisions()` 读方法，冲突名带上新旧两方的 `source`/`server_name`），`logger.warning`，MCP 侧计入该 server 的状态供健康检查面读。这一半纯观测、零行为变更，正好落实上一轮 §7.5 的判语"三者都 fail-closed，区别在失败是否可见"。硬失败那一半——内置路径 raise、MCP 路径不插入——是两处运行语义变更：前者把"降级启动、少三个工具"变成"进程起不来"（`builders.py:201-202` 那个吞异常的 except 也要跟着收窄），后者把同名之战的胜者从后注册者翻成先注册者，而"今天没有冲突所以是空操作"这个前提只对 tavily/brave/firecrawl 三家核过注册面，amap、baidu、duckduckgo、fetch、open-meteo 的完整暴露面没有逐条核过。两处都该做，但按行为变更立项：先靠可见性那一半跑一段时间确认零冲突，再带着 ADR 把语义翻过来。

**代价。** 可见性一半：registry 约 15 行加一条测试，一小时。硬失败一半：另计，含 ADR 与 invariants 条目。

**档位与理由：必做（可见性一半）。** 成本一小时，收益是把"治理面翻转"从静默事件变成告警；硬失败一半的前提核实也靠它积累。

### 3.3 A-7｜research packet 的 prompt 快照，按仓库既有生成物门禁的形状做（必做）

**我们的观察。** `build_research_packet_system_prompt`（`agents/research_packet_prompt.py:41-98`）是纯函数：10 个关键字参数（时间是传进来的），三个 worker 各调一次。这段文字是硬合同不是文案，因为主 worker 调用不带 `response_format`——ReAct 循环在 `agents/utils.py:1827` 只传 messages 与 tool_schemas，`response_format` 只在修复轮出现（`research_packet_output.py:3621/4178/5084`）；`research_packet_output.py:3164-3168` 的 docstring 把结论写死了：provider 不强制 schema，router 把它降级成 `json_object` 并把 schema 复述成 prose，"The schema *text* is therefore the entire contract the model reads"。prompt 里嵌的 schema 实测 29,213 字符（紧凑序列化；默认 separators 是 31,646，整份 prompt 约 33.8K）。这类漂移在本仓已经真实发生并被手工修过一次——`packet_candidate_limit` 的 docstring（`research_packet_output.py:174-181`）记着"prompt 说最多 4 个而同一次调用的 schema 强制 3 个"那次事故，函数本身就是修复物。今天还有一处活着：`destination_researcher/node.py:296` 的定向补研 task prompt 写"1 至 6 个"，同一次调用的 system prompt 里 `{candidate_limit}` 是 4。缺陷归缺陷轨，但它是这条建议最强的收益证据：快照会把两个数字并排印进同一份 fixture 的 diff。

**参照的做法。** codex 对"钉住渲染出来的 prompt"给了三种答案，核实后推翻上一轮的一处说法：`format_role` 没有快照测试（`role_tests.rs` 全是子串 contains 断言）；insta 快照用在 `core/src/context/world_state/` 的 instructions 测试（逐字钉 prompt 片段）与 `core/tests/suite/` 的 38 个 `.snap`（含占位符钉整轮请求消息结构）；`codex-prompts` crate 用字面量 `assert_eq!`（dev-dependencies 只有 pretty_assertions）。三个子系统三种写法，没有统一决策——所以这条建议的依据不在 codex，在本仓自己的三条事实：prompt 文本是全部输出合同、这类漂移修过一次、今天还有一处活的。形式按本仓既有资产选：`test_generated_config_docs_are_committed`（`tests/test_config_contract.py:341-356`）那套"生成物提交、逐字符比对、报错给修复命令"。

**吸收建议。** 三份 fixture `tests/fixtures/prompts/research_packet_system.<worker>.txt`，固定入参生成（`candidate_limit` 取 `packet_candidate_limit(worker)` 不写死数字——4 改 5 时 fixture 该变，这正是要看见的；三个 worker 的文案不同，散文段实测 destination 4649 / transport 4188 / accommodation 4182 字符，golden 是三份各自的）。schema 段不进 fixture：生成时先 `assert schema_text in prompt` 再把它替换成 `<RESEARCH_PACKET_SCHEMA>` 占位符——那一行断言是这套设计里最重要的一句，它守住"schema 逐字符注入这件事没有断"，而 schema 内容本身由 `ResearchPacket` 的类型定义管，entity 改字段不再 churn 三份 fixture。schema 的可读 diff 由另一份生成物 `docs/research_packet.schema.json` 承担——两件事各有可 diff 的落点。生成器接既有 CLI：`cmd_prompts_snapshot` 与 `cmd_config_docs` 同形，带 `--check`，更新流程与 INV-CFG-003 同一句式（改了 prompt 就跑 `journeypilot prompts snapshot` 并提交）。测试组主张生成器放 `scripts/`（理由：`cli/` 是产品面且整包 994 行零测试，测试基础设施不该进产品面）——两个主张各有道理，本文取 CLI 同形，因为"一种更新流程"的习惯价值更大；若采 `scripts/` 方案，报错文案里的命令跟着换即可，其余设计不变。三个 `build_*_task_prompt`（含那个"1 至 6"）同机制加三份文件。

有一处要按核实结果改标的：分析底稿建议断言 `research_packet_prompt.py:59` 与 `router.py:374` 用同一组 separators，这条守卫是错的——`_messages_already_contain_schema`（`router.py:360-375`）只在 `response_format=json_schema` 被降级时才跑，而主 worker 调用根本不带 response_format，那份 prompt 永远不是 dedupe 的比对对象，按原稿写会留一条永绿的假守卫。真正靠同一组 separators 耦合的是修复轮：`research_packet_output.py:4929-4933` 把 schema 紧凑序列化进修复 prompt，`:5083-5090` 同一次调用带 `json_schema`（同形另有 `:3612`、`:4170`）——router 降级时靠子串比对去重，序列化参数一变就静默翻倍。共享常量与断言落在这两处之间。

**代价。** 约 200 行加三份 fixture，半天。真实成本在维护心智：动 prompt 或动 `ResearchPacket` 都要多跑一条命令——对照物是 INV-CFG-003 已经让人习惯了同一件事。

**档位与理由：必做。** 零守卫、漂移有前科、现行犯还在，成本半天。

### 3.4 值得做的三条

**B-2｜降级表与工具推荐表的注册面守卫，接在 MCP 初始化上（值得做）。** `_FALLBACK_MAP`（`tools/fallback.py:83-92`）的注释已把每条边的注册面核到包版本并立了规矩（新增降级边必须先拿注册面证据），但规矩没有执行者。同类表里已经有一张在跑死键：`capability_planning.py:59-64` 六个条目四个不同名字，其中三个不是注册过的工具名（`nominatim_place_search`/`search_web`/`rail_12306_search`——真名分别是 `global_place_search`、`free_web_search`、`get-tickets` 系），第四个 `global_route_search` 是真名（`builtin_tools.py:263`）。这张表进 `recommended_tools`，被 `prioritize_recommended_tools`（`agents/utils.py:168-186`，docstring 写明"LLM 倾向于调首个"）用来重排工具——对 destination 与 accommodation 是空操作（推荐名全对不上），对 transport 不是（`global_route_search` 命中）。为什么不迁配置：`_FALLBACK_MAP` 的键是 MCP 工具名，配置加载期不存在（要等 `mcp_manager.initialize()` 拉 `list_tools`），搬 YAML 只换存放地点，死键这个唯一失败模式仍无人查。本仓已有现成形状：`tools/temporal.py:149-198` 的 `_PINNED_MCP_SCHEMA_REQUIREMENTS` 在 MCP 初始化时跑、缺项升级 RuntimeError、INV-TOOL-001 背书。落法：全部 server 初始化完成后收口检查三份名单（`_FALLBACK_MAP` 键与目标、`_ALTERNATIVE_TOOLS` 取值、`_TOOLS` 取值）逐个 `registry.has_tool`，缺的记 `logger.error` 写进可读的 gaps 字段；检查函数放 `builders.py`（`tools/` 不能 import `agents/`）。首轮只报告不 raise——`_TOOLS` 今天就有三个死键，raise 会让现有部署起不来。另补两条静态守卫：`_ALTERNATIVE_TOOLS` 每个名字在对应 worker 允许面内（今天 20 条全成立）；`_FALLBACK_MAP` 每个键的 manifest `allow_offline_fallback` 为真（否则降级分支在 `agents/utils.py:911` 就短路）。【行为标注】清死键本身是模型调用面变更——改成真名会让 `prioritize_recommended_tools` 真的重排 tool_schemas，且 transport 今天已在被重排，影响从一个 worker 扩到三个；"缺项清零后升级 raise"隐含这次变更，归缺陷轨单独立项。

**B-3｜`config/mcp_defaults.py` 收尾（值得做，取低成本落法）。** 文件头 `:1-9` 自称"这是一份数据"，落地是返回 dict 的函数（`:49-166`）。函数身份有实在理由：函数体里有三件运行期的事——node_modules bin 存在性判断（`:36-45`）、`sys.executable` 拼路径、`os.getenv`（`:30-34`）——整体搬 YAML 要先发明三种插值，正是 `config/env.py` 判过的"又一门小语言"。切"声明/解析"两半的方案可行（静态声明进 `configs/mcp/servers.yaml`，解析留在 Python，`required_env` 与 `env` 的 Key 名重复由派生消掉），但核实把收益打了折：实质重复只有 6 处不是 11 处，而等价性一破就是改"实际启动哪 11 个 MCP server 及其 command/args/env"——工具面变更，fixture 还要覆盖 npx 回落与本地 bin 两条分支。所以推荐的第一步是一行自述修正：把 docstring 改成"这里是内置 MCP 的构造：静态部分是字面量，路径与 Key 要运行期解析，所以它是函数不是数据文件"——F-20/F-39 那族文档漂移的成本正是第一屏误导排障，一句准确的自述比半吊子 YAML 更值钱。YAML 切半留作可选项，做的话按 A-5 的基线 fixture 法验等价。

**B-4｜候选上限守卫（值得做）。** 上一轮说"配置反射渲染可迁移（数据源已存在，缺渲染函数）"，核实后要修正：渲染函数本仓已经有了，`packet_candidate_limit`（`research_packet_output.py:168-199`）就是，prompt 里 `{candidate_limit}` 已在用它；核过之后没有第三处"相等且仍写字面量"的地方。这一维的实际落点是两条断言：对每个 worker 从 system prompt 输出里正则取出"最多输出 N 个"的 N，断言等于 `packet_candidate_limit(worker)`（今天绿）；再加一条 `pytest.mark.xfail(reason="node.py:296 的 6 与 packet_candidate_limit 的 4 不一致，属行为决策")` 盖住 task prompt 那个 6——xfail 会在有人改对的那天 XPASS 报出来，删掉就没人记得。约 40 行，一小时，并入 A-7 的测试文件。

### 3.5 不做的三条

**C-6｜`capability_planning` 的三段执行顺序不迁配置。** 它是图拓扑不是参数：`order` 构造（`capability_planning.py:174-184`）、`upstream_assignment_ids`（`:200-214`）、`_DOMAIN_OWNER`（`:39-45`）是同一件事的三个面，迁走其中一个等于新造一张要同步的表；顺序可配置则四段 deadline 窗口的语义就没了（研究段在组合段之前是窗口切分的前提）。参照仓库这一维也不支持：codex 角色 TOML 能改 model/effort/permissions，不含"先跑谁"；openpi 的自由编排是设计层前提不同（上一轮 §7.8 已判不迁）。该做的替代是守卫不是迁移：断言 `order` 展平集合等于 `_DOMAIN_OWNER` 值集加 itinerary、itinerary 恒在末段、每个 researcher 的 upstream 与段位一致——约 40 行测试，归入第 4 章的守卫族。

**C-7｜prompt 整体外置为数据文件。** 确认上一轮判断，补三条量化：模板 14 处插值（含表达式插值与二级 format），外置要先有支持它们的模板语言，或把逻辑挪进调用方——净收益零；最大那块根本不是文本，29K 字符的 schema 是运行期从类型现算的，不能外置；codex 自己两条 prompt 生产路线并存（静态模板与运行时拼串），照抄哪一路都能引证。做了 A-7 之后外置想解决的问题（可 diff、可 review）已经解决。

**C-8｜工具策略不做成 `Settings` 字段。** "迁进 config 管线"最自然的读法恰好是错的那种。做成 `Settings.agent_tool_policy`，用户就能在 `config.yaml` 里把一个刻意声明"纯 LLM 规划、拒绝所有工具"的节点（`agents/utils.py:319-322`）打开；且 loader 对非 mcp 段是整体替换语义，半份 policy 会把另外三个 worker 清空。codex 对同一问题的答案是第二道关（`Constrained<T>` 校验闭包让覆盖只能收窄、`deny_read` 只增不减），我们没有这套东西，也不该为一张四键表造。policy 是仓库对自己的治理声明，与 `configs/providers/*.yaml` 同类：放 `configs/`，用户改不动。真要开用户覆盖入口，前置是先有收窄校验器，那是另一个项目。

---

## 4. 测试钉法与测试组织

上一轮 §7.7 判这一维"优先级最高、成本最低"，本轮把五张零守卫表写到可开工的粒度。先记一件基线变化带来的新事实，它改变了做这批守卫的正确顺序。（五张表里的 `last_error` 前缀那张已并入 2.1，此处不重复。）

### 4.1 A-8｜先修样板：现有守卫已从"对图"退化成"对表"（必做）

**我们的观察。** `test_run_execution_contract.py:131-166` 是上一轮认定的守卫样板。`510d5236` 之前它的第一条断言两侧是两份独立文本（run_control 手抄的四个字面量 vs travel_planning 的清单）；现在左侧 `_DEADLINE_BLOCKED_WORKER_NODES` 由 `node_names.RESEARCH_WORKER_NODES` 派生（`run_control.py:29`、`:649-650`），右侧 `WORKER_NODES` 是 `travel_planning` 对同一真源的 re-export（`travel_planning.py:66-92`）——两侧同源，断言退化成恒真。后果具体：docstring（`:132-140`）说"加第四个调研 worker 会静默落进 research 默认档"，今天在 `build_travel_workflow()`（`travel_planning.py:514`）里 add_node 一个第五 worker、给它一条边，只要不动 `node_names`，这条测试照样全绿——它两边都不看图。

**吸收建议。** 把断言一侧换成从真实图读出来的集合。实测成本可接受：import `travel_planning` 约 0.9 秒，`build_travel_workflow()` 28 毫秒，不需要 checkpointer、数据库、配置，返回未 compile 的 `StateGraph`，`graph.nodes` 是节点名 dict，`graph.branches[node]` 里每条分支的 `ends` 是 `{路由值: 目标节点}`。取分支按 `values()` 不按名字——分支键是路由函数的 `__name__`，那是 LangGraph 内部约定，不该写进断言。这套内省必须自带反空转哨兵，本仓与 openpi 各有先例（`test_invariants_doc.py:116-134` 的"解析器抓到零条就永远通过"防护；openpi drift guard 的 `registered.size >= 15`，`child-session.test.ts:656`）：

```python
def test_graph_introspection_still_sees_the_graph():
    graph = build_travel_workflow()
    assert len(graph.nodes) >= 20, "图内省坏了：下面所有集合断言都会在空集上空转"
```

守卫本体留在 `test_run_execution_contract.py` 原处不搬家——它挂在 INV-RUN-005 上，搬文件会让不变量的 Tests 引用失效，`test_invariants_doc.py` 的门禁正好会拦这种搬家。

**代价与档位。** 半天，纯测试改动。必做，且是本章其余守卫的前置：不修样板，照它复制出去的每一份都是同款弱守卫。

### 4.2 A-9｜图内省守卫：`amendment_continuations` 与 `_KNOWN_NEXT_AGENTS`（必做）

**我们的观察。** `amendment_continuations` 的 20 项表在 `travel_planning.py:665-686`，是 `build_travel_workflow()` 的函数局部变量——任何模块 import 不到它，唯一的观察途径是把图建起来读 `ends`。实测：`ends` 恰 20 项，`nodes - ends == {scope_clarifier, intent_amendment_router}`，反向差集为空。两个缺席各有理由（clarifier 在合同建立之前、router 不能回自己），但理由今天没写在任何地方。`_KNOWN_NEXT_AGENTS` 在 `dispatcher.py:32-36`，三个值，写方是同文件 `dispatcher_node` 的八处 `return {"next_agent": ...}`，其中两处是三元表达式（`:98-102`、`:143-147`）；`next_agent` 另有两个图外写方（`scope/node.py` 与 destination 的 HALT），守卫必须把写方范围钉在 dispatcher 上，否则第一天就红在两个无关文件上。

**参照的做法。** openpi 的双向闭包（正向"每个注册工具必须被分类"、反向"排除表的名字必须仍对应真实注册"、豁免带理由，`child-session.test.ts:716-748`）。codex 的穷举 match 不可迁移，Python 侧的等价物就是这类"图内省 + 源码扫描"的组合。

**吸收建议。** 新文件 `tests/test_graph_table_contract.py`。第一条：`ends <= nodes` 且 `nodes - ends` 恰等于显式豁免集 `{NODE_CLARIFIER, NODE_INTENT_AMENDMENT_ROUTER}`，豁免理由写成断言旁的注释——漏一个节点，修订续跑就会撞 LangGraph 路由错误，发生在运行时而不是 CI。第二条组合拳：先做一步生产侧的纯字面量搬家——dispatcher 顶部立 `NEXT_TO_CHECK`/`NEXT_CANDIDATE_GATE`/`NEXT_DISPATCH_GROUP` 三个常量，`_KNOWN_NEXT_AGENTS` 从它们派生，八处 return 换常量，字符串值一字不改；再加两条测试：图内省断言 dispatcher 分支目标集的构成（`dispatch_group` 不是边名，经 Send 展开成 worker 节点），与 AST 扫描断言"`{"next_agent": <字面量>}` 的字面量集合等于 `_KNOWN_NEXT_AGENTS`"。扫描器有一个实测踩过的坑：天真的 `ast.walk` 会把三元表达式的条件也收进去，多出 `itinerary_planner` 与 `passed` 两个假阳性——只递归 `IfExp.body`/`IfExp.orelse`，遇到不认识的写法直接 raise 不静默跳过：

```python
def _route_literals(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _route_literals(node.body) | _route_literals(node.orelse)
    raise AssertionError(f"next_agent 出现了扫描器不认识的写法：{ast.dump(node)[:120]}")
```

【行为标注（流程要求）】dispatcher 常量化动的是路由决策文件——值抄错就直接改路由结果，而 ruff 的 E/F 抓不到字符串内容错。核实阶段的要求是：常量化与两条测试必须同一个 PR 落地，不接受先改生产后补测试。

**代价与档位。** 常量搬家一小时，测试半天。必做：`route_after_dispatcher:178-183` 的兜底是"log error 后收敛 to_check"，新增路由值忘登记的后果安静（F-32 那族表已从六处长到八处，F-31 是已发生的漏配实例）。INV 编号：续跑表新开 INV-INTENT-006；dispatcher 路由值挂在 INV-PLAN-001 下加 Tests 引用即可。

### 4.3 A-10｜`_AGENT_TOOL_POLICY` ↔ 图上 worker 集合（必做）

**我们的观察。** 表的四个键今天恰等于 `WORKER_NODES`，零守卫。漏配一个 worker 是两重静默叠加（工具面归零 + 不被认成 worker、按需曝光失效），只有一条 `logger.debug`（`agents/utils.py:477-486`）。依赖方向已通：`agents/utils.py:51-52` 本来就 import `workflows` 下的模块，而 `node_names` 零依赖，表的键完全可以直接用 `NODE_*` 常量。

**吸收建议。** `tests/test_tool_policy_contract.py` 两条断言：键集与 `WORKER_NODES` 双向相等（报错分列"只在图里/只在表里"）；`_WORKER_AGENTS == set(WORKER_NODES)`。再加一条揭示性断言：`deny_tools` 含 `"*"` 时 `servers`/`extra_tools` 是死配置（`:453-454` 直接返回空列表），itinerary_planner 哪天被人加了 server 白名单，这条会红并说明那份白名单不会生效。顺带的生产改动（可选，建议做）：四个键改用 `NODE_*` 常量，零行为变化。注意顺序依赖：A-8/A-9 先落地，把 `WORKER_NODES` 钉在图上，否则这条又是两张常量表互测。若 3.1 的 YAML 迁移先行，断言对象换成 `load_tool_policy()` 的键集，形状不变。

**代价与档位。** 半天，零风险。必做（F-25 + F-17 双背书）。INV-TOOL-002。

### 4.4 A-11｜`_FALLBACK_MAP` 的静态守卫与注册面声明表（必做）

**我们的观察。** 五条降级边全指向 `free_web_search`，消费点在 `agents/utils.py:902-928`。"表里的键是不是真工具"静态测试答不了——`tavily_search` 是 npm 包暴露的名字，注册发生在运行期（`mcp_manager.py:510`），证据只在注释里（`fallback.py:73-81`，逐条核到包版本与行号）。但四件事完全静态可测，合起来盖住全部失效模式：降级目标链每一环都在仓库里（`free_web_search` 由仓内 server 暴露，`mcp_defaults` 的 `duckduckgo-search` 条目指向该文件且无 `required_env`——缺 Key 被跳过的规则对它不生效）；每个键归属的 server 必须在默认配置里；降级不成链不自环；每个能触发降级的 worker，其允许面必须放行降级目标。第四条钉的是真实脆弱面：`accommodation_researcher` 的 `servers` 不含 `duckduckgo-search`，它拿到 `free_web_search` 全靠 `extra_tools` 那一行——有人清理时删掉它，付费检索额度耗尽就从"降级到免费搜索"变成硬失败。

**吸收建议。** 数据一步：在 `fallback.py` 加一张并列的纯声明表 `_FALLBACK_KEY_SERVERS`（键 → 归属 server，注释行放注册面证据），不被生产代码读——把 `:31-32` 那条"新增降级边必须先拿注册面证据"的规矩变成一个有位置的东西。断言四条进 `test_tool_policy_contract.py`。两处按核实结果修正的写法：第四条判定不要在测试里重写一遍 `filter_tools_for_agent` 的集合逻辑（会造出判定的第二份实现），直接调真实现、喂手造 schema 列表；被拦分支的断言不能写 `pytest.raises(PermissionError)`——那个异常出不了 `execute_tool`，`agents/utils.py:1009-1010` 有 `except PermissionError: pass`，最终返回的是 `status=FAILED`、`fallback_to=blocked_fallback_to` 的 envelope（`:899-900` 的注释写的就是这个意图），断言要落在 envelope 上，否则守卫恒绿。顺带三行：`tools/temporal.py:87` 的 `_CAPABILITIES` 键是 (server, tool)，三个 server 全是仓内实现，工具名可扫源码核死。

**代价与档位。** 一天。必做——第四条断言对应的失效模式（删一行 extra_tools 把降级变硬失败）没有任何其他机制会出声。INV-TOOL-003。与 3.4 的 B-2 是同一族的两半：这里是静态守卫，B-2 是 MCP 初始化时的运行期收口。

### 4.5 A-12｜修订协议的三个纯函数穷举测试（必做，钉 F-09）

**我们的观察。** 本轮逐符号复核 F-09 仍成立：`classify_amendment`、`invalidation_update`、`_terminal_bucket`、`_document_has_content`、`claim_checkpoint_resume` 在 `tests/` 下零命中（13 个相关符号一次 grep 全空，全仓 352 个 test 函数无一触碰）。

**吸收建议。** 按 fixture 成本排三步。第一步 `invalidation_update`（`services/state_invalidation.py:10-72`）零 fixture，三条断言：返回的每个键都是 `TravelAgentState` 的真字段（最值钱——拼错字段名不抛错只静默不清空，F-07 是同款失效的另一实例）；四档清场范围嵌套单调；七个枚举成员逐行写落在哪一档——`ADMISSION_AFFECTING`/`IDENTITY_CHANGE`/`UNSUPPORTED` 三个今天都落默认全清档，各写一句注释指向 F-03，不改行为，让下一个人看见。第二步 `classify_amendment`（`workflows/intent_amendments.py:61-76`）：`IntentAmendment` 必填四字段、内部唯一外部调用是纯正则，本地写一个 `_amendment()` 构造器就够，参数化表覆盖五类输入；刻意不去借 `tests/agent_behavior/` 的 builder——那套东西同名不同义（`_identity` 在两个文件里一个返回裸 dict 一个返回 model），三个纯函数别拖进那个维护面。第三步 `_terminal_bucket` 与 `_document_has_content`：字符串进出，参数化表逐个 reason code 写期望桶，未识别值那行明确写 `is None` 并注明"这是当前事实不是期望"（与 2.1 的 `worker_failed:` 行同一手法；`_terminal_bucket` 的形状与修正见 5.2）。`claim_checkpoint_resume` 要真库，归 `tests/db/`，本批不排。

另有一条测试要写但不能挂：F-02 的两份 projection-only 词表一致性断言（"摘要再短一点"今天两处结论相反，测试今天红）。转绿要统一两张词表，而 `classify_amendment` 的结论决定 `invalidation_update` 清哪些字段、修订从哪续跑——那是路由与运行时语义变更，必须单独立项。测试先写进那张票的描述里，不合红灯进主干。

**代价与档位。** 一天。必做：F-02/F-03/F-07/F-13 能长期共存的直接原因就是这片零测试（F-09），三个纯函数是这片盲区里 fixture 成本最低的入口。落点 `tests/test_amendment_protocol.py`，新开 INV 编号挂进 invariants。

### 4.6 值得做的三条

**B-5｜invariants 门禁的收集子进程补 returncode 断言。** `test_invariants_doc.py:91-113` 起 `pytest --collect-only` 子进程但不查 `returncode`，收集期部分失败时它拿到残缺的 node_id 集合，然后报"文档点名了不存在的测试"——真因是收集炸了。本轮真实发生过一次（本机缺 reportlab 导致两个文件收集失败，门禁炸出三条不相关的不变量）。加 `assert result.returncode in (0, 5)`，三行，把一条已有门禁的误报变成正确诊断。

**B-6｜F-17 的三层切入。** 复核后收紧一格：`tools/fallback.py` 在 tests 下的 grep 命中全是别的上下文，`guardrails/`、`cli/`、`preset/` 三个子包整包零引用。切入不按行数按"失败模式是否静默"：第一层 `tools/gateway.py`（354 行，在每次工具调用路径上）——harness 已经存在，`test_temporal_tool_policy.py:62-85` 就是"真 ToolRegistry + monkeypatch + 直调 execute_tool 断言 envelope"的完整形状，先补 allowlist 拦截、manifest disabled、投毒扫描（`_scan_tool_result_for_poisoning` 是纯函数，最先做）三条。第二层降级执行路径：注册一个恒失败的 `tavily_search` 加一个成功的 `free_web_search`，断言 envelope 的 `degraded`/`original_tool`，以及 `_fallback_query_text` 把执行旋钮剔出查询正文（`fallback.py:107-109` 的注释记了"把酒店查询推到 YouTube"的实测事故，那句话今天没有任何测试）；反向一条按 4.4 的 envelope 写法。第三层 `tools/exposure_ledger.py`（纯内存类，半天全覆盖，产出进账单摘要）。`output_guard` 排最后（F-28：只服务快答一条路径）；`mcp_manager.py` 本批不排（子进程生命周期，贵一个量级），其中两块纯函数顺手带上。

**B-7｜`tests/agent_behavior/` 的 builder 整理。** 加一个 `conftest.py`，只上移形状确实一致的（`_clause`、`_rule`、`_capability`）；两对同名不同义的不合并，各自改名（`_identity_dict`/`_controlled_identity`、`_intent_draft`/`_intent_item`），让分歧在名字里读得出来。不阻止新缺陷，只降下一批测试的边际成本。

### 4.7 不做的五条

**C-9｜pytest marker 分层。** 本仓的测试选择机制已经是路径制且 CI 真在用（`pr.yml:47` 跑 `tests/ --ignore=tests/db`、`:99` 跑 `tests/db`；nightly 全量三遍，注释写明"一个偶发红灯会训练所有人忽略红灯"）；真正的跳过在 `conftest.py:53-68` 的 fixture 探测（`postgres_available`，可用环境变量升级成 fail）。`postgres` marker 只是给人看的标签——而且它已经被注册了两遍（`pyproject.toml:100-102` 与 `tests/conftest.py:32-35` 的 `pytest_configure`）。再引 marker 分层是给一个已有两套机制的地方加第三、四套。

**C-10｜同址测试。** codex 用同目录 `*_tests.rs` 换 `super::*` 访问私有项的能力——Rust 的模块私有性是编译期强制的。Python 没有这道墙：`test_run_execution_contract.py:148` 直接读 `run_control._DEADLINE_BLOCKED_WORKER_NODES`，monkeypatch 想打哪打哪。搬测试进 `src/` 只换来实现文件更挤（F-10/F-11）与打包排除的麻烦。openpi 那边同址也不是契约（`ask-user` 四个源文件一个测试、`dashboard-state.ts` 零测试），且一半是运行器单层 glob 逼出来的形状（`package.json:84`，放进子目录的测试会被静默漏跑）。本仓自己长出来的 `*_contract.py` 命名法更贴合"测的是跨文件的一条规则"这个事实。

**C-11｜syrupy 或任何快照库。** 四条。需要的 golden 四到五个，在任何快照库的盈亏平衡点以下（codex 759 个 `.snap` 里 705 个属 tui 终端渲染，本仓没有对应表面）。`--snapshot-update` 的一键便利正是快照烂掉的机制，与本仓文化相反（`docs/invariants.md:9`："修复过的事故必须永久变成测试，不允许删"）。新 pytest 插件会进 `test_invariants_doc.py:91` 的收集子进程，一个插件的收集期异常会让那条门禁报一堆假失败。本仓已有的手写 golden 先例报错质量更高——它告诉你该跑哪条命令，syrupy 的默认失败输出没有这一句。

**C-12｜覆盖率百分比门禁。** `pytest-cov` 在依赖里但三个 workflow 都没开，维持不开。本仓自己的 F-24 是反例：`services/run_diff.py` 有测试无生产调用方，被测试的死码让覆盖率虚高——百分比门禁会奖励这种测试。切入顺序按"失败模式是否静默"排，不按行数。

**C-13｜codex 的单测试二进制聚合。** `core/tests/all.rs` 把 129 个集成测试文件聚成一个二进制，是压缩编译/链接次数的成本优化，不是测试语义分层（读码笔记的原判词）。Python 没有链接期，pytest 收集开销与文件数近乎无关，本仓非 db 测试全内存跑（agent_behavior 82 个 1.45 秒）。不适用。

---

## 5. Agent 主循环与调度、编排与台账

这一组的参照物最容易照抄也最不该照抄：codex 的 submission 双队列、RAII 名额，openpi 的沙箱消息循环、两池准入——四样东西在单进程 asyncio + LangGraph 的形态下都没有对手，"不做"是本章最重要的产出（5.5）。能吸收的集中在台账语义与恢复路径的工程护栏上。先记一条更正：上一轮 F-13 说"未识别值静默不进任何桶"只对了一半——`completed`/`failed`/`cancelled` 的未识别 reason 其实会进 `unclassified_terminal_count` 兜底；真正两头都不认领的是另一类，见 5.1。

### 5.1 A-13｜给"中断但未判定"一个显式桶（必做，带行为标注）

**我们的观察。** 写方侧，`interrupted` 在审计平面不可表达：`AuditClosureStatus` 是三值 Literal（`entities/delivery_bundle.py:486`），没有第四个值；`_completion_audit_for_status`（`infrastructure/trip_run_store.py:281`，链在 `:294-328`）只覆盖 RUNNING、{CANCELLED, FAILED}、COMPLETED 三档——RUNNING 那档还把 `terminal_attribution` 显式写成 None（`:295`），INTERRUPTED 落链外原样返回（`:329`）。而恢复扫描 `_converge_running`（`services/run_recovery.py:211-252`）恰恰会把断进程的 Run 转成 INTERRUPTED（`:224-230`）。读方侧，`_terminal_bucket`（`run_completion_metrics.py:662-685`）是三个分支加 `:685` 的 `return None`（`_TERMINAL_BUCKET_KEYS` 也只有三个键，`:50-54`；顺带一条勘误：该文件 `:594` 的 docstring 自称 four allowed buckets，源码自己就在误导读者）；兜底 `_is_unclassified_outcome` 对 `interrupted` 这类状态额外要求墙钟已耗尽（`:603-605`）。叠起来：一个 interrupted 且墙钟未耗尽的 Run，`terminal_buckets` 里没有它，`unclassified_terminal_count` 里也没有它——只在分母 `authorized_run_count` 里存在。这不是 reason_code 不认识，是连 status 都没归属。而这正是恢复路径最需要被看见的时候。

**参照的做法。** openpi 的 `executionState` 是四值联合，中断显式落 uncertain（`invocation-ledger.ts:12-16`）；热路径 `terminalize()`（`index.ts:1285-1288`）与冷路径 `normalizePersistedWorkflowDetails`（`dashboard.ts:322-330`，时间戳取 max 保证不倒退）共用同一个纯函数 `classifyInterruptedInvocation`（`:348-368`，对已终态直接 throw）。关键在 uncertain 没有引擎消费者：读它的只有展示层与投递管道，引擎不据此自动重试——"标出来，但不猜"。本仓其实已有同一习惯，只是落在另一平面：`RunRecoveryStatus` 的词表里就有 `RECOVERY_CONTRACT_FAILURE`，注释是"durable 事实自相矛盾，恢复不做猜测，只留诊断"（`entities/trip_run.py:64-77`）。缺的不是概念，是它没传到度量平面。

**吸收建议。** 不动写方，只补读方。`_TERMINAL_BUCKET_KEYS` 加第四键 `interrupted_unresolved`；`_terminal_bucket` 的返回从 `Optional[str]` 换成显式判别式（桶名 / unclassified / in_flight），把 `return None` 拆成"识别不出的终态"与"还没到终态"两件事，兜底分支补一条 `logger.warning` 打出 (status, closure_status, reason_code) 三元组——现在这条路一个字都不留（F-13）。新桶判据只吃两个旧计数器都不认领的那部分：`status in _OVERDUE_UNRESOLVED_STATUSES` 且墙钟未耗尽。桶里顺带带上恢复判定的结论，零新 I/O——`_converge_running` 写 `run.interrupted` 事件时 payload 已含 `recovery_status`（`run_recovery.py:229`），而指标重算本来就在遍历 events。

核实阶段把这条的口径掰正了两处，照录。其一，"不改判决"是前置条件不是推论：`evaluate_completion_guarantee`（`:284-338`）确实不读 `terminal_buckets`（全文件只在四处出现，均不在判决函数里），但 `unclassified_terminal_count` 是它九个零容忍字段之一（字段元组在 `:310-322`）——新桶判据若多拦一格、把墙钟已耗尽的 interrupted 也吃进来，unclassified 计数就会变小，Eval 判决 `passed` 可能从 False 翻 True。所以入桶判据必须配一个穷举测试当门槛：8 个 `TripRunStatus` × 墙钟耗尽与否 × 有无 attribution，逐格断言两个旧计数器的值不变。其二，改判别式意味着 `_terminal_bucket` 的签名要动（现在只收 status 和 audit，判墙钟要多传一个入参），这是最容易写错的地方，测试先行。

【行为标注】`terminal_buckets` 是 `GET /metrics/completion`（`api/routes/trip_runs.py:391-392`）的响应字段，加键是加性变更——不碰 Agent 运行时，但不是零对外变更，PR 里写明。

**代价与档位。** 半天，全部封在一个自称 performs no I/O 的 728 行纯函数模块里。必做。

### 5.2 A-14｜`agent_status` 词表立真源，且分类集合必须是两张不是一张（必做）

**我们的观察。** 五个值散在五个文件写（completed / failed / partial / pending / ignored_after_delivery），四处读方各自重敲判据。字段本身是 `Annotated[Dict[str, str], _merge_dicts_allow_clear]`（`entities/state.py:349-351`，带 reducer，不是裸 Dict），值域无任何约束。最值得写下来的是"不在终态集合里"这一件事承载着两种相反意图：`pending` 是 itinerary_planner 故意的非终态，注释原话说骨架是半个组合、保持非终态才能把 dispatcher 引回来做物化（`itinerary_planner/node.py:3234-3238`）；`ignored_after_delivery` 同样不在集合里，语义却是"交付已封存、结果作废"（`run_control.py:846-858`）。同一个缺席表达两件相反的事，零注释、零测试（`ignored_after_delivery`、`_DONE_STATUSES` 在 tests/ 全零命中）。

**参照的做法。** openpi 把这类词表写成显式字符串联合加一张迁移表（`invocation-ledger.ts:12-16`、`isLegalTransition :250-273`、非法迁移 throw），而那个 throw 在真实控制流里永远不该触发——调用方先查合法起点再选唯一下一步，表的价值在防回归。

**吸收建议。** `entities/state.py` 模块级加 `WorkerStatus` Literal 与分类集合，`dispatcher._DONE_STATUSES` 改 import；守卫测试断言集合互斥、并集恰等于 `get_args(WorkerStatus)`、每个写点字面量是词表成员（源码扫描，样板照 4.1）。两条红线，都来自核实阶段。其一，分类集合必须是两张：dispatcher 读三值 `{completed, partial, failed}`（`dispatcher.py:29`），但另外三处读方读的是两值 `{completed, partial}`——`candidate_gate.py:1670`、`artifact_gate.py:207` 与 `:268` 都不含 failed（`:211` 对 failed 另有专门分支）。照"四处读方统一换成一个 import"去做，failed 会被两个门当成可接受状态，那是改门裁决。正确形状是 `TERMINAL_WORKER_STATUSES`（三值，dispatcher 用）与 `ACCEPTED_WORKER_STATUSES`（两值，门用）并列，注释写死两者为什么不同。其二，字段注解保持 `Dict[str, str]` 不动：`TravelAgentState.model_validate` 是 checkpoint 恢复的第二道合同校验（`travel_planning.py:828`），值上加 Literal 会让带旧值的历史 checkpoint 从可恢复变成 `CheckpointContractError`——那是本轮最不该动的路径。词表放模块级、字段留裸 str，是这个形态下唯一免费的一档。

**代价与档位。** 半天。必做：五写四读零测试，且缺席语义双关是新缺陷的产地——第五个 worker 或第六个状态值进来时，今天没有任何东西会响。

### 5.3 A-15｜`register` 补一条日志，语义测试已经有了（必做，缩版）

**我们的观察。** `RunControlRegistry.unregister`（`run_control.py:302-313`）有显式的 handle 身份守卫（`:311-312`），docstring 把它防的事故写得很清楚（按 run_id 盲删会删掉接管者的 handle，此后取消在任何节点边界都观察不到）；同类 `register`（`:292-295`）无条件覆盖（赋值在 `:294`）。`with_run_control` 读的正是 registry 里那一个 handle（`:783-794`：封存短路与 pending_supplements）。核实阶段把这条缩了范围：`tests/test_run_execution_contract.py:90-106` 已经钉住了覆盖语义——`:99-100` 对同一 run_id 连续 register 两次、`:104` 断言 get 返回后者。所以"配测试写下当前语义"这半已经存在，只剩可见性那半。

**参照的做法。** codex 在 `Mutex<Option<ActiveTurn>>` 的两个插入点前都放 `debug_assert!(turn.task.is_none())`（`tasks/mod.rs:347`、`:359`，`turn.task` 的赋值全仓只有 `:437` 一处），不变量写在结构体注释里（`session/session.rs:39`）。这是 codex 那套所有权切分里唯一能原样搬来的一条。

**吸收建议与代价。** `register` 在覆盖一个已存在且未取消的 handle 时 `logger.error` 打出被顶掉的 handle，不抛异常（抛会改行为）。十行，一小时。必做——成本比它挡的事故（一个观察不到取消的 Run 跑满墙钟）低两个数量级。

### 5.4 A-16｜冷热两条 checkpoint 探测路径共用同一个异常分类器（必做）

**我们的观察。** 热路径 `probe_checkpoint`（`travel_planning.py:802-843`）很讲究：探测抛错先过 `_is_checkpoint_contract_failure`（`:108-112`），不是合同失败原样重抛（`:815-816`）。冷路径 `run_recovery._resume_verdict`（`:283-298`）的 `except Exception`（`:290-295`）把一切异常收敛成 `checkpoint_contract_mismatch`，落库成 `recovery_status = NON_RESUMABLE`（`:215-222`），而 `chat.py:402-412` 读到它就永久拒绝续跑。一次数据库抖动因此被记成"合同读不懂这个 checkpoint"，用户看到"请重新规划这趟旅行"。严格的语义在热路径，宽松的在决定 durable 结论的冷路径——装反了。

**参照的做法。** openpi 冷热两条中断分类路径共用同一个纯函数（5.1 已引），保证进程正常打断与崩溃后重启发现两种触发不产生不一致的终态语义。

**吸收建议。** `_is_checkpoint_contract_failure` 提到两边都能 import 的位置（新建 `workflows/checkpoint_contract.py`；直接从 `travel_planning` import 会让恢复扫描依赖图定义文件，不取）；`_resume_verdict` 按它分流 reason：合同失败仍是 `checkpoint_contract_mismatch`，其余记 `checkpoint_probe_failed`，`recovery_status` 两种都仍是 `NON_RESUMABLE`。为什么不是行为变更：拒绝续跑的判据读的是 status 不是 reason，而 `recovery_reason` 的全部消费者是两个展示字段（`api/schemas.py:280`、`api/routes/trip_runs.py:235`，全仓 grep 核过）。顺带把 `run_recovery.py:291-293` 的日志补上异常类型名——现在只打消息文本，两类异常分不开。

**代价与档位。** 一次搬移、一个 if、一行日志，两小时。必做：它把"数据库抖一下、用户永久失去续跑"从静默归类换成两条可分辨的记录，是 F-08 同根问题在恢复扫描侧的另一半。

### 5.5 不做的五条：形态差异的正面论证

**C-14｜codex 的 submission/event 双队列。** 那层解耦买的是"turn 在跑时还能接新指令"。本仓已有等价物且是持久化版本：`trip_run_commands` 表 + `RunCommandCoordinator.poll_once()` + `RunControlHandle.wake_event`。表版本在"进程死掉"这一维严格更强——`chat.py:1022-1025` 在协调器 start 之前先 `poll_once()`，注释写明上个进程死前落库的命令必须在第一个边界就生效，bounded channel 做不到这条。指令词表也是刻意收窄的（`RunCommandType` 只有 CANCEL/SUPPLEMENT，`entities/trip_run.py:96-105` 的 docstring：没有消费者的命令类型只会让状态机多一条永远 pending 的分支）；对照 codex 的 `Op` 枚举已长到让调度层认识审批这层领域概念。再造进程内队列的具体坏处：命令出现两个真源，而"取走不等于清空"（`pending_supplements` 的 docstring，`run_control.py:243-249`）这条语义靠表与内存的一对状态实现，多一层队列就多一处要对齐的中间态。

**C-15｜RAII 名额。** Python 的等价物是 `async with`，本仓 `ChannelGate.hold`（`utils/concurrency.py:57-88`）已是这个形状——释放在 finally 里，异常与正常同一出口，没有 codex 那个 panic 缝隙（`SessionTask::run` 内 panic 时名额要等下次用户动作走 100ms 超时分支才清掉）。"至多一个运行中 turn"在本仓有更强载体：DB 执行租约加 CAS，跨进程有效；codex 的 Mutex 只在单进程内有效。再引进程内计数器只会多一份可能与租约不一致的事实。唯一值得抄的是那两句 debug_assert，已写成 5.3。

**C-16｜openpi 的沙箱子进程与 IPC 消息循环。** 它的存在理由是执行的控制流本身不可信——模型现写的 JS 需要进程边界围起来。本仓图形状授权前完全确定、模型不编排图（设计层前提，上一轮 §7.8 已判），没有不可信控制流就没有要围的东西；引入进程边界还会把 `run_control.py` 那六个 contextvar 全部作废——归因、预算、分窗、取消检查都挂在上面，跨进程一个都传不过去。顺带一次核对（openpi 读码笔记提示的）：openpi 把预算计费点刻意放在 `controller.schedule()` 入口而不是缓存命中处，本仓对应的计费点在 `models/router.py:504-523` 的 `_in_channel`（先墙钟、再并发门、再发请求），Provider 快照缓存命中的路径压根不经过 router——计费点已经在对的位置上，无需动作。

**C-17｜openpi 的两池两准入哲学。** 那边 workflows 排队、subagents 满即拒，是两类调用方性质不同。本仓只有一个池（`ChannelGate`），准入哲学"排队时长由 Run 的剩余墙钟定界"在墙钟封存形态下是唯一自洽的一种，理由已写在两处 docstring（`router.py:505-510`："等不到位置和调用本身太慢对一个 Run 是同一件事——窗口关了"；`concurrency.py:57-63`："在这里再写一个数就是给同一个问题两个答案"）。要做的只有半小时的一件小事：给这条判据补一个 INV 编号，让 invariants 门禁保证这句话不被删。

**C-18｜journal 按内容哈希做重放键：不加、不预留。** 三条理由。本仓已有同构实现在更该在的那层——`ProviderSnapshotScope.cache_key_digest`（`provider_snapshot_cache.py:200-203`，`_canonical_json` sort_keys 加 sha256）连 openpi 把验收合同编进重放键的决定都有对应物（scope 含 `provider_contract_version`/`payload_schema_version`，`:142-143`），`_validate_reuse_boundary`（`:193-198`）就是 `isReplaySafeAgentCall` 那层资格白名单——Provider 事实层才是重跑成本最高、最值得缓存的地方。补研轮真要重放，键的原料早在 `ResearchPacket` 的七个身份字段里，预留哈希字段是给不存在的问题付利息。openpi 那把哈希解决的是无 barrier 流水线乱序（`journal.ts` 文件头写明），本仓补研轮严格串行经过 candidate_gate，乱序不存在，哈希没有对手。真要做补研重放，落点是给 `ProviderSnapshotScope` 加 worker 维度，不是在图上新建台账与两份预算账本竞争真源。

### 5.6 值得做的四条

**B-8｜`PacketStateKey`：把复合键的四份正则收成一个类型（值得做，带硬前提）。** `research_packets` 的键 `f"{worker_key}@{generation_id}"` 被三处独立解析，轮次后缀正则有四份，其中两份数轴不同：`assignment_research_round`（`agents/utils.py:389-391`）返回 N-1、无后缀记 0；`_latest_packets`（`candidate_gate.py:244-260`）把同一个 N 当 round_number、无后缀记 1。没有任何地方说明差别。openpi 的对照是重放键只有一个函数（`journal.ts:56-80` 的 `agentCallKey`，进什么不进什么写在接口上，label/phase 永不参与）。建议在 `state_invalidation.py` 加 frozen dataclass `PacketStateKey(base, round_number, generation_id)` 带 render/parse，三处解析换调用，两个数轴各自改成显式换算并在 docstring 写明差别。硬前提（核实阶段点名）：这两个函数的输出决定 candidate_gate 看到哪份 packet 与补研轮号，换算写错直接改门输入——先落一张"同一批 key 输入、四个函数当前输出"的基线表驱动测试，再动手，不是可选项。

**B-9｜包装层两处逐字重复的短路判据提成纯谓词。** "交付已封存就丢弃"的三段条件与两键载荷在 `run_control.py` 同一个闭包里写了两遍（进入前 `:784-793`、返回后 `:847-858`，逐字相同）；`divert_to_amendment_router`（`:820-825`）同样内联。而同文件的分窗/短路链已经全部提成可单测的纯函数（`:658-731` 四个）——留在闭包里的恰好是没测的。提成 `_delivery_sealed_for`/`_ignored_after_delivery_update`/`_should_divert_to_amendment_router` 三个纯函数，两处调用各变两行。约 40 行，提函数与两处替换必须同一次改动完成，防止判据分叉。openpi 的对照是 controller（有状态资源所有者）与 coordinator（零状态纯判据）切在文件级。

**B-10｜checkpoint 探测的名实之辨（值得做；第二条是行为票）。** `probe_checkpoint` 的 docstring 写明 id 必须来自决定可恢复性的同一次读（`travel_planning.py:805-810`），但 `safe_checkpoint_id` 实际从不进图的 config——`configurable`（`:952-960`）里有 thread_id、plan_gate_enabled 与五个 store/recorder，没有 checkpoint_id；恢复实际从"此刻最新"续跑，名字承诺的 pin 不存在。教义被绕开得最明显的一处是核实新补的：`chat.py:910-921` 有第二次 probe 加 `mark_safe_checkpoint`——与"必须同一次读"正面冲突。三件事：局部变量与字段注释改名成 observed_checkpoint_id 并写清"审计用、不是恢复 pin"（纯改名）；补一个测试钉住"available=True 而 checkpoint_id=None 是允许的组合"（`:838-843` 两个判据来源不同步）；`chat.py:413` 的 `getattr(..., "probe_checkpoint", None)` 换成直接属性访问——【行为标注】这条会把"方法改名"的症状从 409"未找到 checkpoint"变成 AttributeError/500，是有意的失败提前，但属行为变更，单独立项（全仓只有一个实现，仅在改名时触发）。

**B-11｜`claim_checkpoint_resume` 的跨实现合同测试（钉 F-04 的护栏半边）。** 两个 store 实现各有一份默认值与绕过迁移矩阵的 CAS（`trip_run_store.py:1168` 与 `:2115`）。F-04 的修复（allowed_statuses 收回实体层）是行为票，本条只做护栏：参数化测试对两个实现跑同一组断言——allowed 里每个状态到 RUNNING 的迁移在 `ALLOWED_STATUS_TRANSITIONS` 里合法；调用方实际传的两个集合是 `_RESUMABLE_STATUSES` 的子集。今天两条都绿（CREATED 只是多在实体表里没被用），钉的是下一个人加状态或换调用方的那天。两小时。

---

## 6. 错误分类与恢复链、可观测性

先立一条贯穿本章的判断：我们缺的不是"引入 codex 的错误模型"，是把仓库里已经做对的三个样板再用一遍——`ProviderFailureSignal`（packet 内 typed 失败证据，`candidate_gate.py:157-162`）、`RunBudgetConfig → RunBudgetSnapshot` 的授权时封存链、`test_run_execution_contract.py` 的双向集合守卫。还有一条要先说的观察：candidate_gate 这一侧的字符串协议其实已经被降级成兼容层了——`_failure_signals`（`candidate_gate.py:176-241`）优先读 packet 里 `lifecycle_status == "rejected"` 的服务端记录，`last_error` 只在 typed 证据为空且失败 worker 唯一时才被当桥用，为什么必须加这道限制写在 `:1679-1685` 的 docstring 里（"last_error……是 latest-nonempty 归并，分不清并发失败"）。真正还在裸读字符串的是 artifact_gate 的三处（`:212-213`、`:228-229`、`:246-247`）。全仓最脆的一点值得单独记下：`itinerary_planner/node.py:3731` 失败时写 `str(exc)` 进 `last_error`，`artifact_gate.py:246-264` 据 `is_provider_or_model_failure` 决定买不买修复轮（不命中则经 `:266-275` 的 workspace 校验落 `:276-284` 的 integrity 结果，reason_code 是 `required_workspace_artifact_missing`）——而 `_TRANSIENT_MARKERS` 里有 "connection"、"timeout"、"upstream" 这类任何异常文案都可能出现的词。一次组合失败的异常消息里有没有 "connection" 这个词，决定这个 Run 还有没有一轮修复机会；`node.py:3733-3736` 的注释自己承认 `last_error` 是共享通道，结构化原因已经另写进 `composition_failure_context`，只是门不读它。

### 6.1 A-17｜失败分类的穷举金标准表，以及为什么不升枚举（必做）

**参照的做法。** codex 的可用之处不是"四层类型"，是两件事。一是顶层 variant 只管类别、诊断字段下沉 payload，`is_retryable` 只对 variant 判别不解构载荷（`protocol/src/error.rs:364-404`，本轮逐行核实无 `_` 分支：24 个 false、11 个 true、两个 Landlock 单独 false）。二是同一个错误在不同后果问题上允许相反答案、各一张表：`RetryLimit` 在 `is_retryable` 是 false（`:380`），在"换模型有没有用"那张表里是值得重试（`compact_model_fallback.rs:18`）；`affects_turn_status`（`protocol.rs:1817-1836`）是第三张同构表。还有一条负面证据：在 codex 的错误处理链路里 grep 不到任何"读错误文案决定分支"的生产代码，`error_tests.rs:14-33` 反而逐字符钉 Debug 输出——文案是给下游日志解析的契约要钉住，控制流一律走类型。这两件事在 codex 里是分开的，在我们这里是同一件。

**吸收建议。** Python 逼近"新增分类必须声明后果"的现实方案不需要枚举：`typing.get_args(ProviderFailureCategory)` 直接返回三个成员（实测，Literal 在 `provider_failure.py:15`），写方六前缀已有可遍历的 `_KNOWN_PREFIXES` 元组，且 `get_args` 在本仓已是惯用法（`config/schema_export.py:31`、`config/env.py:68`）。金标准表四条内容（落 `tests/test_failure_taxonomy_contract.py`，即 2.1 配套测试的完整版）：六前缀 × `classify_provider_failure` 断言 (category, reason_code) 二元组，顺带钉住 `schema_gate:` 先看文本 transient marker 的顺序语义（`:116-125`）；六前缀 × `is_provider_or_model_failure` 断言布尔——`worker_failed:` 那行写当前值 False 并在断言消息指向 §4.4 缺陷一，把没人知道的矛盾变成有人签过字的事实；未识别前缀断言落 `("incomplete", "provider_incomplete_result")`（`:166-169`），测试名写明这是墙钟轴上的 fail-open（缺陷二）；两份 query-miss 词表的差集断言恰为 `{"no results", "empty result"}`——不预设哪边对，只保证差异不能被顺手抹掉。

反方向的红线同样承重：不要为了更像 codex 把这个 Literal 升成 `str, Enum`。实测 Python 3.11 下 `f"{X.MEMBER}"` 产出类名而非成员值，而 `.category` 被 f-string 插进 `failure_signature`（`candidate_gate.py:233`、`:1713`），那个串是持久身份——逐值比对（`:2347-2348`）后进 `completion_audit`（`entities/trip_run.py:801`）。升枚举会静默改写持久身份串，正是硬约束禁止的改动。仓里的 `GateDisposition` 之所以安全，是它只经 Pydantic 序列化落地、从不进 f-string——同一个"升枚举"动作在两处一处安全一处危险，区别就在这。

**代价与档位。** 一天，纯新增。必做：§4.4 缺陷一、二、四直接背书（复核确认该协议在 tests/ 仍零命中）。搬移本体见 2.1，这条测试与它同 PR。

### 6.2 A-18｜run 级视图：不新建账本，接通三个已写好的死 DTO（必做）

**我们的观察。** 先修正上一轮底稿的一处：门决策是持久的。`gate_failure_attributions` 被投影成十个字段进 `completion_audit`（`entities/trip_run.py:793-804`），落 `trip_run_states` 的 jsonb 列（真正写库在 `trip_run_store.py:930`、`:942`），docstring 自陈这份投影"足以在进程重启后重算全部零容忍指标"（`:649-656`）——前提是走完授权（`:660-661`）。真正的缺口更精确：模型调用、工具调用、门决策三块各有一个写好的只读 DTO 和读方法，三个全部零路由（`RunCostResponse`/`ToolAuditListResponse`/`TripRunCompletionDiagnosticsResponse`，`api/schemas.py:577/:515/:396-401`；`cost_ledger_store.list_calls`、`tool_audit_store.list_by_run` 零调用；`trip_runs.py` 的 16 个 `@router` 无一引用这三个 response_model）。第三条最能说明问题：`GET /trip-runs/{run_id}` 用的 `TripRunStateResponse` 里没有 `completion_audit` 字段，而专门为它写的 DTO 一次没被用过。有人设计过这个 run 级视图，最后一段没接完。现在实际的成本视图走另一条路（run 终结时拼裸 dict 经 SSE 推送，`chat.py:622-661`），"终结时推送"与"事后可查"是两套互不相干的实现，后者没通电。

**参照的做法。** codex 分两本账且分账依据清楚：rollout 是面向恢复会话的白名单账本（错误事件显式不入账，`rollout/src/policy.rs:136`），rollout-trace 才是取证账本（完整 payload 落盘，环境变量开关、默认关、README 明写当敏感文件对待）；两本账的 wire format 都有往返与 schema 契约测试钉住。openpi 是一个 run 目录四个文件、读入口唯一且逐字段防御性 normalize。对照我们：数据不缺（三张 DB 台账都 typed 都在写），缺的是读路径。

**吸收建议。** `GET /trip-runs/{run_id}/audit`，`RunAuditResponse` 三个字段拼三个现成 DTO，调两个现成读方法加一列现成 jsonb——零新表、零新写路径、三个死方法三个死 DTO 全部通电。授权面注意一条（核实阶段提示）：`TripRunCompletionDiagnosticsResponse` 的 docstring 自称 Developer/Eval-only，接路由时与其余 16 条同一套授权，别把 Eval 视图开成产品面。配一条 drift guard（openpi 手法）：扫描 `api/schemas.py` 全部 `*Response` 类，断言每个都被 `response_model=` 或嵌套引用消费，例外进显式豁免表——立刻抓出这三个，此后不再攒新的死 DTO。

**代价与档位。** 一天。必做：这是全部建议里唯一"把已花掉的实现成本变现"的一条，不接的代价是每次排障手工 join 三处（其中一处 jsonb）。

### 6.3 A-19｜tool_audit 的幂等策略对齐 cost ledger，连挂载点一起改（必做）

**我们的观察。** 两个紧邻的账本对"同 id 重复写"策略相反（F-36）：cost ledger 内容不一致即抛 `CostLedgerConflict`（`cost_ledger_store.py:363-373`）；tool_audit 命中同 id 直接返回旧行，不比对不告警（`tool_audit_store.py:194-201`）。判据不是哪个更严，是这个 id 谁生成、重复意味着什么：cost ledger 的重复写是预期路径——落库失败时 `usage_recorder.requeue(batch)` 重放整批（`chat.py:624-626`，注释明言 record_calls 幂等），同 id 必然再来，内容不同说明 id 生成有 bug，抛是对的，且 cost 直接进预算裁决；tool_audit 没有 requeue 路径，同 id 再来本身就不该发生，静默复用把异常事件当正常处理。统一成吵的那种。

**吸收建议（按核实修正后的完整形状）。** store 侧：取旧行、用显式列出参与比对列的 `_audit_identity` 比对——不含 `created_at`，也不含 `run_id`（`tool_execution_audits.run_id` 是 ON DELETE SET NULL，父 run 删除后的合法重放不该炸）——相同幂等返回，不同 `logger.error` 加 `raise ToolAuditConflict`；`InMemoryToolAuditStore.record_envelope` 的同分支同改。挂载点必须一起动，否则白做：`record_envelope` 的唯一调用者不是 `execute_tool` 本身，是 `tools/gateway.py:337` 的 `_record_audit_safe`，它 `:343-344` 的 `except Exception → logger.warning` 会把新异常降成一句 warning。审计失败不该带崩工具调用（这个可用性选择保留），所以改法是给 `ToolAuditConflict` 单独一个 except 分支记 `logger.error` 并带上新旧两行的差异摘要——其余异常仍走 warning。这样可见性拿到了，可用性语义一字不变。

**代价与档位。** 约 30 行加两条测试（同 id 同内容幂等、同 id 异内容抛并在 gateway 层记 error）。半天。必做，F-36 背书；顺带把"两边都没有测试逼你去对比行为"这个 F-36 的根因一起填掉。

### 6.4 A-20｜`NODE_PHASES` 接真源加双向守卫；补门那半是行为票（守卫必做）

**我们的观察。** `trace.py:20-50` 的表仍是手写字面量、未接 `node_names`（`510d5236` 没覆盖到它），23 个键对图上 22 个节点：表侧多 `fast_answer_agent` 与 `workflow` 两个非图条目，图侧缺 `intent_fidelity_gate`——F-31 仍成立，这道门的事件落进兜底 `postprocess`，与信封条目混在一个桶。

**吸收建议。** 守卫今天就能挂，但必须用豁免表写法，否则第一天就是红灯（核实阶段点名分析稿没把这个二选一说出来）：断言 `set(NODE_PHASES) - {NODE_FAST_ANSWER, "workflow"} == set(graph.nodes) - {NODE_INTENT_FIDELITY_GATE}`，两个豁免各带一行理由——前者是非图条目，后者引 F-31"已知缺失，修复票见缺陷轨"。同时把表的键换成 `node_names` 常量（纯搬移）。修 F-31 本身——补一行 `"intent_fidelity_gate": "verification"`——是行为票：phase 值落库进 `trip_run_events`（`chat.py:1159-1162`）并出现在 `GET /trip-runs/{run_id}/events`，`trace.py:1-6` 又自称 API/SSE 契约；两位核实员对"是否影响 SSE 流"读法不一（一说 trace 事件不走 SSE、一说走），合入前现场确认一次即可，无论哪种都属可观测契约变更，单独提交并更新守卫豁免表。

**代价与档位。** 守卫半天、必做（F-31 是 F-32 那族手写表里唯一已知出过错的一处）；修复另立行为票。

### 6.5 值得做的四条

**B-12｜typed `worker_failure_kinds` 收窄字符串桥（带行为标注，排期在 F-01/F-06 修复之后）。** 不删 `last_error`（删它动 reducer、四门读点、SSE，风险最高）；让 typed 通道多盖一段，形状抄 candidate_gate 已在用的"typed 优先、字符串兜底"。落法：state 加 `worker_failure_kinds: Annotated[Dict[str, str], _merge_dicts]`（键 agent_key，dict 载体下并发归属丢失的问题自然消失）；`format_worker_last_error` 内部本来就算出了分类（六个 return 分支），改成同时返回 (kind, text)，三个 worker 一次写两个字段；artifact_gate 三处读点各加 typed 前置分支、不删旧分支。【行为标注】加前置分支本身就是改判定入口——typed 与字符串判定不同答的案例，门的裁决就换值。闸门是一条差分测试：同一批构造异常，断言两条路给出同一个分类，不同答的案例先不切。配套一条明确的不做：不把 itinerary_planner 接进 `format_worker_last_error`——接进去会给 `str(exc)` 打上前缀，`artifact_gate` 的判定随之改变；planner 的结构化失败原因该走它自己的 `composition_failure_context`，让门读那个字段是本条落地之后的事。

**B-13｜`ClassifiedFailure` Protocol 与未分类异常的显式清单（不立公共基类）。** 全仓 51 个顶层异常类、三种基类、6 个裸 Exception，无选型文档。真正有工程后果的不是没有基类，是捕获面不对称：`DeliveryProjectionError` 有 13 处 raise、全仓零处按类型 except，与 `DeliveryPresentationError` 一起落进 `chat.py:1510-1527` isinstance 分派链的 else，记成 `unclassified_workflow_failure`，与真 bug 无法区分；而 `DeliveryContractViolation` 自带机器可读 `reason_code`/`gate_class`，是我们自己的正确样板。落法三步：`runtime_checkable` 的 `ClassifiedFailure` Protocol（不改任何基类）；两个交付异常加可选 `reason_code` kwarg（基类仍是 ValueError，`except ValueError` 行为不变），13+1 处 raise 补命名空间化的码；一条守卫扫描满足 Protocol 的异常类、断言每个都在分派链有分支，例外进豁免表并注明"已知落 unclassified，见 F-13"。本轮不接入分派链——那是 F-13 的行为修复票；先补守卫的理由是它产出的豁免表就是后两步的工单。

**B-14｜两个恢复链预算进 `RunBudgetConfig`/`RunBudgetSnapshot`（带行为标注）。** 六个恢复链参数五种载体，其中 `max_tool_retries_per_target` 已在授权封存链里，而 `MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS = 3`（`composition_repair.py:33`）与 `_MAX_TARGETED_RESEARCH_ATTEMPTS = 1`（`candidate_gate.py:99`，注意它是下限，`_domain_research_budget` 只向上放宽）是模块常量——改配置立刻影响在跑的 Run，恰好违反 `RunBudgetConfig` docstring 自己立的规矩，而同规矩下的第三个参数守住了。迁移三个硬点：新字段必须带默认值（`RunBudgetSnapshot` 是 StrictModel，必填字段会让旧 checkpoint 反序列化失败）；模块常量不删、作为未封存路径的回落（快答等 `peek_ledger` 为 None 的路径）；`RUN_BUDGET_POLICY_VERSION`（`run_budget.py:42`）要一起递增——加维度不动版本号，同一个版本号就对应两种字段集。【行为标注】默认路径逐字不变，但配置化本身是有意的功能扩张：从此改一行 YAML 就能改门裁决与模型调用轮数，档位说明里明写。附带的两条不做：`execute_tool(max_retries=2)` 不进 config——它与 `max_tool_retries_per_target` 是同一件事的两个 owner，`run_budget.py:143-152` 记着一次判记分离的真实 bug；该做的是把 `fast_answer/node.py:515` 那个 `max_retries=1` 写成具名常量加一行理由，十分钟。"参数注册表"也不立——没有消费方的集中表只会变成第七张要同步的手写表。

**B-15｜三件小的：事件类型枚举、trace 文档对齐、F-38 的修法方向（修正版）。** 其一，`TripRunEvent.event_type` 立 `TripRunEventType(str, Enum)`，十余种字面量分散在六个文件；写方改枚举、落库字节不变、读方不动、payload 不做 schema（每种一个 TypedDict 的维护成本高于收益）；注意 6.1 那个 f-string 陷阱——写方必须传 `.value` 或把参数类型收成枚举。其二，`trace.py:1-6` 的 docstring 说"not a durable run log"，而 `chat.py:1159-1162` 对每个 trace 事件都落库、`api/sse_projection.py:52-53` 的注释也承认——docstring 与实现矛盾，想验证 trace 是否持久的人第一屏读到错的答案，十分钟改掉（F-20/F-39 同族）。其三，F-38 的修法方向要按核实结果修正：原稿建议把 `install_query_secret_redaction()` 从 `amap_route_search.py:50` 挪去日志初始化入口，核实指出这会降低可靠性——`:47-49` 的注释写明 import 时安装保证"本模块发出第一个请求之前 filter 已在"，挪走后任何绕过日志初始化直接 import 的路径（脚本、单测、工具直调）会裸奔。正确方向是加不是挪：保留 import 时安装，日志初始化入口再挂一遍（幂等），补一条测试断言配置日志后 httpx logger 上有这个 filter。

### 6.6 不做的四条

**C-19｜仓库级公共异常基类。** 51 个类绝大多数的消费方就是紧邻几行的 `except SomeError`（Rail12306Error 族、WeatherProviderError 族都是这个形态且工作正常）；没人会写 `except JourneyPilotError`，真写了等于回到裸 Exception。改基类还有实际风险：`ValueError` 子类改继承新基类，上游的 `except ValueError` 就不再捕获它，而那 13 处 raise 的调用面没有穷举过。收益零、风险非零。F-35 想要的东西由 B-13 的 Protocol 给，不动继承树。

**C-20｜接 OpenTelemetry。** 全仓零观测栈依赖（实测 grep，唯一命中是一句中文注释）。codex 接 otel 的收益来自把大量客户端遥测汇到自家后端（连 Statsig 客户端密钥都硬编码在源码里），我们单机单用户没有汇聚方，第一个 exporter 只能指回本机——本机已有文件日志。更要紧的是它一行都不解决我们的真缺口：读路径没接（6.2）与手写表漏项（6.4）。span 打点还会把观测完整性变成"开发者记不记得打点"，而 `WorkflowTraceEvent` 已在每个节点边界结构性覆盖。

**C-21｜新建 run 级账本，或 rollout-trace 式全量 payload 落盘。** 数据不缺（三张 DB 台账 typed 且在写），新账本要新表、新迁移、新结构指纹（INV-DB-002 门禁），成本远大于收益；rollout 要解决的"跨会话恢复对话历史"我们没有这个用例。全量 payload 落盘会把脱敏问题从日志过滤器（F-38 已证明这层会被绕过）升级成落盘文件；真要做，抄 codex 的开关哲学（环境变量、默认关、README 写明当敏感文件对待），排在所有观测工作之后。

**C-22｜（并入 B-14 的两条附带不做，此处只留索引）** `execute_tool` 的调用内重试次数不进 config；恢复链参数注册表不立。理由见 B-14。

---

## 7. 三档汇总与动手顺序

编号沿正文：A 必做、B 值得做、C 不做。带 ★ 的条目有【行为标注】——仍然该做，但 PR 必须点名它改了什么对外可见或运行时语义，不许搭纯搬移的车。

### 7.1 必做（20 条）

| # | 一句话 | 落点 | 代价 |
|---|---|---|---|
| A-1 | 失败协议前缀与词表提成零依赖叶子 `agents/failure_protocol.py`，TID251 锁边界，三条红线（query-miss 双名、外部信号前缀显式派生、casefold） | 2.1 | 半天 |
| A-2 | state 字段所有权表 + AST 写点扫描守卫（74 字段/134 对实测，盲点 fail-closed） | 2.2 | 1-2 天 |
| A-3 ★ | `TravelAgentState` 加 `extra="forbid"`（构造面），当场抓出 6 处错字段名；与 A-2 成对才闭合 | 2.3 | 半小时 |
| A-4 | plan_gate 约 300 行搬出图定义文件到 `workflows/plan_gate.py`（task_id 不含模块名，在飞 interrupt 不受影响） | 2.4 | 2 小时 |
| A-5 ★ | `_AGENT_TOOL_POLICY` 迁 `configs/tool_policy.yaml` 走严格校验（新增启动失败模式要点名；`_WORKER_AGENTS` 保持 import 期求值） | 3.1 | 1 天 |
| A-6 | 工具同名注册先做冲突可见性（registry 记账 + warning + 健康检查面）；硬失败另立行为票 | 3.2 | 1 小时 |
| A-7 | research packet 的 prompt 快照（占位符 + "schema 注入未断"断言 + CLI 生成器），修复轮 separators 共享常量 | 3.3 | 半天 |
| A-8 | 修守卫样板：`test_run_execution_contract.py:131` 重新锚回真实图（基线变化后已退化成同源互测） | 4.1 | 半天 |
| A-9 | 图内省守卫：修订续跑表 + dispatcher 路由值（常量化与测试同 PR；AST 扫描防三元假阳性） | 4.2 | 1 天 |
| A-10 | `_AGENT_TOOL_POLICY` 键集 ↔ `WORKER_NODES` 双向守卫 | 4.3 | 半天 |
| A-11 | `_FALLBACK_MAP` 四条静态断言 + 注册面声明表（被拦分支断 envelope 不断 raises） | 4.4 | 1 天 |
| A-12 | 修订协议三个纯函数的穷举测试（F-09；F-02 一致性测试写进行为票描述、不合红灯） | 4.5 | 1 天 |
| A-13 ★ | 完成率指标加 `interrupted_unresolved` 桶，`_terminal_bucket` 换三态判别式（穷举测试保证两个旧计数器不变；响应加键点名） | 5.1 | 半天 |
| A-14 | `agent_status` 词表立真源，分类集合必须两张（dispatcher 三值 ≠ 门两值）；字段注解保持 str | 5.2 | 半天 |
| A-15 | `RunControlRegistry.register` 补覆盖告警（语义测试已存在，只缺这半） | 5.3 | 1 小时 |
| A-16 | 冷热 checkpoint 探测共用 `_is_checkpoint_contract_failure`，reason 分流（DB 抖动不再被记成合同不匹配） | 5.4 | 2 小时 |
| A-17 | 失败分类穷举金标准表（`get_args` 路线，零类型改造；不升枚举——f-string 会改写持久身份串） | 6.1 | 1 天（与 A-1 同 PR） |
| A-18 | `GET /trip-runs/{run_id}/audit` 接通三个零路由的死 DTO + 死 DTO drift guard | 6.2 | 1 天 |
| A-19 | tool_audit 幂等策略对齐 cost ledger，连 gateway 挂载点一起改（identity 不含 run_id） | 6.3 | 半天 |
| A-20 | `NODE_PHASES` 接 `node_names` + 豁免表守卫（今天绿；补门那半是行为票） | 6.4 | 半天 |

必做档的共同判据：每条都有 F-xx 或 comparative-study §4.4 定案背书，且都是"不做就继续产新缺陷"的结构缺口。二十条里十七条是纯新增（测试、守卫、日志、端点）或纯搬移；三条带 ★ 的有明确圈定的行为面，标注的意思是要点名，不是要犹豫。

动手顺序建议三批。第一批是守卫族（A-8 先行，然后 A-9/A-10/A-11/A-12 共用图内省，加 A-1+A-17 的协议叶子与金标准表）——全部纯新增，一周内清完；A-15、A-16、A-19 三个小修随时插队。第二批是结构搬移与配置（A-4、A-7、A-5、A-6），每个都是独立 PR。第三批是台账与观测（A-13、A-14、A-18、A-20），其中 A-2+A-3 成对做、排在有人能腾出一两天专注核表的时候。

### 7.2 值得做（15 条）

| # | 一句话 | 落点 |
|---|---|---|
| B-1 ★ | `_DEEP_WORKER_NODES` 收进 `node_names`（SSE 分帧集合从此跟 WORKER_NODES 走，commit 里写明） | 2.5 |
| B-2 ★ | 降级表与推荐表的注册面守卫接 MCP 初始化（首轮只报告；清死键是模型调用面变更、归缺陷轨） | 3.4 |
| B-3 | `mcp_defaults` 收尾：先一行自述修正；YAML 切半可选（实质收益 6 处 Key 名重复） | 3.4 |
| B-4 | 候选上限守卫（一条今天绿，一条 xfail 钉住 6 vs 4） | 3.4 |
| B-5 | invariants 门禁收集子进程补 returncode 断言（真实误报已发生过） | 4.6 |
| B-6 | F-17 三层切入：gateway → 降级执行路径 → exposure_ledger（复用现成 harness） | 4.6 |
| B-7 | `tests/agent_behavior/` builder 整理：一致的上移，同名不同义的改名不合并 | 4.6 |
| B-8 | `PacketStateKey` 收掉四份轮次正则与两套数轴（硬前提：先落四函数输出基线测试） | 5.6 |
| B-9 | 包装层两处逐字重复的封存短路提成纯谓词（提函数与替换同一次改动） | 5.6 |
| B-10 ★ | checkpoint 探测名实之辨：改名 observed_checkpoint_id + 组合测试；getattr 换直接访问是行为票 | 5.6 |
| B-11 | `claim_checkpoint_resume` 跨两个 store 实现的合同测试（F-04 的护栏半边） | 5.6 |
| B-12 ★ | typed `worker_failure_kinds` 收窄字符串桥（差分测试当闸门；排 F-01/F-06 修复之后） | 6.5 |
| B-13 | `ClassifiedFailure` Protocol + 未分类异常显式清单（不动继承树；不接分派链） | 6.5 |
| B-14 ★ | 两个恢复链预算进 RunBudget 封存链（默认值防旧 checkpoint；POLICY_VERSION 递增；配置化=功能扩张要明写） | 6.5 |
| B-15 | 事件类型枚举、trace docstring 对齐、F-38 加第二挂载点（不挪原位） | 6.5 |

值得做档的理由分三类：依赖别的票先行（B-2、B-12 等在缺陷轨后面），收益比必做小一个量级（B-3、B-7），或者钉的是尚未出过错的表（B-4、B-11）。

### 7.3 不做（21 条）

| # | 不做什么 | 一句话理由 |
|---|---|---|
| C-1 | import-linter 分层契约 | 写不出诚实的契约（第一天十几条豁免）；TID251 逐条禁令够用；codex 自己也没有这层工具 |
| C-2 | 顶层 `protocol/` 包 | 同一模式已有落法（包内叶子），再开顶层包是一个模式两种落法；`entities/__init__` 的 960 模块教训 |
| C-3 | core-api 式 re-export 门面 | codex 自己的 50+ 生产 crate 都绕过它；我们没有外部 SDK 消费者场景 |
| C-4 | `assert_never` + mypy 门禁 | 无类型检查门禁的 assert_never 只是运行时 raise；codex 的六态穷举其实也靠一个手写方法自保，测试等价实现代价低三个量级 |
| C-5 | 拆 `TravelAgentState` 子模型 | channel 在字段层展平，拆完 channel 面不变、只多一层 mapping；真问题由 A-2/A-3 解 |
| C-6 | 执行顺序迁配置 | 它是图拓扑，迁了等于配置改路由；两个参照都没把执行顺序做成配置；改做三处一致性守卫 |
| C-7 | prompt 整体外置 | 14 处插值 + 29K 运行期 schema；codex 自己两条路线并存；A-7 的快照已给了外置想要的可 diff |
| C-8 | 工具策略进 `Settings` | 没有"覆盖只能收窄"校验器时，把 fail-closed 治理表接到用户配置面是净损失 |
| C-9 | pytest marker 分层 | 选择机制已是路径制且 CI 在用；postgres marker 已被注册两遍；再加是第三套机制 |
| C-10 | 同址测试 | Python 没有私有性墙，买不到 codex 的 `super::*` 收益；openpi 的同址一半是运行器 glob 逼的 |
| C-11 | syrupy 等快照库 | golden 只需四五个；一键 accept 正是快照烂掉的机制；插件会进 invariants 门禁的收集子进程 |
| C-12 | 覆盖率百分比门禁 | F-24 反例：被测试的死码让覆盖率虚高，门禁会奖励它 |
| C-13 | 单测试二进制聚合 | 那是 Rust 编译/链接成本优化；pytest 收集与文件数无关 |
| C-14 | submission/event 双队列 | `trip_run_commands` 表 + poll_once 是持久化的更强等价物；进程内队列会造出第二个真源 |
| C-15 | RAII 名额计数器 | `ChannelGate.hold` 的 finally 已覆盖异常路径且无 panic 缝隙；turn 唯一性由 DB 租约跨进程保证 |
| C-16 | 沙箱子进程 + IPC 循环 | 没有不可信控制流要围；六个 contextvar 跨进程全部作废 |
| C-17 | 两池两准入哲学 | 只有一个池，"排队由剩余墙钟定界"在墙钟封存形态下唯一自洽，理由已写在两处 docstring（补一条 INV 即可） |
| C-18 | journal 内容哈希重放键 | 同构实现已在 Provider 快照层；补研轮严格串行，乱序不存在，哈希没有对手 |
| C-19 | 仓库级异常基类 | 多数异常的消费方就在紧邻的 except；改 ValueError 子类基类有让上游捕获失效的实际风险 |
| C-20 | 接 OpenTelemetry | 单机单用户无汇聚方；真缺口是读路径与手写表漏项，OTel 一行都不解决 |
| C-21 | 新 run 级账本 / 全量 payload 落盘 | 数据不缺缺读路径；全量落盘把脱敏风险从日志层升级到文件层 |

不做档的理由归三类：语言或形态没有对应物（C-4、C-14 到 C-18）；参照仓库自己也没做、或内部并不一致（C-1、C-3、C-7、C-11）；本仓已有更强或更贴的机制（C-2、C-6、C-8、C-9、C-17、C-20、C-21）。每条的复议条件写在正文里，条件不满足前不必再议。

---

## 8. 方法、证据强度与勘误

### 8.1 方法与核实账面

三段流水线：12 个读码代理（sonnet，1M 上下文）分维度定点读三仓，笔记落 `tmp/review2/`（12 份）；5 个分析代理（Opus）按维度组产出建议与承重断言清单；5 个核实代理（Opus）逐条对抗核查。核实账面：56 条承重断言，31 条 CONFIRMED、25 条 CORRECTED、零 REFUTED；每组另抽查正文引用至少 6 处，全部修正已吸入本文。核实还逐组审查了"建议是否越过不改行为的约束"，点名约 20 处——它们在正文里以【行为标注】或"行为票"字样出现，三处建议因此改写了方案本体（A-6 拆成可见性与硬失败两半、A-19 连挂载点一起改、B-15 的 F-38 方向从"挪"改成"加"）。

与上一轮"零测试运行"不同，本轮分析与核实阶段做过定点实验：pytest 全量两遍（含 `extra="forbid"` 的开关实验，255 条收集、开关后 250 通过 5 失败）、ruff TID251 规则实验、LangGraph 1.1.3 的三个语义实验（checkpoint 注入废弃字段、节点返回未知键、task_id 派生）、prompt 长度实测。实验的临时改动均已还原。两个参照仓库的测试套件没有运行过。

### 8.2 对上一轮报告的四条勘误

其一，§7.6 说"codex 生成出的 prompt 文本有快照测试钉住"，对 `format_role` 不成立：`role_tests.rs` 全是子串 contains 断言；insta 快照在 `world_state/` 的 instructions 测试与 `core/tests/suite/`（759 个 `.snap` 里 705 个属 tui），`codex-prompts` crate 用字面量 `assert_eq!`。三个子系统三种写法，没有统一决策——A-7 的依据因此改锚到本仓自己的三条事实上。

其二，F-13 只对了一半：`completed`/`failed`/`cancelled` 的未识别 reason 会进 `unclassified_terminal_count` 兜底；两个计数器都不认领的是 interrupted 且墙钟未耗尽的 Run（5.1）。顺带一条源码自身的误导：`run_completion_metrics.py:594` 的 docstring 自称 four allowed buckets，实际三桶。

其三，F-12 与 F-16 已被 `510d5236`/`5524f388` 修掉；随之 `test_run_execution_contract.py:131` 的第一条断言退化成同源互测（4.1），上一轮"三件已有资产"里的这一件需要重修。

其四，本轮底稿曾断言"门决策不持久、checkpoint 清理即不可再得"，不准确：`gate_failure_attributions` 被投影成十个字段进 `completion_audit` 落 jsonb（6.2）。另两处小口径修正：openpi 子会话排除名单是 26 项（上一轮记 21）；codex protocol crate 的反向依赖实测 54 个 crate、正向依赖 10 个 `codex-*` 工具 crate 且无一反向依赖。

### 8.3 覆盖边界

本轮是定点读，不是普查。codex 侧读了 core 的主循环与任务层、protocol 的错误类型、otel/rollout/rollout-trace、config 与 agent-roles、tools 的注册与曝光；approvals、guardian、ConfigLayerStack 的合并细节仍未展开。openpi 侧读了 workflows 全家（runner/controller/coordinator/journal/invocation-ledger/replay-safety/acceptance/resume-lookup）、subagents 的 manager 与 result-delivery、shared 的 tool-surface/child-session、测试组织；plan-mode 的 bash-policy 仍未读。JourneyPilot 侧按四个新维度做了盘点（主循环、错误、观测、测试），上一轮 §9.2 列的未读区（`db/` 全目录、`preset/`、`intent_verification.py` 判定内核、组合确定性中段、RAG 索引侧）本轮只在守卫建议触及处抽读，仍未系统覆盖。

行号以 `5524f388` 为准；审查期间仓库仍在被编辑，凡核实与分析冲突处以核实为准。工作底稿在 `tmp/review2/`（12 份读码笔记、5 份分析件、5 份核实件，gitignored），保留了每条建议更长的推导与实验记录。

### 8.4 一条方法论收获

Python 逼近 codex"新增分类必须声明后果"的现实方案，不是枚举加 match，是 `typing.get_args(Literal)` 或既有常量元组，加参数化金标准表。它不改任何运行时表示，天然满足"判定逐案例不变"；反过来，为了更像参照仓库把 `Literal` 升成 `str, Enum`，会在 f-string 插值处静默改写持久身份串（6.1 的实测）。同一个"升枚举"动作，在只经 Pydantic 序列化的 `GateDisposition` 上安全，在进 f-string 的 `failure_signature` 上危险——对照吸收的价值不在搬做法，在搬判据。
