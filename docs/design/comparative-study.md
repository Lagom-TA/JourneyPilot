# 对照研究：codex-main 与 openpi

> **状态：大纲待确认。** 骨架 + 已收集到的关键证据位置，正文逐轴补齐。

参考版本：`codex-main`（Rust，OpenAI Codex）、`openpi`（TypeScript，Pi 工作台扩展），
读取日期 2026-08-25。JourneyPilot 侧基线：`main @ 5fbb2b29`，详见根目录 `AGENT-ARCHITECTURE.html`。

---

## 0. 方法与边界

- **只在对方的选择确实更好的维度上比较。** 不做 feature 对齐，不列「他们有我们没有」。
- 每条对照四段：① 我们现在选了什么 ② 他们选了什么 ③ 他们为什么这样选（指到具体代码/配置）
  ④ 这个选择好在哪、对 JourneyPilot 意味着什么。
- 前提不同就先写前提差异，再判断结论是否可迁移。**不可迁移的明确说不可迁移。**
- 结论必须落到编号决策（DD-xx），不停在「值得借鉴」。

## 1. 三个系统的前提对照

> 这一章决定后面所有结论的可迁移性，必须先读。

| 维度 | codex | openpi | JourneyPilot |
|---|---|---|---|
| 交互形态 | 多轮，无限期 | 多轮 | 单次 Run，一个 HITL 点 |
| 墙钟约束 | 无 | 无 | 600 秒硬上限，授权瞬间封存 |
| 人的可用性 | 全程在场，可审批 | 全程在场 | 只在计划门 |
| 稀缺资源 | **上下文窗口** | **上下文窗口** | **墙钟秒数** |
| 失败可逆性 | 可逆（git） | 可逆 | **不可逆**（用户站在关门的餐厅前） |
| 可回放要求 | 好有则有 | 好有则有 | 规范要求（INV-REPLAY-001） |
| 交付物 | 一个 diff，由测试/人验证 | 文本 | DeliveryBundle，由四道门验收 |

- 1.1 「稀缺资源不同」如何解释两边的投资方向差异
- 1.2 「失败可逆性不同」如何解释我们为什么不能采纳「模型决定 + 人审批」的研究环姿态
- 1.3 哪些章节因此**整章不可迁移**，说明理由

## 2. 轴一：编排的确定性，与配置空间的宽度

- 2.1 我们现在选了什么：`build_capability_plan()` 三种形状 + 单点 Worker 配置
- 2.2 他们选了什么
  - codex：`agent/role.rs` 的 `AgentRoleOverrides` 封闭覆盖面；`registry.rs`；`builtins/*.toml`
  - openpi：`extensions/subagents/src/agent-types.ts` 的 `agents/*.md` 声明式类型
- 2.3 他们为什么这样选（代码证据）
  - 覆盖只能收窄：role.rs 模块注释、`features` 的 `if !enabled` 守卫、`skills.max_context_tokens = None`
  - 空间由人写、选择由模型做：`spawn_tool_spec::build` 把可选角色枚举给模型，并声明哪些设置不可改
  - 授权按缺席实现：`collab_tools_enabled` 在深度用尽时**不曝光** spawn 工具族；`DEFAULT_AGENT_MAX_DEPTH = 1`
  - openpi：「a capability boundary instead of a request the child can ignore」
  - openpi：未知 frontmatter 键视为非法——「a misspelled key fails in the dangerous direction」
- 2.4 好在哪 / 对我们意味着什么：**问题不是图的形状，是执行档只有一个点**
- 2.5 不可迁移：选择权不能交给模型（墙钟在授权瞬间封存，时间片必须在授权前可投影）
- 2.6 决策 DD-1..n

## 3. 轴二：Worker 的生命周期与上下文

- 3.1 我们现在选了什么：装配 → ≤N 轮 ReAct → 定型 packet → 结束
- 3.2 他们选了什么
  - openpi：`extensions/shared/child-session.ts` 的 fail-closed 双名单
  - openpi `AGENTS.md`：模型拥有判断 / 运行时拥有可强制的事实
  - codex：子线程 spawn，深度默认 1
- 3.3 他们为什么这样选（代码证据）
  - 「the parent session owns its persistent goal」——子 agent 不能改自己的目标
  - 「children cannot recursively orchestrate」
  - 「headless children have no user to ask」
- 3.4 好在哪 / 对我们意味着什么：**openpi 在这一轴是支持性证据，不是反例**
- 3.5 两处真的不如人
  - 补研轮次没有 typed 的「上一轮结论」输入
  - 反向差异：我们允许 Worker 调 `ask_user` 并 HALT 整个 Run——比 openpi 给子 agent 的权限更大
- 3.6 决策 DD-x..y

## 4. 轴三：门间协议与边界类型

