# 出厂基础语料

这里的 Markdown 是随仓库发布的小规模基础语料，用来让知识库检索在没有任何本地种子时也能命中常见旅行常识。内容只覆盖通用做法，不替代景区、铁路和当地交通部门的官方公告。

## 文件与集合

文件名格式为 `<集合名>__<名称>.md`，装载时按前缀分派：

| 前缀 | 出厂集合 | 内容 |
|---|---|---|
| `destinations` | destinations | 目的地区位、景点组合与住宿区域 |
| `local_culture` | local_culture | 本地饮食、习俗与参观礼仪 |
| `travel_tips` | travel_tips | 预约、购票、城市交通与接驳 |
| `visa_policies` | visa_policies | 签证与入境政策（本目录暂未提供） |

`README.md` 本身不会被索引。同一集合内，同名来源重复装载会替换正文与分块，因此更新正文后直接重跑即可。文件改名会生成新的来源，旧来源需要另行删除；用 `--collection` 把语料写入其他集合，也不会删除默认分派留下的副本。

## 内容来源与更新

语料由项目维护者按公开的通用旅行常识整理，不包含具体班次、票价、酒店名称或实时营业信息。景区预约入口、铁路预售期和城市交通规则会调整，修改语料时应先核对官方渠道的当前说法，再更新对应段落。

## 装载

先按根目录 README 启动后端（入口为 `backend/main.py`），再另开一个终端执行：

```bash
python backend/scripts/load_factory_corpus.py
```

脚本从 `backend/data/corpus/factory/` 读取全部语料，按文件名前缀写入 `destinations`、`local_culture` 或 `travel_tips`。需要把整批语料写入同一个集合时，显式指定：

```bash
python backend/scripts/load_factory_corpus.py --collection travel_tips
```

装载要求 `config.yaml` 中 `embedding.enabled` 为 `true`，并会先校验数据库结构。服务启动路径不会自动装载这份语料。
