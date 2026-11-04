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

- [ ] **职责单一**：每段提示词只写这一步需要的目标；去掉重复、互相冲突和越权的要求。
- [ ] **上下文顺序**：稳定的内容放在前面，动态内容（当前时间、工具结果、上游成果）放在后面；同一轮内不改写已有的前缀。
- [ ] **角色输入**：以第一阶段整理好的旅行理解作为共同依据，不重复注入原始对话或同义资料。
- [ ] **输出要求**：结构要求只到解析所需为止；字数等软要求不设为硬性失败。
- [ ] **产出抽检**：用已有会话的真实结果抽检语气、准确性和长度；需要新增运行时，先取得付费授权。
- [ ] **统一风格**：主链之外的模型调用也遵循同一套上下文和写作原则。

## 影响下游

- 改动输出结构 → [B2](B2-planning-intake.md)、[B3](B3-planning-delivery.md)
- 生成的文字长度变化 → [F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)

## 收到的提醒

- [ ] 来自 B3-01、B3-04、B3-06：候选类型仅在无歧义时补全，天气敏感度支持 `medium`，空白日期须说明缺口 → 请复核输出示例与来源语义准确性。
- [ ] 来自 B2-03：重新规划的理解输入包含交付后的连续追问上下文 → 请复核内容保真与重复注入。
- [ ] 来自 S0：目的地调研曾遗漏 `candidate_kind`，另一次输出了 `medium` 天气敏感度；B3 已支持可确定类型的恢复和 `medium`，请复核提示词及输出示例。

## 问题与修复

- （暂无）