- 4.1 我们现在选了什么：97 个 state 字段中 15 个协议载体；`last_error` 字符串前缀
- 4.2 他们选了什么：codex `protocol/` 独立 crate 的三层错误分类
- 4.3 他们为什么这样选（代码证据）
  - `CodexErrorDetails`（内部，富载荷）vs `CodexErrorInfo`（对外，「errors we expose to clients」）
  - `strum_discriminants(CodexErrKind)`：类别**机械派生**，不可能与变体漂移
  - `affects_turn_status()`：后果声明在类型上，穷举 match，加变体即编译错误
  - `TurnAbortReason` 封闭四值，`BudgetLimited` 是一等终止原因
  - openpi：drift test 扫描扩展，**未分类即失败**（动态语言里的等价物）
- 4.4 好在哪 / 对我们意味着什么
  - **先写清楚现在做对了什么**（否则结论不诚实）：前缀常量在 `worker_errors.py:19-24`
    单点定义为 `Final`；marker 词表 `_TRANSIENT_MARKERS` / `_DETERMINISTIC_MARKERS` 在
    `provider_failure.py:34,58` 单点定义并被写方 import，注释写明理由——
    「A classification that depended on which layer saw the string first is not a classification」；
    唯一写方 `format_worker_last_error` 且幂等（`_already_prefixed`）
  - **缺陷一（已复核）**：两个读方对同一个 `worker_failed:` 结论相反。
    `classify_provider_failure` 落到 `incomplete`（保留补研预算，`provider_failure.py:166-169`）；
    `is_provider_or_model_failure` 因 `_EXPLICIT_EXTERNAL_FAILURE_MARKERS`（89-104）不含该前缀而返回
    False，按其 docstring「remains Delivery Integrity」。而 `worker_failed:` 是写方的**兜底分支**
    （`worker_errors.py:107`），不是罕见路径
  - **缺陷二（已复核）**：未识别前缀落到 `incomplete` = 在墙钟这条最稀缺的轴上 fail-open
  - **缺陷三（已复核，根因与上一轮记录不同）**：读方无法 import 写方常量，因为依赖方向是
    写方→读方（`worker_errors.py:13-16`）。读方只能把五个前缀写成字面量，且写了两处
    （`provider_failure.py:89-93` 与分支条件 116/126/131/136/146）。根因是依赖方向，不是「五处副本」
  - **缺陷四（已复核）**：`tests/` 中零个测试引用这两个函数或任一前缀
  - ~~词表五处副本~~ —— 上一轮记录有误，marker 词表实际是单点定义并被 import
- 4.5 决策 DD-z..

## 5. 看过但决定不采纳的

- 上下文压缩（深度路径）：稀缺资源不同，Worker 短命
- 模型选择角色：墙钟封存不允许
- 递归 spawn：图是静态的，没有对应概念
- （逐条附理由）

## 6. 决策清单

| 编号 | 决策 | 轴 | 影响面 | 状态 |
|---|---|---|---|---|
| DD-1 | *待讨论确定* | | | 提案 |

---

## 7. 已复核证据台账（原始材料，非结论）

> 本节只记「读到了什么、在哪一行」。结论在 §2–4，不在这里。
> 未标注的条目为主会话直接读取核实；标注 `[待补]` 的尚未收集。

### 7.1 codex —— 覆盖面只能收窄（轴一）

| 位置 | 事实 |
|---|---|
| `core/src/agent/role.rs:1-4` | 模块注释：*"Roles may customize the child or reduce its capabilities, but never replace the parent session's authority."* |
| `core/src/agent/role.rs:36-48` | `AgentRoleOverrides` 恰好九个字段：`developer_instructions` / `model` / `model_reasoning_effort` / `model_reasoning_summary` / `model_verbosity` / `personality` / `service_tier` / `features` / `skills` |
| `core/src/agent/role.rs:91-106` | features 只认 `!enabled`，且限于六个特性的闭合白名单（ShellTool / Apps / Personality / Plugins / MemoryTool / RequestPermissionsTool）。写 `true` 被静默丢弃 |
| `core/src/agent/role.rs:107-118` | skills 只能关不能开：`retain(\|skill\| !skill.enabled)`；**`skills.max_context_tokens = None`——上下文预算根本不在覆盖面内** |
| `core/src/agent/role.rs:213-217` | 只有 `features.disable(feature)`，全仓无对应 `enable` 调用 |
| `core/src/agent/role.rs:203-212` | `ServiceTier::Fast` 仅当父级 `Feature::FastMode` 已启用时才生效 |
| `core/src/agent/role.rs:318-340` | `format_role` 在工具描述里向模型明说锁定项：*"These settings cannot be changed."* |
| `core/src/agent/builtins/explorer.toml` | **0 字节空文件** |
| `core/src/agent/role.rs:358-394` | 出厂角色 `default` / `worker` 的 `config_file` 均为 `None`；`awaiter`（唯一带配置的）在 `:395-412` **被注释掉** |
| `core/src/agent/role.rs:369-375, 383-390` | 出厂角色真正变化的维度是 description 文本，内容是**委派合同**（explorer：避免重复探索、可并行、复用已有；worker：明确文件归属、"not alone in the codebase"） |

