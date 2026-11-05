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

验收覆盖当前可达界面：默认首页与纸品检查全部视口和关键断点，其他状态使用代表截图及对应交互用例。普通输入中未挂载的旧工具、交付后才可达的队列已明确移交 F3/F4。素材使用真实组件与浏览器内业务接口拦截，不代表真实规划模型或移动设备键盘验收。当前首页、四主题纸组、整宽玻璃横条和首屏构图以 r10 为准；普通对话沿用 r6，未变更的人数和日期视觉结论沿用 r4。自然输入随内容与宽度自动伸缩，主题磨砂进度满格切换，暂停时保留原进度。

| 场景 | 必截状态 | 视口 | 进度 |
|---|---|---|---|
| H1 ⭐ 一句话规划 | 默认（无独立偏好控件）；输入自适应伸缩；包含偏好描述；提交中；提交失败 | 默认全部 + B，其余 M、D | ✅ r10 |
| H2 按条件规划 | 无常用出发地；已有出发地；目的地 1 / 3 / 5（上限）；人数点选与自填；更多偏好展开；校验错误；配置读取中；配置读取失败 | 默认与展开全部 + B，其余 M、D | ✅ |
| H3 目的地搜索 | 搜索中；有候选；无结果；出错；键盘与触摸排序 | M、D | ✅ 候选代表状态与排序用例 |
| H4 日期选择 | 桌面双月；手机底部弹层单月；只选了开始日；已选区间；14 天上限；跨月和跨年 | M、D、B（639 / 640） | ✅ 稳定态与边界用例 |
| H5 ⭐ 旅行灵感图 | 同主题票据与行李签；整宽玻璃栏；磨砂进度与自动切换；悬停及点选采用 | 默认全部，其余 M、T、D | ✅ r10 |
| H6 分流确认卡 | 当前首页可达的规划、推荐与只回答组合；交付后的调整入口见 F3 | M、D | ✅ |
| H7 推荐目的地后转入规划 | 选择目的地；继续规划 | M、D | ✅ |
| H8 普通问答 | 用户和助手气泡；流式输出中；已停止生成；错误卡；安全拦截卡；载入更早的对话；整理事件不产生额外提示 | M、D、W | ✅ |
| H9 输入区 | 当前简化输入的常规、停止与停止后状态；旧补全和风格工具不挂载；交付后队列移交 F3/F4 | M、D | ✅ 当前可达范围；移交项未计入通过 |
| H10 内部信息收敛 | 普通旅行界面不展示上下文透镜、模型用量账本和压缩过程；必要影响用旅行语言表达 | M、D | ✅ 代表截图与事件用例 |

## 审查项

- [x] 两种规划模式来回切换时，已填写的内容不丢失；隐藏偏好不混入一句话提交。
- [x] 两件纸属于同一提案，仅点选时更新当前模式并聚焦主输入；纸面不显示动作说明。
- [x] 磨砂进度与 14 秒自动切换同步，悬停、焦点、填写和隐藏页面保留进度并暂停，无独立暂停按钮。
- [x] 输入内容、程序采用灵感、切回模式、宽度或字体变化时重新计算输入高度，不显示拖拽角。
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

- [x] 来自 F5-08：首页仅在已选择风格或风格失效时显示上下文，选择风格会新建旅行，默认一句话规划仍无独立偏好控件；选择与失效两条浏览器路径通过。

- [x] 来自 F1-05、F1-06：首页样式已分文件并统一 token 与断点 → 已验证 320–2560px 及关键断点、稳定态日历与目的地候选；本轮表单指定截图复核通过。
- [x] 来自后端综合验收：旧标题的换行空白和“从哪里出发”字段选择器与当前界面不一致 → 已按现有标题及“出发地”标签更新，使用既有数据库和 API 的 `smoke`、`mobile-navigation`、`home-inspiration`、`planner-intake`、`multi-round-intake` 共 31 项通过。

## 问题与修复

