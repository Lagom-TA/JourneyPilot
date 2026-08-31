# 待决清单

这里放**已观察、已确认修法形状、但需要行为级拍板所以不做**的项。每一条必须写清三件事：
实测到的是什么、修了会动什么、它在等哪个决定。修掉一条就删一条，不留历史存档。

---

## `worker_failed:` 前缀的实际作用域为零

来源：`2026-08-26-adoption-review.md` §4.4 缺陷一。

1. **作用域实测为零。** `worker_failed:` 是 `format_worker_last_error` 的兜底前缀，
   却不在 `provider_failure._EXPLICIT_EXTERNAL_FAILURE_MARKERS` 里。四道门
   （`artifact_gate.py:212/228/246`、`candidate_gate.py:1706`）全部先过
   `is_provider_or_model_failure` —— 带它的前缀不匹配任何 marker，返回 False，
   门根本不进 `classify_provider_failure`。
2. **分类随残留文本漂移。** 带它的文本一旦落进 free-text 扫描，分类由异常文案里
   碰巧含什么词决定：同一类失败，文案里多一个 "connection" 就从 incomplete 翻
   transient。它今天唯一真正生效的地方是 `worker_errors._already_prefixed`
   （防二次加前缀）。
3. **修它要动路由。** 把它加进 `_EXPLICIT_EXTERNAL_FAILURE_MARKERS` 会让四道门
   当场翻面：原本停在 Delivery Integrity 分支的失败全部换到内容失败分支，
   reason_code、重试语义、域关闭逻辑都跟着变。这是路由级变更，需要单独立项，
   先回答「兜底失败到底该按什么语义处理」，再动手。
   **禁止的修法：** 用 `*KNOWN_PREFIXES` splat 全表混进名单 —— 那是无人拍板的
   路由变更。

## 收编三处协议外裸写路径

`run_control.py:721-726`（按节点身份写不带前缀的文案）、
`itinerary_planner/node.py:3010`（裸文案）、`:3731`（`str(exc)`）不经
`format_worker_last_error`。收编是行为决策：例如含 "research packet" 字样的异常文本今天走 free-text
落 incomplete，过 `format_worker_last_error` 会命中关键词分支变成 `schema_gate:`
前缀，`is_provider` 从 False 翻 True，artifact_gate 从 Delivery Integrity 分支
换到内容失败分支。路由级变化，单独立项。

## 合并两份 query-miss 词表

写方三条（`worker_errors._QUERY_MISS_MARKERS`）对读方一条
（`provider_failure._QUERY_MISS_MARKERS`），差集 `{"no results", "empty result"}`。
读方注释（`provider_failure.py:24-26`）自陈这是刻意收缩：权威信号是
`provider_empty:` 前缀，读方词表只兜 Provider 自己措辞的空结果。合并会让未加
前缀文本的 reason_code 从 `provider_incomplete_result` 变 `provider_empty_result`，
是行为决策，单独立项。