**覆盖顺序（最不可信者排最前，被逐层盖掉）** —— `core/src/tools/handlers/multi_agents/spawn.rs:90-115`：

1. `build_agent_spawn_config` 从**父亲的生效配置**起步（`multi_agents_common.rs:176-184`）
2. 模型请求的 `model` / `reasoning_effort`（`apply_requested_spawn_agent_model_overrides`, `:263`）
3. **role 覆盖模型请求**（`apply_spawn_agent_role`, `:376`）
4. **runtime 最后覆盖一切**（`apply_spawn_agent_runtime_overrides`, `:234`）：approval policy / cwd / sandbox / permission profile

- `multi_agents_common.rs:230-233` doc：*"These values are chosen by the live turn rather than persisted config, so leaving them stale can make a child agent disagree with its parent about approval policy, cwd, or sandboxing."*
- `multi_agents_common.rs:219-227`：`fork_context`（继承父级完整历史）与 `agent_type` 覆盖**互斥**

**深度：双重防御** —— 曝光期 `tools/spec_plan.rs:596-608` + `:1129-1132`（深度用尽则 spawn 工具族**不注册**）；调用期 `spawn.rs:65-71`（`"Agent depth limit reached. Solve the task yourself."`）。
`config/mod.rs:236` `DEFAULT_AGENT_MAX_DEPTH: i32 = 1`；`:226` `DEFAULT_AGENT_MAX_THREADS: Option<usize> = Some(6)`。

### 7.2 openpi —— fail-closed 交集与漂移守卫（轴二）

| 位置 | 事实 |
|---|---|
| `AGENTS.md`「Keep ownership clear」 | 模型拥有判断 / 运行时拥有**可强制的事实**（权限、隔离、并发与时间上限、生命周期、原子性、fail-closed 结果、**exact terminal evidence**） |
| `AGENTS.md` 同节末句 | *"Do not rely on prompts for runtime invariants. **Do not move model judgment into a rigid state machine merely because it is easier to test.**"* ← 直接冲着我们这套设计 |
| `AGENTS.md`「Build for model leverage」 | *"Do not encode a preferred reasoning process, keyword router, or fixed orchestration workflow **unless correctness requires it**."* ← 转折在最后四个词 |
| `AGENTS.md`「Keep subagents simple」 | *"Child capabilities are a fail-closed intersection and do not silently widen parent authority."* |
| `extensions/shared/child-session.ts:13-24` | 白名单半边的 doc：*"anything registered by this package and not listed here MUST be excluded, and `child-session.test.ts` scans the extensions to enforce exactly that — so a future tool cannot silently leak into children by being forgotten."* |
| `child-session.ts:25-31` | `CHILD_SAFE_PACKAGE_TOOL_NAMES` 只有五个只读发现工具：`fd` `rg` `git_show` `git_diff` `git_log` |
| `child-session.ts:59-97` | `CHILD_EXCLUDED_TOOL_NAMES` **按所属扩展分组，每组带一句理由**。关键几条：`// ask-user — headless children have no user to ask or handoff to`（排除 `ask_user` / `human_handoff`）、`// goal — the parent session owns its persistent goal`、`// workflows — children cannot recursively orchestrate`、`// context-pivot — compaction of the conversation is a parent-only decision` |
| `child-session.ts:99-116` | 准入代数：`(!allowed \|\| allowed.has(name)) && !excluded.has(name)`。doc：*"It can only ever REMOVE… an allowlist naming an excluded tool still cannot obtain it, and the boundary above stays authoritative."* |
| `child-session.ts:209-262` | `bindChildSessionExtensions`：**第一次 prompt 之前**做工具预检，请求的工具在绑定后不可用则直接抛错 |
| `child-session.ts:161-192` | Trust fail-closed：*"Unreadable or invalid trust data fails closed."* |
| `child-session.ts:331-395` | abort + shutdown + dispose **共享同一个 deadline**，*"reports timeout/failure instead of silently turning failed cleanup into success."* |

**漂移守卫**（`extensions/shared/child-session.test.ts:651-749`）——比预期更完整：

- **双向**：每个已注册工具必须被分类（否则失败）；每个 excluded 名字必须仍被注册（否则要求删除陈旧条目）
- **反空转断言**：`assert.ok(registered.size >= 15, "expected to discover the package tools")` —— 扫描失效时测试失败，守卫不会静默变成 no-op
- **工厂注册盲区显式兜底**：`KNOWN_FACTORY_TOOLS` 记录已审阅分类，*"an unrecognized factory registration trips here instead of silently escaping the boundary"*
- 同一工具不得既 safe 又 excluded