- [x] F2-01 占位示例与示例卡重复 → 改为一句输入占位与同一组可采用的旅行票据与行李签；沉浸风景配原色纸品，当前截图为 H1-D/M-default-r10.png。（提交 669f83a、627f341）
- [x] F2-02 一句话规划包含独立“补充偏好”控件 → 只保留自由输入与开始操作，偏好通过文字表达；两种模式保留独立草稿，17 项浏览器测试通过。（提交 669f83a）
- [x] F2-03 条件表单拥挤、加减人数与预算常识说明影响填写 → 重做路线与条件分区；人数弹层点选及自填，预算仅在无效字段就近标记；复核 H2-D/M/T-filled-r4.png、H2-D/M-travelers-custom-r4.png 通过。（提交 669f83a）
- [x] F2-04 普通旅行对话暴露上下文、用量与技术详情 → 移除对应界面入口与整理提示，保留旅行语言和恢复操作；定向浏览器测试通过，截图 H8-D/M-answer-r3.png。（提交 669f83a）
- [x] F2-05 填写下一字段时出发地候选仍停留并遮挡操作 → 失焦、Escape 和切换模式时收起并取消旧查询；对应浏览器用例通过。（提交 669f83a）
- [x] F2-06 右侧灵感贴画粗糙，缺少可复用素材 → 采用 D-07 的旅行票据与行李签，生成 16 个基础单元和手机横签，共 17 张透明 WebP；真实纸形接入首页，文字与动作由组件表达，见 [素材方案](../F2-paper-assets.md)。（提交 669f83a）
- [x] F2-07 〔r5〕窄签日期断行、海岛页签对比不足、宽屏对话过宽 → 天数与单位整组换行、页签使用深绿实底、普通对话居中限宽；三项 r6 定向复核均已解决。（提交 669f83a）

- [x] F2-08 〔r6〕两件纸主题割裂、内容空泛，轮换缺少清楚机制 → 同一提案分为路线票据与插画旅行时刻；背景和地域图整组解码，每 14 秒轮换，悬停、填写、焦点与隐藏页面冻结并保留磨砂进度，满格切换；无“填入”文案或暂停按钮。（提交 627f341）
- [x] F2-09 〔r8、r9〕上方切换条、侧边标题、纸品重叠及首屏留白关系不当 → 采用上方整宽玻璃横条，与旋转票据两端对齐；两纸独立留距；宽屏两列居中，标题与输入卡间距 48–80px、矮桌面 44px、手机 40px，复拍 r10。（提交 627f341）
- [x] F2-10 输入框仍有拖拽角且不能随内容伸缩 → 去除手动缩放，按内容、模式、宽度和字体重算高度，删除后缩回；长文本及回缩用例通过，录屏 V2-D-glass-progress-r10.webm。（提交 627f341）
- [x] F2-11 导航与表单 e2e 仍使用旧标题/字段名称 → 标题匹配允许视觉换行空白，出发地使用当前标签；五个指定规格共 31 项通过。（提交 627f341）

## 设计与验收结论

- [首页与需求输入设计结论](../F2-design-options.md)：信息只服务旅行理解和操作，视觉表达要大胆；沉浸风景为主体、融合原色拼贴，一句话规划不设置独立偏好控件，见 D-05。
- [纸品与交互素材](../F2-paper-assets.md)：17 件生产素材与完整提示词位于 `frontend/src/assets/paper/`；首页使用主票据、对应屏幕的行李签与当前地域图，并预取下一主题。
- 当前素材索引：`output/review/F2/manifest.md`；r10 包含 19 张主题/交互图、两段 V2 录屏及 11 尺寸断点截图。画面按真实纸形 Alpha 检查文字边界，并检查纸件间距、玻璃栏两端与标题到输入卡的间距。
- 当前视觉复核：GPT 6.1 Terra 的 `atlas-r10-independent-review.md` 对 r10 所展示图片与录屏抽帧给出限定范围通过，无明确阻塞；横条整宽、左侧位置、标题间距与纸件分离均已确认。未变更的表单、普通对话结论分别见 `terra-form-r4-review.md`、`final-conversation-review.md`。
- 验证：最终 `npm run check` 通过（类型、lint、198 项单元测试、构建），五个指定浏览器规格共 31 项通过；r10 排版覆盖 320–2560px 与关键断点，进度保持/续走、整组素材失败、输入伸缩及两种草稿均通过。后端代码未变更，沿用此前 ruff、配置检查及 1003 项非数据库测试结论。
- 边界：画面和规划交互使用浏览器内业务接口拦截，不代表真实规划模型或移动设备键盘验收；导航与 HTTP 冒烟沿用现有数据库/API 配置。全工作台衔接、旧工具和交付后队列由 F3/F4/F6 接续。
