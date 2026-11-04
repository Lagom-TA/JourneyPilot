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

- [ ] 来自 S0：目的地调研的模型产出缺少 `candidate_kind` 判别字段，导致 `ResearchPacket` 校验失败（run `trip_93ae8b4793d0597f813cbf36c4985f35`，6 处，详见 B3 提醒）；重试后另一次失败是 `weather_sensitivity` 的 `cold_sensitivity`、`wind_sensitivity` 填了 `medium`（只允许 `none/low/high`）。请检查对应提示词和输出示例是否明确要求每个候选带 `candidate_kind`，并写清这两个字段的取值范围。

## 问题与修复

- （暂无）