### 7.3 失败方向按字段选择（轴三的核心可迁移原则）

`extensions/subagents/src/agent-types.ts`：

- `:303-305` — *"Unknown tool names remain advisory because extensions can register them; unknown frontmatter keys reject the whole type because a misspelled restriction key could otherwise expand capability."*
- `:379-389` — *"A misspelled KEY is the dangerous direction: `tool:` or `allowed_tools:` … reject the whole type on an unknown key rather than guessing and widening capability."*

**同一个仓里，未知工具名 fail-open、未知键 fail-closed——因为两者危险的方向相反。**

**反例（前提不同导致答案相反）**：codex 对未知 frontmatter 键**静默忽略，甚至主动修复**。
`skills/src/parser.rs:6-20` 无 `deny_unknown_fields`；`:48-62` 的 `repair_frontmatter_scalar_fields` 会把
`argument-hint: <duration: e.g. 7d>` 这类无法解析的未知键重新加引号救回来。理由写在 `:53-55`：
*"Some third-party skills use prose like … Keep the repair line-oriented so unrelated invalid YAML still surfaces."*
测试 `parser_tests.rs:63-79` `repairs_unrecognized_frontmatter_fields_that_need_quotes` 钉住这个行为。
→ **codex 必须容忍为别的 harness 写的第三方 skill；openpi 拥有自己全部扩展面。前提不同，答案相反。**

### 7.4 codex 的错误分类学（轴三对照对象）

| 位置 | 事实 |
|---|---|
| `protocol/src/error.rs:73-78` | `#[derive(Error, Debug, EnumDiscriminants)]` + `#[strum_discriminants(name(CodexErrKind))]`，doc：*"The payload-free semantic category used for analytics."* —— **类别由变体机械派生，不可能漂移** |
| `protocol/src/protocol.rs:1776-1779` | `CodexErrorInfo` doc：*"Codex errors that we expose to clients."* —— 内部富载荷 `CodexErrorDetails` 与对外闭合 `CodexErrorInfo` 分离 |
| `protocol/src/protocol.rs:1818-1836` | `affects_turn_status()`：**后果声明在类型上**，穷举 match，加变体即编译错误 |
| `protocol/src/error.rs:364-404` | `is_retryable()`：第二个「后果挂在类型上」的方法，同样穷举 |
| `protocol/src/protocol.rs:4000-4006` | `TurnAbortReason` 闭合四值：`Interrupted` / `Replaced` / `ReviewEnded` / `BudgetLimited` |
| `protocol/src/error.rs:269-273` | `From<CancelErr> for CodexErrorDetails` → `TurnAborted`：所有取消收敛到一个变体 |
| `core/src/session/mod.rs:1933-1946` | `send_event` 只对 `EventMsg::Error` 锁存 `terminal_error`，**不对 `StreamError`** —— 重试通知与终态错误是不同事件类型，重试不污染终态 |

**他们自己的对应缺陷（写进文档时必须写，否则对照不诚实）**：
`TurnAbortReason::BudgetLimited` 与 `ReviewEnded` **在整个 workspace 中没有任何生产者**，只被 match。
——这与我们的 `worker_failed:` 恰好是镜像：他们是「读了没人写」，我们是「写了没人读」。
**他们的失败模式是死代码，我们的是静默发放预算。** 差别不在谁更细心，在穷举 match 强制每个读方处理每个变体，
而字符串 dispatch 允许未处理值落进默认分支。

**codex 在终态归因上没有可抄的模型**：core 层无单一 typed 终态，是
`Result<Option<String>, CodexErr>` + `Option<TurnAbortReason>` + 侧信道 `terminal_error` 三者联合
（`core/src/tasks/mod.rs:71, 582-602, 784-825`），到 app-server 边界才收成四值 `TurnStatus`。

### 7.4b codex 的具名上下文片段（供 agent-workflow §6）

`core/src/context/mod.rs:1` —— *"Context fragments injected into model input."*

**46 个具名模块，一个片段一个文件**（`ls core/src/context/`）：`base_instructions` / `user_instructions` /
`environment_context` / `developer_instructions` / `compaction_summary` / `current_time_reminder` /
`turn_aborted` / `token_budget_context` / `rollout_budget` / `subagent_notification` /
`inter_agent_message` / `inter_agent_completion_message` / `multi_agent_role_instructions` /
`guardian_policy` / `guardian_review_evidence` / `image_resize_notice` / `unsupported_media` /
`hook_additional_context` / `network_rule_saved` / `approved_command_prefix_saved` … 等。

每个片段是一个实现 `ContextualUserFragment` 的 struct，四个方法：

