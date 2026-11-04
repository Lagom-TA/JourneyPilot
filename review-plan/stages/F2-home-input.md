# F2 首页与需求输入

`前端页面` · 前置 [F1](F1-frontend-foundation.md) · [返回总览](../../REVIEW-PLAN.md)

开工前阅读：[工作规则](../rules.md) · 采集员读[采集规范](../capture.md) · 分析员读[分析规范](../analysis.md)

## 范围

- `frontend/src/features/travel/components/planning/`
- `frontend/src/features/chat/components/`：`ConversationThread`、`InputArea`、`MessageBubble`、`ContextCompactionNotice`、`hallmark/`
- `frontend/src/features/presets/components/PresetSelector.tsx`
- `frontend/src/app/layout/`

## 截图清单

⭐ 为[展示镜头](../analysis.md#达标线)。

验收覆盖当前可达界面：默认首页与纸品检查全部视口和关键断点，其他状态使用代表截图及对应交互用例。普通输入中未挂载的旧工具、交付后才可达的队列已明确移交 F3/F4。素材使用真实组件与浏览器内业务接口拦截，不代表真实规划模型或移动设备键盘验收。当前首页以 r6 为准，四场景代表素材为 r5，海岛页签与更早消息为 r6；未变更的表单、人数和日期沿用 r4 复核。

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| H1 ⭐ 一句话规划 | 默认（无独立偏好控件）；输入长文本；包含偏好描述；提交中；提交失败 | 默认全部 + B，其余 M、D | ✅ |
| H2 按条件规划 | 无常用出发地；已有出发地；目的地 1 / 3 / 5（上限）；人数点选与自填；更多偏好展开；校验错误；配置读取中；配置读取失败 | 默认与展开全部 + B，其余 M、D | ✅ |
| H3 目的地搜索 | 搜索中；有候选；无结果；出错；键盘与触摸排序 | M、D | ✅ 候选代表状态与排序用例 |
| H4 日期选择 | 桌面双月；手机底部弹层单月；只选了开始日；已选区间；14 天上限；跨月和跨年 | M、D、B（639 / 640） | ✅ 稳定态与边界用例 |
| H5 ⭐ 旅行灵感图 | 四个场景；悬停；主副纸件填入 | 全部 | ✅ |
| H6 分流确认卡 | 当前首页可达的规划、推荐与只回答组合；交付后的调整入口见 F3 | M、D | ✅ |
| H7 推荐目的地后转入规划 | 选择目的地；继续规划 | M、D | ✅ |
| H8 普通问答 | 用户和助手气泡；流式输出中；已停止生成；错误卡；安全拦截卡；载入更早的对话；整理事件不产生额外提示 | M、D、W | ✅ |
| H9 输入区 | 当前简化输入的常规、停止与停止后状态；旧补全和风格工具不挂载；交付后队列移交 F3/F4 | M、D | ✅ 当前可达范围；移交项未计入通过 |
| H10 内部信息收敛 | 普通旅行界面不展示上下文透镜、模型用量账本和压缩过程；必要影响用旅行语言表达 | M、D | ✅ 代表截图与事件用例 |

## 审查项

- [x] 两种规划模式来回切换时，已填写的内容不丢失；隐藏偏好不混入一句话提交。
- [x] 灵感卡片仅填入当前模式，滚动和聚焦主输入。
- [x] 目的地的键盘排序、触摸排序、删除和上限提示。
- [x] 日期选择的边界：过去的日期、最长天数、清除日期、跨年和夏令时。
- [x] 首页提交后到进入工作台之间的等待与失败状态（拦截接口的浏览器验证）。

## 参考

- 首页与首屏：[a1 · AI](https://www.a1.gallery/category/ai)、[a1 · Travel](https://www.a1.gallery/category/travel)、[a1 · Sections](https://www.a1.gallery/sections)、[minimal · AI](https://minimal.gallery/tag/ai/)、[minimal · Travel](https://minimal.gallery/tag/travel/)、Hero 条目 [Daisy AI](https://supahero.io/hero/daisy-ai) / [Klook](https://supahero.io/hero/klook) / [Airbnb Homes](https://supahero.io/hero/airbnb-homes)
- 组件：[Hero](https://component.gallery/components/hero)、[Segmented control](https://component.gallery/components/segmented-control)（模式切换）、[Combobox](https://component.gallery/components/combobox)（目的地搜索）、[Datepicker](https://component.gallery/components/datepicker)
- 动效：[60fps · AI](https://60fps.design/shots/filter/ai)、[60fps · Chat](https://60fps.design/shots/filter/chat)（H8）、[60fps · Onboarding](https://60fps.design/shots/filter/onboarding)

## 影响下游

- 改动输入区或分流卡 → [F3](F3-generation-workspace.md)、[F6](F6-motion-a11y.md)、[T1](T1-ui-copy.md)
- ⭐ 展示镜头定稿 → [T3](T3-docs-showcase.md)

## 收到的提醒

- [x] 来自 F1-05、F1-06：首页样式已分文件并统一 token 与断点 → 已验证 320–2560px 及关键断点、稳定态日历与目的地候选；本轮表单指定截图复核通过。

## 问题与修复

- [x] F2-01 占位示例与示例卡重复 → 改为一句输入占位与最多两条可填入灵感；沉浸风景配旅行票据与行李签，当前截图为 H1-D/M-default-r6.png。（提交 669f83a）
- [x] F2-02 一句话规划包含独立“补充偏好”控件 → 只保留自由输入与开始操作，偏好通过文字表达；两种模式保留独立草稿，17 项浏览器测试通过。（提交 669f83a）
- [x] F2-03 条件表单拥挤、加减人数与预算常识说明影响填写 → 重做路线与条件分区；人数弹层点选及自填，预算仅在无效字段就近标记；复核 H2-D/M/T-filled-r4.png、H2-D/M-travelers-custom-r4.png 通过。（提交 669f83a）
- [x] F2-04 普通旅行对话暴露上下文、用量与技术详情 → 移除对应界面入口与整理提示，保留旅行语言和恢复操作；定向浏览器测试通过，截图 H8-D/M-answer-r3.png。（提交 669f83a）
- [x] F2-05 填写下一字段时出发地候选仍停留并遮挡操作 → 失焦、Escape 和切换模式时收起并取消旧查询；对应浏览器用例通过。（提交 669f83a）
- [x] F2-06 右侧灵感贴画粗糙，缺少可复用素材 → 采用 D-07 的旅行票据与行李签，生成 16 个基础单元和手机横签，共 17 张透明 WebP；真实纸形接入首页，文字与动作由组件表达，见 [素材方案](../F2-paper-assets.md)。（提交 669f83a）
- [x] F2-07 〔r5〕窄签日期断行、海岛页签对比不足、宽屏对话过宽 → 天数与单位整组换行、页签使用深绿实底、普通对话居中限宽；三项 r6 定向复核均已解决。（提交 669f83a）

## 设计与验收结论

- [首页与需求输入设计结论](../F2-design-options.md)：信息只服务旅行理解和操作，视觉表达要大胆；沉浸风景为主体、融合原色拼贴，一句话规划不设置独立偏好控件，见 D-05。
- [纸品与交互素材](../F2-paper-assets.md)：17 件生产素材与完整提示词位于 `frontend/src/assets/paper/`，概览为 `output/review/F2/paper-library.png`；首页只请求使用中的纸件。
- 素材索引：`output/review/F2/manifest.md`；本轮补齐 55 个代表状态及 8 个定向修复状态，均无页面脚本错误和漏拦截业务请求。
- 视觉复核：GPT 6.1 Terra 的 `terra-form-r4-review.md`、`final-conversation-review.md`、`final-home-r5-review.md` 覆盖表单、普通对话及最终首页；最后三项修复经 r6 逐项确认已解决，当前约定视觉范围收尾。
- 验证：最终 `npm run check` 通过（类型、lint、198 项单元测试、构建）；已有 17 项首页用例与隐藏诊断用例通过，纸品接入后 5 项受影响用例及修复后 2 项定向验证通过；提交前 ruff、配置文档检查、配置验证及 1003 项非数据库后端测试通过。
- 边界：业务接口由浏览器拦截，未调用规划模型、写数据库或重启共享后端。动态录屏与全工作台衔接由 F3/F6 接续，旧工具及交付后队列按 H9 所述移交。
