# AI 工作过程与恢复提示调研

- 调研时间：2026-10-29
- 用途：`20261029-2325-floating-recovery-notice`、`20261029-2325-work-activity-feed`、`20261029-2325-workspace-followup-composer`
- 范围：公开的工作进度、工具活动、结果核查与后续输入；不采集或展示模型私有原始思维链。

## 证据等级

- A：本轮成功读取页面正文；只引用正文明确写出的内容。
- B：官方页面的搜索摘要／摘要正文可读，但直接 Fetch 未成功；不作为像素级视觉证据。
- C：第三方文字资料，只作辅助，不据此声称主流产品的统一视觉规范。

## 来源与可用结论

| 来源 | 证据 | 实际看到的内容 | 对本次设计的限制与用途 |
| --- | --- | --- | --- |
| [OpenAI：ChatGPT 中的深度研究](https://help.openai.com/zh-hans-cn/articles/10500283-deep-research-in-chatgpt#1) | B | 官方摘要说明可在研究期间跟踪进度、中断并调整重点；完成后报告含来源与活动历史。 | 支持“过程可查看、完成后保留历史、允许继续调整”的信息架构。没有据此推断其卡片、颜色、动画或尺寸。 |
| [Claude：Enable and use web search](https://support.claude.com/en/articles/10684626-enable-and-use-web-search) | B | 官方摘要说明搜索时出现明确的搜索中指示，会处理多个来源；回答附直接引用、来源链接和必要引文。 | 支持“进行中状态轻量可见、结果可核查”，不要求把每个来源或每次调用都做成卡片。未据此推断其具体视觉样式。 |
| [Perplexity：What is Pro Search?](https://www.perplexity.ai/help-center/en/articles/10352903-what-is-pro-search) | B | 官方摘要说明会执行多次搜索、阅读与综合，提供来源，并可用后续问题继续对话。 | 支持将多次工具调用收进同一工作过程，并在结束后保留追问入口。直接 Fetch 返回 404，未声称看过其实时界面。 |
| [Perplexity 产品综述（第三方）](https://journals.library.ualberta.ca/jchla/index.php/jchla/article/download/29877/22213/83438#1#1#1) | C | 文字描述结果中的 Sources 与 Tasks：前者核查来源，后者概述检索任务。 | 仅辅助说明“任务过程”和“来源结果”可分层查看，不照搬其标签或页面结构。 |
| [Google Help：Gemini Deep Research](https://support.google.com/gemini/answer/15719111?hl=zh-Hans) | B | 官方摘要提到来源选择、生成前编辑研究计划，以及开始／完成研究流程。 | 只支持“先确认计划、再研究、完成后核查”的职责划分，不作为 Gemini 过程区视觉证据。 |
| [Cursor：Agent](https://cursor.com/docs/agent/overview) 与 [Agent SDK Sessions](https://cursor.com/docs/agent-sdk/reference/sessions) | A | 正文说明 Agent 可执行搜索、文件和命令操作，用户可在执行中追加指引；SDK 文档另有工具动作、结果与时间线事件。 | 支持工作过程与用户指引处于同一上下文。SDK 的字段与 Trace 能力不等于普通聊天 UI 默认展示内部参数或输出。 |
| [AWS Cloudscape：GenAI Timeline](https://cloudscape.design/gen-ai/patterns/timeline-overview/) | A | 官方设计系统建议用时间线呈现 Agent 事件日志，以图标区分状态，并明确用户离开底部后不应被强制自动滚动。 | 直接支持单列连续时间线、轻量状态与保留用户滚动控制；不要求复制其视觉样式。 |
| [Component Gallery：Toast](https://component.gallery/components/toast/) | A | 正文将 Toast／Snackbar 定义为“位于其他内容之上的一层”的提示。 | 支持恢复提示使用非通栏浮层。该定义不等于自动消失；本项目的持续恢复状态和“重试”仍按现有业务状态处理。 |
| [Component Gallery：Accordion](https://component.gallery/components/accordion/) 与 [Popover](https://component.gallery/components/popover/) | A（前期同站调研） | 前期记录确认展开区需要显式控件和可读状态，详情可由点击触发。 | 支持工具详情按需展开；不要求使用 Popover，也不把 hover 当成唯一入口。 |
| [60fps](https://60fps.design/) 与[其他设计入口前期调研](20261029-itinerary-redesign.md) | A＋原记录 | 本轮读到 60fps 首页可按 Chat、Assistant、Loading、Progress 浏览；前期记录含 Component Gallery、Minimal Gallery、One Page Love、Grainient 等站点的正文与 Fetch 失败边界。A1、Recent、Posts 等未找到直接相关证据。 | 只复用“保持上下文稳定、主动点击展开、避免无依据动画”的结论；没有为每个网站补写未经验证的 AI 产品模式。 |

## 形成的设计判断

1. **恢复提示是状态层，不是内容区。** 持续提示在上层浮框中保留，重试仍可用；不推挤工作区，不用模态遮罩打断阅读。
2. **工作过程是一条连续动态，不是诊断卡墙。** 阶段标题说明当前真实工作，下面按时间／阶段列出公开活动；减少嵌套边框、重复图标、重复状态和过宽阅读列。若自动跟随新活动，只在用户仍位于底部时启用；用户上翻后不得强制拉回。
3. **默认看行动，点击看证据。** 行内先显示中文行动名称与简短输入／结果；展开后再看工具显示名、可读输入、公开摘要、结果预览和来源。这里展示的是工具活动与公开摘要，不是私有原始思维链。
4. **别名覆盖所有入口。** 工具标题、折叠行、展开标题、摘要、无障碍名称和历史恢复使用同一中文显示投影；未知工具回退到中文类别，不能把内部标识当作兜底文案。
5. **数量必须来自真实公开计数。** 预览列表可能截断，不能用预览长度声称总结果数。有摘要就保留摘要；只有确认多条总数时才显示“返回 X 条结果”。
6. **完成不是对话终点。** 过程结束后在同一工作台提供后续输入，沿用现有会话、Run 与审批合同。交付后的行程查看和过程／调整可以各有视图，但不另建承担同一职责的页面。
7. **动画不是本轮借鉴结论。** 来源未提供可核实的完整动效录屏；实现沿用项目既有短时、可减弱动效，不编造参考产品的曲线或时长。

## 调研限制

本轮没有登录 ChatGPT、Claude、Perplexity 或 Gemini 做账号内实测，也没有把官方功能说明当作视觉截图。因此方案借鉴的是可证实的信息层级与交互职责，不声称复刻某个产品。JourneyPilot 的具体中文文案、密度、暖色纸面与桌面／手机布局由自身工作台上下文决定。