| 方法 | 作用 | 例（`user_instructions.rs:10-34`） |
|---|---|---|
| `content_kind()` | 稳定字符串 ID | `"agents_md.instructions"` |
| `role()` | `"user"` / `"developer"` | `"user"` |
| `type_markers()` | **关联函数**（非实例方法）：开闭定界符 | `("# AGENTS.md instructions", "</INSTRUCTIONS>")` |
| `body()` | 渲染文本 | —— |

`type_markers()` 是**关联函数**这一点是承重的：不需要持有实例就能定位并剥离某一类注入内容，
去重、替换、移除因此可以按类别做。

**对轴二直接相关的一个具体片段** —— `core/src/context/turn_aborted.rs:9-18`：

```rust
pub(crate) const INTERRUPTED_GUIDANCE: &'static str = "The user interrupted the previous turn on purpose. Any running unified exec processes may still be running in the background. If any tools/commands were aborted, they may have partially executed.";
```

即：codex 有一个**专门用来把「上一轮出了什么事」带进下一轮**的具名上下文片段，
`content_kind = "generic.turn_aborted"`，`type_markers = ("<turn_aborted>", "</turn_aborted>")`。
→ 这正是我们定向补研轮缺的东西（轴二缺陷 a）：新一轮不知道上一轮试过什么、怎么失败的。
**这条不是「值得借鉴」，是有现成实现可以指。**

### 7.6 JourneyPilot 状态与预算（已复核，含对既有认知的修正）

**修正 A：跨门私有导入比记录的小。** `agents/orchestrator/artifact_gate.py:32-36` 实际导入**三个**符号，
其中**只有一个**是私有的：`_latest_packets`（私有，`candidate_gate.py:248-264`）、
`worker_targeted_research_exhausted`（公开，`:1610-1644`）、
`worker_research_satisfied_by_a_later_round`（公开，`:1647-1676`）。
全仓跨模块私有导入只有三处，`agents/` 下仅此一处（另两处在 `services/candidate_readmission.py:51`、
`api/routes/chat.py:59`）。→ **这不是「门之间纠缠」，是一个具体的所有权表达问题。**

**修正 B：「定向补研每域 1 次」是下限不是上限。** `candidate_gate.py:99` 的
`_MAX_TARGETED_RESEARCH_ATTEMPTS = 1` 经 `_domain_research_budget()`（`:1458-1502`）按结构负载放宽为
`max(len(legs) / len(destinations) / len(local_connector_gaps), 1)`。docstring 讲了为什么按
**受控身份给的责任数**而不是**尚未满足数**计：账本是累积且持久的，随满足度收缩会「在最后一个责任
最需要第二次机会的那一秒把它拿掉」。

**修正 C：`route_after_candidate_gate` 把异常吞成路由。** `candidate_gate.py:2776-2777`：
`observe_run_deadline` 抛 `ValueError` 时 `return "passed"`。

**发现 1（对轴三是决定性的）：`last_error` 在并行 worker 下根本无法归属。**
reducer 是 `_prefer_non_empty_str`（`state.py:153-158`，`b or a`），而 `dispatcher.py:211-213` 用
`Send(node, state)` 真并行扇出。**代码自己承认了这一点** —— `candidate_gate.py:1685-1687`：
*"reduced as a latest nonempty string, so it cannot distinguish concurrent worker failures"*。
→ 前缀词表的问题不只是「字符串约定」，是**载体本身在并行下会丢归属**。

**发现 2（最有力的内部论证）：我们已经在用「后果挂在类型上」——只是用在时钟上，没用在错误上。**
`workflows/run_deadline.py:97-119` 的 `DeadlineObservation` 暴露两个**具名谓词**
`research_closed` / `composition_closed`，docstring 写明：
*"Read the two predicates rather than comparing phases: they name the question each call site is actually asking."*
→ 这正是 codex `affects_turn_status()` 的同一手法。**轴三的修法不是「引入 codex 的模式」，
是「把我们自己已经在时钟上用对的模式，用到错误分类上」。**

**发现 3：并行安全的 reducer 隐患。**

| reducer | 位置 | 并发下是否静默丢数据 |
|---|---|---|
| `_merge_dicts` | `state.py:64-77` | **会**。docstring 自陈契约是**无强制的约定**：*"Same-key dual write is undefined and must not appear in production paths."* |
| `_merge_dicts_allow_clear` | `:80-83` | **会，两重**：同键覆盖，且**任一分支返回 `{}` 抹掉所有其它分支的贡献**。用在 `agent_status` / `artifact_status`——正是并行 worker 写的字段 |
| `_replace_amendments` | `:91-104` | **会**：`_a` 完全弃用 |
| `_prefer_pending_choice` | `:161-172` | **会**，且**保留先到者**，与其它每一个 reducer 方向相反 |
| `_take_latest_value_allow_clear` | `:182-189` | **会**：无条件返回 `b`（含 `None`）。守着 `run_budget` / `minimum_delivery_draft` / `terminal_attribution` |
| `merge_provider_evidence_outcomes` | `provider_evidence.py:611-646` | **不会——唯一一个冲突时 `raise` 而不是静默取一个的 reducer** |

