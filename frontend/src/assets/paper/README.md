# 旅行纸品素材

同一纸材家族的 16 个基础单元，另有手机横版行李签，共 17 张透明 WebP。首页使用主票据、适合当前屏幕比例的行李签和对应地域印刷图，其余按具体场景选用。

| 家族 | 素材 |
|---|---|
| 书写纸 | `note-square` 方便签、`note-landscape` 横便签、`note-torn` 撕边纸、`note-fold` 折角纸 |
| 旅行纸件 | `ticket-main` 主票据、`ticket-stub` 短票根、`tag-luggage` 竖行李签、`photo-mount` 照片底托 |
| 连接件 | `tape-long` 长纸胶带、`tape-short` 短纸胶带、`band-orange` 橙纸带、`photo-corner` 照片角贴 |
| 地域印刷 | `print-northwest` 西北、`print-jiangnan` 江南、`print-island` 海岸、`print-southwest` 山城 |
| 比例适配 | `tag-luggage-wide` 横行李签 |

## 来源

- 素材由 [OpenRouter / GPT Image 2.5 Sunburst](https://openrouter.ai/openai/gpt-image-2.5-sunburst) 生成，使用统一的纸材、色彩与光向，以透明 WebP 提供。

## 使用

所有文字、图标、选择与加载状态均由页面绘制；素材图层不接收点击。外部投影作用于装饰纸形，摆放、旋转和按压由 CSS 控制。当前主题的风景与地域图解码后共同切换，并预取下一主题；未使用的纸型和连接件不进入当前页面请求。

主票据的文字区位于左侧，右端橙色票根显示天数与动作箭头；竖行李签避开顶部裁角与孔位，手机横签避开左侧孔位。按图片实际比例渲染。长内容需要独立纸边或切片方案，不拉伸折角与孔洞。

地域图表达旅行氛围，不是具体地标的照片或可导航地图。页面按当前真实内容选择纸品，普通长回答保留清楚的阅读排版。
