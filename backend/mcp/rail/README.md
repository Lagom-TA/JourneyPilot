# 12306 铁路站点离线快照

本目录维护仓内 `12306-train` MCP 服务所使用的全国铁路车站基础数据快照，供后端在离线环境下快速、确定地解析车站名称与电报码。

## 数据文件说明

- **`station_name.js`**：12306 官方站表资源（<https://kyfw.12306.cn/otn/resources/js/framework/station_name.js>）的原样快照。记录以 `@` 分隔，单条记录内以 `|` 分隔各字段：`[0]` 拼音缩写、`[1]` 中文站名、`[2]` 电报码、`[3]` 全拼、`[4]` 简拼、`[5]` 序号、`[6]` 城市代码、`[7]` 城市名。
- **`station_name.meta.json`**：记录快照的抓取元信息（`source_url`、`fetched_at`、`byte_size`、`record_count`）。后端 `backend/travel_agent/integrations/rail/stations.py` 在首次调用时从本地载入站表，并通过元信息校验文件完整性与快照新鲜度（可在 `/api/health/ready` 的 `data_snapshots` 字段查看，默认新鲜度提醒阈值为 `Settings.data_snapshots.station_max_age_days` 的 90 天）。

关于该站表数据的来源声明与使用条款，请参阅仓库根目录的 [NOTICE](../../../NOTICE)。

## 更新快照流程

1. 从上述官方 URL 下载最新的 `station_name.js` 覆盖本目录同名文件。
2. 同步更新 `station_name.meta.json` 中的 `fetched_at`、`byte_size` 与 `record_count` 字段。
3. 重启后端服务，使进程内的站表缓存（`station_table()`）重新加载最新数据。