→ 发现 3 与发现 1 是同一件事的两面，而 `merge_provider_evidence_outcomes` 已经是**正确形状的样板**。

**发现 4：组合修复预算的两处不一致。**
- `delivery_quality_gate.py:639` **直接写** `composition_repair_attempts`，绕过共享助手
  `apply_composition_repair_budget`（另外三道门都走助手：`candidate_gate.py:1306`、
  `artifact_gate.py:254`、`intent_fidelity_gate.py:128`）
- 1→3 改动后有三处 docstring 未更新，仍写「the single repair round」：
  `composition_repair.py:21-24`、`delivery_quality_gate.py:650`、`:679`

**发现 5：四道门的边上防御不对称。** `route_after_intent_fidelity_gate`（`intent_fidelity_gate.py:136-140`）
是四者中**唯一不做窗口判定**的，且对未知路由 `raise`；另外三道都做窗口折叠。

**预算模型的关键位置（供 agent-workflow §5）**

| 项 | 位置 |
|---|---|
| 四段窗口定义与两个具名谓词 | `workflows/run_deadline.py:89-119` |
| `observe_run_deadline`（三读数取 max，永不回退） | `run_deadline.py:140-190` |
| 封存点：`seal_minimum_delivery_draft` | `workflows/minimum_delivery_draft.py:321-370`，调用点仅两处，都在 `travel_planning.py` 的 `plan_gate_node`（`:349-356`、`:442-448`） |
| 「重放已封存状态不重发窗口、不补额度」 | 同上 docstring |
| 预算与 Deadline 必须同进同出 | `entities/state.py:661-666` 校验器 |
| 判即记一步 | `workflows/run_budget.py:143-152` `reserve_tool_call`，docstring 记了漏判导致 `max_tool_calls` 只精确到 4 倍的事故 |
| 首发不计入重试上限 | `run_budget.py:154-167`，docstring 记了合并计数会让工具永久短路的后果 |
| 费用低报不当上限用 | `entities/run_budget.py:111` —— `cost_complete=False` 时费用维不参与判定 |
| 窗口关闭→改路由而非抛异常 | `dispatcher.py:73-110`（三种去向）、`candidate_gate.py:2763-2792`、`artifact_gate.py:298-308`、`delivery_quality_gate.py:675-695` |
| 节点入口拦截（写状态而非抛异常） | `run_control.py:692-732` `_blocked_research_worker_update` |
| 工具层：窗口与预算都收成 failed envelope | `agents/utils.py:641-679` |

### 7.7 JourneyPilot 轴一/轴二实现（已复核，含三条对「已确认事实」的修正）

> ✅ 下面前三条与开工时给定的「已确认现状事实」不一致。**已确认采纳，`AGENT-ARCHITECTURE.html` §13 已同步修订。**

**修正 D：`execution_plan` 实际只有两种形状，不是三种。**
`services/capability_planning.py:174-184` 三次 append 组装 `order`，但三组里有两组是**结构强制**的：
- `capability_planning.py:89` 无条件 `domains.add(ResearchDomain.LONG_DISTANCE_TRANSPORT)` → `transport_researcher` 恒在
- `services/product_requirements.py:128` `_BASELINE_PHYSICAL_KINDS = frozenset({"visit"})`，`:154` `selected |= set(...)`
  → `"visit"` 恒在 → `capability_planning.py:83-84` 恒加 `VISIT` → `destination_researcher` 恒在
- `capability_planning.py:171` 无条件 `agents.add("itinerary_planner")`

唯一自由变量是 `accommodation_researcher`（`duration_days > 1` 或有 LODGING intent，`:87-88`）。两种可达形状：
```
[[destination], [transport, accommodation], [itinerary]]
[[destination], [transport],                [itinerary]]
```
→ **不是「三种形状」，是一种形状 + 一个可选 worker。每一次深度 Run 都走同样的三步。**

**修正 E：定向补研不写 round-suffix assignment。**
门写的是 `assignments[worker]` —— **base key**，merge 覆盖旧 assignment（`candidate_gate.py:2630-2632`）。
round suffix 是**在 worker 节点内部**发明的，且只用于**输出键**
（`resolve_scoped_research_output_key`，`agents/utils.py:394-416`；`make_round_name` 全仓仅 3 处引用，都在 utils.py）。
→ 「新 assignment + round suffix 重进同一节点」中，suffix 是产物编号机制，不是 assignment 身份机制。

