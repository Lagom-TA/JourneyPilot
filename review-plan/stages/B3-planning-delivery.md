# B3 规划主链（下）：调研、组合与交付

`后端逻辑` · 前置 [B2](B2-planning-intake.md) · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)

## 范围

- `backend/travel_agent/planning/research/`：调度、三个研究角色、产出、数据包、候选目录、补查与重做、失败处理
- `backend/travel_agent/planning/itinerary/`（含 `mutations/`）
- `backend/travel_agent/planning/weather/`
- `backend/travel_agent/planning/costs/`
- `backend/travel_agent/planning/delivery/`（含 `public/`）
- `backend/travel_agent/api/routes/trip_runs/delivery.py`、`workspace.py`

## 审查项

- [ ] **调研次序**：目的地研究先行，交通和住宿并行后汇合；任一侧失败、超时或没有结果时，流程往哪里走、能否带着缺口继续交付。
- [ ] **数据流转**：从调研数据包到候选目录再到组合，字段和来源一路保留，来源记录挂在它支撑的那条事实旁边。
- [ ] **补查与重做**：补查保留既有成果，只增加缺的信息；只有既有成果整体不可用时才重做；补查受预算、取消和时限约束；查无结果和技术失败分开返回。
- [ ] **组合与落地**：时间线、交通衔接、跨夜住宿、营业时间，以及天数边界（1 天、14 天）。
- [ ] **附属产出**：标题生成失败时行程照常可用；天气对行程的影响和替代安排；费用估算覆盖了哪些项目。
- [ ] **交付一致性**：交付包是唯一的事实来源；行程、地图、报告、PDF 四种投影内容一致；部分交付（含“尚未安排”）和投影失败时的状态。
- [ ] **交付后更新**：天气刷新、PDF 导出和交付后修改遇到交付包版本变化时的冲突处理。
- [ ] **修改相关模块**：`itinerary/mutations/`、`delivery/workspace_mutations` 和工作台修改接口各被谁调用、走什么路径。

## 影响下游

- 改动交付包结构或投影 → [F4](F4-delivery-workspace.md)、[B4](B4-runtime-streaming.md)
- 改动研究角色、组合或标题的输入输出 → [T2](T2-prompts-outputs.md)
- 改动部分交付、失败出口 → [F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)、[T1](T1-ui-copy.md)

## 收到的提醒

- [ ] 来自 B1-05：删除无调用方的参考班次文案、住宿基点和开放时间模块 → 请复核交付及行程所需能力是否均由现有主流程承担。
- [ ] 来自 S0：杭州 1 日会话 run `trip_93ae8b4793d0597f813cbf36c4985f35` 在研究门停下（“目的地调研未完成”）。日志：`destination_researcher` 最后一次模型调用 205 秒、输出 18153 token，随后 `ResearchPacket` 结构校验失败，6 处 `candidates.N` 缺少判别字段 `candidate_kind`（`union_tag_not_found`），整份目的地调研被判失败，没有任何修补或降级。同一会话点“重试未完成的研究”后又失败一次，这次是 12 处错误：`weather_sensitivity.cold_sensitivity`、`wind_sensitivity` 被模型填了 `medium`，而枚举只允许 `none/low/high`。两次原因不同、结果相同，整份研究包都被丢弃。请检查：校验失败时能否只让模型修正出错字段、或对枚举做宽容归一，而不是丢弃整次调研。
- [ ] 来自 S0：同一批真实运行里，苏州、成都城内 1 日在默认 450 秒收口时限下都因交通查询未完成而停在研究门，且已开始的 run 带着自己的 deadline 快照，重试沿用旧时限；请确认这是有意设计，以及重试时给用户的说明是否讲清了这一点。

## 问题与修复

- （暂无）
