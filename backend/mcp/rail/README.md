# 12306-train MCP 服务（仓内实现）

`station_name.js` 是 12306 官方站表的**逐字快照**：

- 来源：<https://kyfw.12306.cn/otn/resources/js/framework/station_name.js>
- 抓取：2026-07-29，HTTP 200，167709 字节，3375 条记录

记录格式为 `@` 分隔记录、`|` 分隔字段：`[0]` 拼音缩写，`[1]` 中文站名，`[2]` 电报码，`[3]` 全拼，`[4]` 简拼，`[5]` 序号，`[6]` 城市代码，`[7]` 城市名。

快照随仓库提交，让站点解析确定且离线可用：首次使用时由 `backend/travel_agent/integrations/rail/stations.py` 载入，运行时**不会**联网拉取。

同目录的 `station_name.meta.json` 用机器可读形式记录同一组事实（`source_url` / `fetched_at` / `byte_size` / `record_count`）。`station_snapshot_freshness()` 用它判断快照年龄，`/api/health/ready` 的 `data_snapshots` 组件也会报告。12306 不发布版本号，字节数与记录数是上游唯一提供的指纹，也是发现"只下载了半个文件"的唯一办法。

许可与再分发：该文件是 12306 公开站点资源的快照，仓库仅用于离线站点解析；再分发或商用前请核对 12306 的相关条款。来源与许可见仓库根 [NOTICE](../../../NOTICE)。

## 刷新流程

1. 原样重新下载上面的 URL。
2. 更新 `station_name.meta.json` 的**每一个**字段，包括 `fetched_at`。
3. **重启后端。** `station_table()` 及其两个派生索引是 `lru_cache(maxsize=1)`，解析结果与进程同寿；只换磁盘文件不会改变正在运行的服务，旧表会继续回答。
4. 核对指纹与年龄阈值保持一致。

年龄阈值：`Settings.data_snapshots.station_max_age_days`（默认 90 天）。快照过期只**报告**，不阻断启动。