**修正 F：`itinerary_planner` 没有 ReAct 循环。**
`streaming_react_loop` 在 `agents/itinerary_planner/node.py` 中从未 import 或调用；它做的是直接的
结构化输出 `ainvoke`（`response_format: json_schema`，`node.py:3048-3060`、`:3340-3360`）。
→ 调模型的 worker 有**两类**：ReAct 研究者（3 个）与结构化输出组合者（1 个）。「≤N 轮 ReAct」不适用于后者。
（另：subagent 数到 8 个模型调用点而非 7，多出的是 `agents/scope/constraint_normalizer.py:169`。**待核**。）

**发现 6（轴一的决定性证据）：三个旋钮没有一个来自合同。**

| Worker | 模型档 | ReAct 轮次上限 | 工具集 |
|---|---|---|---|
| `destination_researcher` | 硬编码 `get_fast()` @ node:1353 | 硬编码 **3** @ node:126 | 硬编码 `_AGENT_TOOL_POLICY` @ utils.py:276 |
| `transport_researcher` | 硬编码 `get_fast()` @ node:1877 | 硬编码 **5** @ node:97 | 硬编码 @ utils.py:297 + 4 个节点内 scoping |
| `accommodation_researcher` | 硬编码 `get_fast()` @ node:792 | 硬编码 **4** @ node:85 | 硬编码 @ utils.py:304 |
| `itinerary_planner` | 硬编码 `get_primary()` @ node:3021/3274/3340 | 无（非 ReAct） | 硬编码 deny-all `{"*"}` @ utils.py:321 |

合同投影 `build_capability_plan()` 产出的是**任务内容**（objective / must_cover_intent_ids /
research_query_ids / success_criteria / excluded_categories …），**不含档位、不含轮次、不含工具白名单**。
连它携带的 `recommended_tools` 也来自硬编码表 `_TOOLS`（`capability_planning.py:59-64`）。
→ 注意 3 / 5 / 4 三个不同的常量：**有人已经想要按 worker 调轮次了，只是写成了常量而不是投影。**

**发现 7（把轴二与轴三合并成同一个根因）：补研轮的 typed 记录在边界上被拍成了字符串。**

我们**有**类型化的上一轮记录：
- `CandidateResearchGap`（`entities/delivery_bundle.py:1293-1327`，`StrictModel`，含 `attempted_signatures: List[str]`、`status` 四值、`reason` 五值）
- `ProviderFailureSignal`（`candidate_gate.py:161-166`，frozen dataclass，含 `tool_name` / `signature` / `reason_code` / `category`）

**结构化强制的部分做对了**：`excluded_tools` 经 `exclude_tools()` 程序化移除（`utils.py:190-202`），
`excluded_candidate_ids` 作为 typed 参数传给解析器，`recommended_tools` 由 `_ALTERNATIVE_TOOLS` 表算出。

**但「试过什么、怎么失败的」这份账，到模型那里只剩 f-string**：
`candidate_gate.py:2602` `gap_summary = [gap.model_dump(mode="json") for gap in scoped_gaps]`
→ `:2637-2638` `f"… gaps={gap_summary}; failure_signatures={accumulated_signatures}"`
→ 写进 `assignment["objective"]` → worker 读 `task_desc = assignment["objective"]` 印进 prompt。

→ **这与 `last_error` 前缀是同一个病：typed 信息在跨节点/跨门边界时被降级成字符串。**
轴二和轴三因此不是两个问题，是一个根因的两处发作。

**发现 8：worker 之间「能看到什么」是不对称的，且没人设计过这个不对称。**
`transport_researcher/node.py:1884` 与 `accommodation_researcher/node.py:799` 调用
`format_research_packet_context(state.research_packets)`（`research_packet_output.py:5145-5156`），
它 `json.dumps` 了 `.values()` **不加过滤** —— 所以这两个 worker 看到全部 packet，**包括自己上一轮的**。
`destination_researcher` 不调用该 helper，什么兄弟产物都看不到。

**发现 9（`ask_user` HALT 比「与前提 1.5 矛盾」严重得多）：它不是 interrupt，且不断点续跑。**
- `destination_researcher/node.py:1621-1643` 写 `next_agent="HALT"` + `pending_user_choice`，**不写 research_packet**
- `route_after_destination` → `"HALT"` → `END`（`travel_planning.py:633-641`）。这是**正常图终止，不是 `interrupt()`**；
  全图唯一的 `interrupt()` 在 `plan_gate`（`travel_planning.py:359`）
- `api/routes/chat.py:68` `_CHECKPOINT_GATE_NODES = {"plan_gate"}` —— 只有计划门能断点续跑
- worker HALT 留下的 `AWAITING_INPUT` 不满足 `checkpoint_resume`（`chat.py:374-391`），于是走 else 分支
  **构造全新 `TravelAgentState`，从 `START → scope_clarifier` 重新开始**（`travel_planning.py:927-931`）

