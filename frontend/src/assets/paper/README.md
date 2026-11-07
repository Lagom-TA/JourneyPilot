# 旅行纸品视觉素材

本目录存放拟物化旅行纸品家族的 17 张透明背景 WebP 素材（由 [OpenRouter / GPT Image 2.5 Sunburst](https://openrouter.ai/openai/gpt-image-2.5-sunburst) 生成，保持统一的纸张肌理、色调与光影方向）。目前首页（`TravelAtlas.tsx`）使用了其中的主票据、竖版/横版行李签及 4 张地域印刷图，其余为基础预留素材：

| 分类 | 文件名 | 规格说明 | 当前用途 |
|---|---|---|---|
| 书写纸 | `note-square` | 方形便签纸 | 预留素材 |
| 书写纸 | `note-landscape` | 横版便签纸 | 预留素材 |
| 书写纸 | `note-torn` | 撕边便签纸 | 预留素材 |
| 书写纸 | `note-fold` | 折角书写纸 | 预留素材 |
| 旅行纸件 | `ticket-main` | 主旅行票据（左侧正文区 + 右端橙色票根） | 首页灵感票据底图 |
| 旅行纸件 | `ticket-stub` | 独立短票根 | 预留素材 |
| 旅行纸件 | `tag-luggage` | 竖版行李签（顶部带裁角与穿孔） | 桌面端首页行李签 |
| 旅行纸件 | `tag-luggage-wide` | 横版行李签（左侧带穿孔） | 移动端首页行李签 |
| 旅行纸件 | `photo-mount` | 照片底托框 | 预留素材 |
| 连接装饰 | `tape-long` / `tape-short` | 长/短纸胶带 | 预留素材 |
| 连接装饰 | `band-orange` | 橙色纸束带 | 预留素材 |
| 连接装饰 | `photo-corner` | 照片角贴 | 预留素材 |
| 地域印刷 | `print-northwest` | 西北主题插画 | 首页地域配图 |
| 地域印刷 | `print-jiangnan` | 江南主题插画 | 首页地域配图 |
| 地域印刷 | `print-island` | 海岸主题插画 | 首页地域配图 |
| 地域印刷 | `print-southwest` | 山城主题插画 | 首页地域配图 |

## 排版与渲染说明

- 纸品图片仅作为视觉底图，所有文字、图标与交互控件均由前端组件叠加绘制。
- 渲染时保持素材原始宽高比，避免拉伸折角或穿孔；`ticket-main` 的文字排布在左侧票面，天数与箭头置于右侧橙色票根区；`tag-luggage` 与 `tag-luggage-wide` 排版时需预留顶部或左侧的穿孔区域。
