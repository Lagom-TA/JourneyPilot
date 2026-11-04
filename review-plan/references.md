# 外部参考库

[返回总览](../REVIEW-PLAN.md) · 给 `前端页面` 两侧和 T3

- 参考库用来校准“展示级”的标准，并寻找可以借鉴的处理方式；不照搬布局和视觉。
- 借鉴了某个条目时，在问题记录里附上链接。
- 不下载或使用站内的素材。只看公开内容，不登录，不付费。
- 获取方式：📖 是文字、代码或 Markdown，分析员可以自己读取；🎬 是图片墙或视频，由采集员按[采集规范](capture.md#参考素材)截图或录屏。

## component.gallery 📖

各大设计系统的组件规范与实现对比，附无障碍要求。

| 入口 | 用于 |
|---|---|
| [Hero](https://component.gallery/components/hero) · [Segmented control](https://component.gallery/components/segmented-control) · [Combobox](https://component.gallery/components/combobox) · [Datepicker](https://component.gallery/components/datepicker) | F2 |
| [Progress indicator](https://component.gallery/components/progress-indicator) · [Progress bar](https://component.gallery/components/progress-bar) · [Stepper](https://component.gallery/components/stepper) · [Skeleton](https://component.gallery/components/skeleton) · [Spinner](https://component.gallery/components/spinner) · [Accordion](https://component.gallery/components/accordion) | F3 |
| [Tabs](https://component.gallery/components/tabs) · [Card](https://component.gallery/components/card) · [Popover](https://component.gallery/components/popover) · [Badge](https://component.gallery/components/badge) · [Toast](https://component.gallery/components/toast) | F4 |
| [Navigation](https://component.gallery/components/navigation) · [Drawer](https://component.gallery/components/drawer) · [Empty state](https://component.gallery/components/empty-state) · [Form](https://component.gallery/components/form) · [File upload](https://component.gallery/components/file-upload) · [Modal](https://component.gallery/components/modal) | F5、F6 |

## 60fps.design 🎬

真实 iOS App 的交互动效录屏，按交互模式和效果筛选。以手机端为主，最适合用来判断 M 视口。有 PRO 入口，只看公开部分。

| 入口 | 用于 |
|---|---|
| [AI](https://60fps.design/shots/filter/ai) · [Chat](https://60fps.design/shots/filter/chat) · [Assistant](https://60fps.design/shots/filter/assistant) | F2 普通问答、F3 生成过程 |
| [Loading](https://60fps.design/shots/filter/loading) · [Shimmer](https://60fps.design/shots/filter/shimmer) · [Success State](https://60fps.design/shots/filter/success-state) | F3 进行中与完成 |
| [Map](https://60fps.design/shots/filter/map) · [Bottom Sheet](https://60fps.design/shots/filter/bottom-sheet) · [Tabs](https://60fps.design/shots/filter/tabs) | F4 地图、手机抽屉、场景切换 |
| [Empty State](https://60fps.design/shots/filter/empty) | F5 |
| [Onboarding](https://60fps.design/shots/filter/onboarding) | F2 |
| [Stagger](https://60fps.design/shots/filter/stagger) · [Spring Physics](https://60fps.design/shots/filter/spring-physics) · [Motion](https://60fps.design/motion) | F6 |

## a1.gallery 🎬

分类齐全的网站画廊，适合用作首页和门面参考。部分条目需要登录或付费才能看到。

| 入口 | 用于 |
|---|---|
| [AI](https://www.a1.gallery/category/ai) · [Software](https://www.a1.gallery/category/software) · [Sections](https://www.a1.gallery/sections) | F2 首页 |
| [Travel](https://www.a1.gallery/category/travel) | F2 首页、T3 |
| [OG images](https://www.a1.gallery/og-images) | T3 社交预览图 |

## minimal.gallery 🎬

极简风格网站画廊，只取两个标签。

| 入口 | 用于 |
|---|---|
| [AI](https://minimal.gallery/tag/ai/) · [Travel](https://minimal.gallery/tag/travel/) | F2 首页、T3 |

## supahero.io 🎬

首屏 Hero 区画廊。站点没有分类，只用下列条目。

| 入口 | 用于 |
|---|---|
| [Daisy AI](https://supahero.io/hero/daisy-ai) · [Klook](https://supahero.io/hero/klook) · [Airbnb Homes](https://supahero.io/hero/airbnb-homes) | F2 H1 |

## navbar.gallery 🎬

导航设计画廊，以营销官网为主，只取导航形式。

| 入口 | 用于 |
|---|---|
| [Side bar](https://navbar.gallery/type/side-bar) · [Dropdowns](https://navbar.gallery/type/dropdowns) · [Full screen](https://navbar.gallery/type/full-screen) | F5 P1 导航与手机抽屉、F3 侧栏 |

## posts.design 📖

品牌在社交平台上发布的帖子、发布视频和 OG 图。每个页面在路径后加 `.md` 就能得到 Markdown 版本，使用说明见 [llms.txt](https://posts.design/llms.txt)。未登录只能看到第一页结果；搜索接口不可用时，改用各页面的 `.md` 版本。

| 入口 | 用于 |
|---|---|
| [Launches](https://posts.design/launches) · [Best of 2026](https://posts.design/launches/best-2026) | T3 演示视频与动图、F6 |
| [OpenGraph](https://posts.design/opengraph) | T3 社交预览图 |
| [Top](https://posts.design/top) · [搜索接口](https://posts.design/api/post-search?q=launch) | T3 |

## recent.design 🎬

每日更新的设计精选，没有搜索功能，也没有稳定的筛选入口。在 S0 由采集员挑选后截图定格，之后只看定格下来的素材。

| 入口 | 用于 |
|---|---|
| [Websites](https://recent.design/websites) | F2、F4 |
| [Launch videos](https://recent.design/launch-videos) | T3、F6 |

## 未收录

- onepagelove.com：用途与 a1.gallery 重复。
- grainient.supply：付费素材站，授权条款没有说明开源项目能否使用。