→ **用户回答之后，这次 Run 已经做过的研究被整个丢弃、从合同段重来。** 在一个墙钟封存的系统里，
这不是「等人」的代价，是「作废」的代价。

### 7.8 codex 工具治理（供 agent-workflow §7）

**修正 F 补充（已核）**：`build_run_constraint_pack` 内的 fast 调用（`agents/scope/constraint_normalizer.py:169`）
是在 `request_contract_normalizer` **节点内部**发生的（`request_contract_normalizer.py:26` import 并调用），
不是第 8 个节点。→ **「7 个节点调模型」成立；但「7 次模型调用」不成立** —— 合同段那一个节点里至少两次 fast 调用。
文档里要把「调用点」和「调用次数」分开说。

| 主题 | 位置 | 事实 |
|---|---|---|
| 曝光面 | `tools/src/tool_executor.rs:49-99` | `ToolExposure` **六值**：`Direct` / `Deferred` / `DeferredModelOnly` / `DirectModelOnly` / `CodeModeOnly` / `Hidden`；另有正交位标志 `ToolExposures{DIRECT,DEFERRED,CODE_MODE}`（`:14-29`），两者的映射在 `core/src/tools/spec_plan.rs:230-242`，`(true,true,_)` 是 `unreachable!` |
| 重算粒度 | `core/src/session/turn.rs:335`、`session/mod.rs:3230-3234` | 工具集**每次模型请求（step）重算，不是每 turn**。注释：*"Capture once so context, advertised tools, and tool calls share one request view."* → 同一个 turn 内不同轮的工具面可以不同 |
| 按需曝光 | `core/src/mcp_tool_exposure.rs:90-94` | 开了 search 时 MCP 工具**整体转 `Deferred`**，模型初始只看到 `tool_search` |
| 检索 | `core/src/tools/handlers/tool_search.rs:229-243` | BM25 over 预计算 search text（名字/描述/JSON schema 的属性名与描述递归展开，`tools/src/tool_search.rs:124-149`），默认 limit 8 |
| **激活是否延续** | `core/tests/suite/search_tool.rs:553,797-829` | **不注入到后续请求的工具列表**。延续靠 `tool_search_output` 这个**会话条目留在历史里**。测试名即断言：`tool_search_returns_deferred_tools_without_follow_up_tool_injection` |
| 审批三态 | `core/src/tools/sandboxing.rs:150-171` | `ExecApprovalRequirement::{Skip, NeedsApproval, Forbidden}` —— 不是布尔 |
| 审批优先级 | `core/src/tools/approvals.rs:454-456` | 注释直书：*"Approval precedence is: 1. Hooks 2. If StrictAutoReview \|\| Guardian enabled, then Guardian. Else, user."* |
| 会话级记忆 | `core/src/tools/sandboxing.rs:39-116` | **只有 `ApprovedForSession` 进缓存**；`McpToolCall` / `NetworkAccess` / `RequestPermissions` / `Execve` 返回空 key 列表 = **不可缓存**。apply_patch **按文件**各出一个 key |
| 自动审批 fail-closed | `core/src/guardian/mod.rs:11` | *"Fail closed on timeout, execution failure, or malformed output."* |
| 沙箱升级不可越顶 | `core/src/tools/orchestrator.rs:148-158` | `"attachment-owned network policy cannot be bypassed by sandbox escalation"` |
| 升级要重新审批 | `core/src/tools/orchestrator.rs:413-414` | *"Strict auto-review approval covers the sandboxed attempt only; retrying without the sandbox requires a fresh guardian review."* |
| execpolicy | `execpolicy/README.md:5,95`；`src/decision.rs:7-27` | Starlark `prefix_rule(...)`，决策三值 `allow/prompt/forbidden`，多条命中取**最严**。`match`/`not_match` 是**加载期验证的样例**（"think of them as unit tests"） |

**不要学的一处**：脱敏是**尽力而为的正则**（`secrets/src/sanitizer.rs:13-14` *"best effort basis following some well-known REGEX"*），
且**未施加于 OTEL 的 `arguments` 字段**（`otel/src/tool_result.rs:68` 直接 `arguments = %arguments`）。
我们的 `ToolExecutionEnvelope` 走的是「参数摘要 + 哈希」，在这一点上比它保守。

### 7.5 尚未收集 `[待补]`

- ~~codex `tools/` + `guardian/` + `execpolicy/`~~ **已完成**，见 7.8
- ~~codex `context/`~~ 片段分类学已收（见 7.4b）；`context_manager/` + `compact*` 仍缺，但预判不可迁移（我们 Worker 短命，不做深度路径压缩）
- ~~JourneyPilot 轴一/轴二实现细节~~ **已完成**，见 7.7
- ~~JourneyPilot 状态协议表与预算表~~ **已完成**，见 7.6
