# T2 提示词与模型产出

`文字内容` · 前置 [B2](B2-planning-intake.md)、[B3](B3-planning-delivery.md) · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)

## 范围

- 规划主链的提示词：
  - `backend/travel_agent/planning/requirements/understanding/prompts.py`
  - `backend/travel_agent/planning/research/prompts.py`
  - `backend/travel_agent/planning/research/destination/prompts.py`
  - `backend/travel_agent/planning/research/transport/prompts.py`
  - `backend/travel_agent/planning/research/accommodation/prompts.py`
  - `backend/travel_agent/planning/itinerary/prompts.py`
  - `backend/travel_agent/planning/itinerary/title_writing.py`
- 主链之外的提示词：
  - `backend/travel_agent/conversation/answer/prompts.py`
  - `backend/travel_agent/conversation/compaction_prompt.py`
  - `backend/travel_agent/conversation/prompt_optimization.py`
  - `backend/travel_agent/conversation/preset_instructions.py`
  - `backend/travel_agent/conversation/titles.py`
  - `backend/travel_agent/memory/memory_extractor.py`
- 用户能看到的模型产出：研究设想、模型工作说明、行程标题和每日主题、最终回答

## 审查项

- [x] **职责单一**：每段提示词只写这一步需要的目标；去掉重复、互相冲突和越权的要求。
- [x] **上下文顺序**：稳定的内容放在前面，动态内容（当前时间、工具结果、上游成果）放在后面；同一轮内不改写已有的前缀。
- [x] **角色输入**：以第一阶段整理好的旅行理解作为共同依据，不重复注入原始对话或同义资料。
- [x] **输出要求**：结构要求只到解析所需为止；字数等软要求不设为硬性失败。
- [x] **产出抽检**：用已有会话的真实结果抽检语气、准确性和长度；需要新增运行时，先取得付费授权。
- [x] **统一风格**：主链之外的模型调用也遵循同一套上下文和写作原则。

## 影响下游

- 改动输出结构 → [B2](B2-planning-intake.md)、[B3](B3-planning-delivery.md)
- 生成的文字长度变化 → [F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)

## 收到的提醒

- [x] 来自 B5-12：记忆总结结合当前事实、画像、偏好和用户手动管理记录，可依据明确意愿更新已有记忆 → 已复核：稳定记忆在前、本轮消息与版本在后；真实模型抽检 4 个场景——推翻旧事实时更新原条目而不新增、普通提问不写入、手动删除记录作为总结反馈、新增长期偏好同时写入事实与画像。输出示例中的 revision 改为整数或 null，与解析一致。
- [x] 来自 B5-07、B5-09、B5-10：工具授权绑定服务来源，天气窗口按目的地时区判断，汇率参数错误不作为证据 → 已复核：提示词只传推荐工具名，不描述授权、时区与汇率参数；国内行程未调用汇率工具，汇率路径未实测。
- [x] 来自 B3-01、B3-04、B3-06：候选类型仅在无歧义时补全，天气敏感度支持 `medium`，空白日期须说明缺口 → 已复核：各研究角色的提示词写明可提交的 `candidate_kind`；组合提示词保留“整天未安排时保留日期并在 unresolved 说明”。真实运行未出现 `medium`，由 Schema 枚举接受。
- [x] 来自 B2-03：重新规划的理解输入包含交付后的连续追问上下文 → 已复核：追问往来只在专门段落出现一次，本次新输入不重复，重新规划时不再附原始对话；新增 3 项单元测试。真实运行未覆盖交付后追问。
- [x] 来自 S0：目的地调研曾遗漏 `candidate_kind`，另一次输出了 `medium` 天气敏感度；B3 已支持可确定类型的恢复和 `medium`，请复核提示词及输出示例 → 已复核：同第 3 条；另在真实运行中发现交通研究员交出混有住宿候选的包（T2-02），已修复。

## 问题与修复

- [x] T2-01 研究员提示词把易变的运行态与固定规则混排，规则重复 → 角色、领域、输出结构、规则固定在前；旅行事实、上游成果、任务参数、当前时间依次在后。
- [x] T2-02 交通研究员交出混有住宿候选的包而整包被拒，工作说明也越出本角色范围 → 逐角色写明 `candidate_kind`，研究设想声明面向所有角色，交通模板指明住宿由住宿研究员负责；复跑 2 次真实规划均通过。
- [x] T2-03 理解输入重复注入追问上下文，稳定内容与易变内容交错 → 追问往来只出现一次，重新规划不再附原始对话，本次表达放在最后。
- [x] T2-04 理解入口与对话压缩各保留一份过时的提示词 → 统一使用理解提示词，删除 `compaction_prompt.py`。
- [x] T2-05 行程组合提示词规则堆叠，替模型规定内容细节（ADR-0010、ADR-0011） → 按角色、工具使用、研究反馈、每日设计、输出约定重写，交通与创作约束精简。
- [x] T2-06 行程标题与每日主题偏机械 → 重写提示词；14 日旅行抽检标题与每日主题自然，主题均在 15 字内。
- [x] T2-07 研究设想出现复述指令的元描述且过长 → 改为两三句自然语言；实测约 100–200 字，无泄漏。
- [x] T2-08 快速回答把当前时间放进固定前缀，范围内的问题也附带规划引导 → 时间移到最后一条用户消息，仅超出范围时引导。
- [x] T2-09 提示词优化可能改写意图、编造条件 → 只润色用户已有文字，并柔和融入系统推理的偏好；无法优化时返回约定标记；新增单元测试，真实抽检 4 组通过。
- [x] T2-10 记忆总结输入把本轮消息放在稳定记忆前 → 稳定记忆在前、本轮消息与版本在后。
- [x] T2-11 记忆压缩提示词冗长，预设指令含制表符缩进 → 精简压缩提示词，去除缩进。
- [x] T2-12 缓存命中忽高忽低（4 次真实运行 0–58%；同一前缀的相邻两次调用可能一次近乎全丢、一次近乎全中） → 提示词前缀已稳定；形态符合网关切换上游，属供应商层面，不在提示词范围，转入待决事项 D-14。
