"""配置 schema：字段、默认值与校验。**全仓唯一定义处**。

这里只声明「未配置时程序怎么跑」。怎么把 YAML 与环境变量读成这些对象归
`loader.py`；帮用户快速填好模型段的那些具体 provider 值归 `providers.py` 与
`backend/travel_agent/resources/providers/*.yaml` —— 把某家 provider 的 base_url 写成这里的默认值，等于
让一次私人部署成为所有人的默认。

每个模型都 ``extra="forbid"``：拼错的字段名会直接报错，而不是静默忽略。
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: config.yaml 的结构版本。加载器按它迁移旧结构（`loader.migrate_config_data`）。
CONFIG_VERSION = 2


class StrictConfig(BaseModel):
    """所有配置段的基类：未知字段拒绝，不静默忽略。"""

    model_config = ConfigDict(extra="forbid")


class FileLogConfig(StrictConfig):
    enabled: bool = True
    path: str = "logs/"
    rotation: str = "1 day"
    retention: str = "7 days"


class LoggingConfig(StrictConfig):
    level: str = "info"
    file: FileLogConfig = Field(default_factory=FileLogConfig)


# 一次补全允许输出的 token 上限。**唯一定义处**：下面两档模型配置与
# ``api/schemas/system.ModelConfigRequest`` 都从这里读取，避免三份独立副本
# 在 POST 省略该字段时把运行中的部署静默降级。
#
# 这只是请求默认值，不是 Run 配额，也不是模型的通用上限。部署可以按模型支持
# 选择其他正数。
MAX_COMPLETION_TOKENS = 65536


class PrimaryModelConfig(StrictConfig):
    """主力 LLM 配置（用于复杂规划等高推理任务）
    默认: MiniMax-M2.7 @ api.minimaxi.com/v1
    """
    api_key: str = ""
    model_name: str = "MiniMax-M2.7"
    base_url: str = "https://api.minimaxi.com/v1"
    use_responses_api: bool = Field(default=False, description="使用 OpenAI Responses 接口；false 使用 Chat Completions。")
    responses_streaming: bool = Field(default=False, description="Responses 使用流式传输；ainvoke 聚合完整响应后返回。")
    token_limit_field: Optional[Literal["max_tokens", "max_completion_tokens", "both"]] = Field(
        default=None, description="Chat Completions 输出上限字段；null 使用 provider preset。",
    )
    max_tokens: int = Field(default=MAX_COMPLETION_TOKENS, ge=1)
    temperature: float = 0.7
    reasoning_effort: Literal["low", "medium"] = "medium"
    timeout: int = 120  # LLM 请求超时（秒）；思维模型（MiniMax-M2.7、DeepSeek-R1）复杂推理可能超过 60s


class FastModelConfig(StrictConfig):
    """轻量 LLM 配置（用于简单问答、路由判断等低延迟任务）

    方案A（默认）: MiniMax-M2.7 @ api.minimaxi.com/v1
    方案B（可选）: 本地 Qwen，model_name="qwen3.5:4b", base_url="http://localhost:11434/v1"
    """
    api_key: str = ""
    model_name: str = "MiniMax-M2.7"
    base_url: str = "https://api.minimaxi.com/v1"
    use_responses_api: bool = Field(default=False, description="使用 OpenAI Responses 接口；false 使用 Chat Completions。")
    responses_streaming: bool = Field(default=False, description="Responses 使用流式传输；ainvoke 聚合完整响应后返回。")
    token_limit_field: Optional[Literal["max_tokens", "max_completion_tokens", "both"]] = Field(
        default=None, description="Chat Completions 输出上限字段；null 使用 provider preset。",
    )
    max_tokens: int = Field(default=MAX_COMPLETION_TOKENS, ge=1)
    temperature: float = 0.5
    reasoning_effort: Literal["low", "medium"] = "low"
    timeout: int = 30  # Fast 模型超时更短，低延迟场景不应等太久


class EmbeddingConfig(StrictConfig):
    """Embedding 模型配置（用于 RAG 向量化）

    provider = "qwen3"  → 本地 Qwen3-Embedding-0.6B ONNX 推理（默认，首次启动从 HF 下载 ~1.2GB）
    provider = "openai" → OpenAI 兼容 Embedding API（需 api_key + base_url）
    provider = "hash"   → 内置确定性哈希向量（零依赖，仅供 RAG 链路跑通，语义质量低）
    """
    enabled: bool = Field(default=True, description="启用向量知识检索与自动记忆抽取；关闭后仍可读写手动偏好。")
    provider: str = "qwen3"
    api_key: str = ""
    model_name: str = "n24q02m/Qwen3-Embedding-0.6B-ONNX"
    base_url: str = "https://api.openai.com/v1"
    dimensions: int = 1024


class DatabaseConfig(StrictConfig):
    """PostgreSQL + pgvector 数据库配置"""
    host: str = "localhost"
    port: int = 5432
    name: str = "travel_agent"
    user: str = "travel_agent"
    password: str = "travel_agent_pwd"
    pool_size: int = 10
    max_overflow: int = 20

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class MaintenanceConfig(StrictConfig):
    """备份 / 迁移 / 恢复这类维护动作的配置。

    只被 `journeypilot` CLI 与启动编排器读取，API 进程不用它；
    API 进程不改 Schema、不改物理数据库。
    """

    #: 备份根目录。相对路径按仓库根解析（不是当前工作目录 —— 从哪个目录敲命令
    #: 不该改变备份落在哪里）。
    backup_dir: str = "backups"
    #: 自动备份保留份数。手工备份永不自动删除。
    keep_automatic_backups: int = Field(default=5, ge=1)
    #: 跑 pg_dump / pg_restore 的容器名。空 = 按「谁发布了数据库端口」自动探测。
    #: 需要显式指定的场合：一台机器上跑着多个 PostgreSQL 容器共用端口映射。
    postgres_container: str = ""
    #: 迁移锁最长等待秒数。超时报错，不会在无锁状态下继续。
    migration_lock_timeout_seconds: float = Field(default=30.0, gt=0)


class RedisConfig(StrictConfig):
    """Redis 缓存配置"""
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class ServerConfig(StrictConfig):
    """FastAPI 服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8001
    reload: bool = True
    log_level: str = "info"
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:8080", "http://127.0.0.1:8080"]
    )
    allow_runtime_model_config: bool = False


class RAGConfig(StrictConfig):
    """RAG 检索配置"""
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 5
    score_threshold: float = 0.3
    # 分块策略: "text"（固定窗口）| "semantic"（语义边界）| "contextual"（语义+LLM上下文前缀）
    chunker_type: str = "contextual"
    # 语义分块相关参数
    semantic_split_threshold: float = 0.5   # 相似度低于此值视为语义边界

    # --- 分块调用的上界 ---
    # semantic / contextual 分块按文档大小逐句 embedding、逐段调用 LLM。一份
    # 10 MB 的上传可以产生上万条模型调用，并与在线 fast 请求共用同一条 httpx
    # 连接池（``langchain_openai`` 按 (base_url, timeout) 缓存一个 AsyncClient）。
    # 不设上界会让一次上传占满该连接池，阻塞其他用户的模型调用。
    #
    # 重试与退避由 transport 负责（openai SDK 指数退避 + max_retries=2）。下面
    # 两个数限制单次入库允许发起的调用条数，以及连续失败多少条后停止调用。同时
    # 在飞的条数归 ``ProviderChannelConfig.ingest_contextual_llm``：并发属于通道，
    # 入库与在线 fast 请求共用一个上游。
    #
    # ``model_chunking_max_chars``：超过该长度的正文不调用模型，直接按固定窗口
    # 分块。这个判断必须在发起任何调用之前完成，因此单位是字符而不是段数。
    # 60000 取出厂语料最大单篇（约 25000 字符 / 197 段）的两倍余量。
    model_chunking_max_chars: int = Field(default=60_000, ge=1)
    # 本篇累计失败达到该条数就停止调用 LLM，其余段落保留原文入库。上游限流时
    # 继续发送只会加重限流，而少几条上下文前缀只影响检索效果。
    contextual_failure_threshold: int = Field(default=8, ge=1)


class RerankConfig(StrictConfig):
    """Reranking 精排配置（Step 4: 二阶段精排）

    provider = "cross_encoder" → BGE-Reranker-v2-m3（需要 pip install sentence-transformers）
    provider = "llm"           → 复用现有 LLM 做相关性评分（开箱即用，推荐）
    """
    enabled: bool = True
    provider: str = "llm"            # "cross_encoder" | "llm"
    model_name: str = "BAAI/bge-reranker-v2-m3"
    initial_top_k: int = 20          # 初检候选数量（传给 Hybrid Search 的 top_k）
    final_top_k: int = 5             # 精排后最终返回数量


class DataSnapshotsConfig(StrictConfig):
    """仓库内上游数据的时效阈值。

    ``station_max_age_days``：12306 不发布版本号，只能按天数判断站表是否过期。
    可容忍的过期程度是运维决策，因此作为配置项而不是常量。
    """

    station_max_age_days: int = Field(default=90, gt=0)


class CheckpointRetentionConfig(StrictConfig):
    """LangGraph checkpoint 的保留策略。"""

    completed_days: int = 30
    cancelled_days: int = 30
    failed_interrupted_days: int = 90
    batch_size: int = 100
    # 为 True 时，Postgres checkpointer 初始化失败会阻止应用启动。
    require_on_startup: bool = False


class RunControlConfig(StrictConfig):
    """Run 控制开关与执行租约边界。"""

    plan_gate_enabled: bool = True
    #: 租约有效期。过期即视为「执行器不在了」，由恢复扫描接管。
    lease_seconds: int = Field(default=45, gt=0)
    #: 心跳间隔。必须显著小于 lease_seconds，否则一次慢查询就会让仍在执行的 run 被误判为失去执行器。
    lease_heartbeat_seconds: int = Field(default=10, gt=0)
    #: 连续心跳失败达到这个次数后，执行器停止发起新的外部调用。
    lease_heartbeat_failure_threshold: int = Field(default=3, gt=0)
    #: 失去执行器的 Run 的扫描间隔。启动时先扫一次，之后按这个周期复扫 —— 上一个进程死时租约可能还剩
    #: 几十秒，只在启动扫一次会把那些 run 永久留在 running。
    recovery_sweep_seconds: int = Field(default=60, gt=0)
    #: durable command 的轮询间隔。同进程的 API 会立刻唤醒执行器，所以这个值是通知丢失
    #: 或跨进程时的上界延迟，不是正常路径的取消延迟。
    command_poll_seconds: float = Field(default=2.0, gt=0)

    @model_validator(mode="after")
    def _heartbeat_fits_lease(self) -> "RunControlConfig":
        if self.lease_heartbeat_seconds * 2 > self.lease_seconds:
            raise ValueError(
                "lease_heartbeat_seconds 必须小于 lease_seconds 的一半，"
                "否则丢一次心跳就会失去租约"
            )
        return self


class RunDeadlineConfig(StrictConfig):
    """一次 Deep Run 的四段时间窗（秒），全仓唯一定义处。

    ``closeout`` 关研究，``composition`` 关行程编排，``delivery`` 是投影与持久化的外界。
    已经开始的 Run 用它自己封存的快照，改这里不影响在跑的 Run。
    """

    target_seconds: int = Field(default=375, gt=0)
    closeout_seconds: int = Field(default=450, gt=0)
    composition_seconds: int = Field(default=570, gt=0)
    delivery_seconds: int = Field(default=600, gt=0)

    @model_validator(mode="after")
    def _windows_are_ordered(self) -> "RunDeadlineConfig":
        ordered = (
            self.target_seconds,
            self.closeout_seconds,
            self.composition_seconds,
            self.delivery_seconds,
        )
        if list(ordered) != sorted(ordered):
            raise ValueError(
                "run_deadline 的四段必须递增："
                "target <= closeout <= composition <= delivery"
            )
        return self


class StreamingConfig(StrictConfig):
    """SSE 缓冲的内存预算。**全仓唯一定义处**，`runtime/events.py` 读它。"""

    #: 不可丢事件的队列长度。满了生产者等待，不丢。
    critical_queue_size: int = Field(default=128, ge=1)
    #: 相邻同源文本合并成一块的字符上限。太小等于没合并，太大会让首帧变迟。
    max_coalesced_chunk_chars: int = Field(default=2048, ge=1)
    #: 缓冲区里未发出的正文字符总量上限。
    max_pending_text_chars: int = Field(default=65536, ge=1024)
    #: 保活帧间隔。它不进业务队列。
    heartbeat_seconds: float = Field(default=15.0, gt=0)
    #: 生产者等消费者腾位置的上限。超过即判定消费者卡住，结束传输交给 durable 恢复。
    stalled_consumer_seconds: float = Field(default=30.0, gt=0)


class BlockingWorkConfig(StrictConfig):
    """同步工作被赶出 Event Loop 之后的并发与排队上界。**全仓唯一定义处**。

    线程池不是无限资源：`services/blocking_work.py` 按通道分配，一个通道排满时
    调用方等 ``queue_wait_seconds``，不是无限排队。
    """

    #: 同时渲染几份 PDF。1：ReportLab 吃满一个核，而导出是可以等的。
    pdf_export: int = Field(default=1, ge=1)
    #: 同时解析几份上传文档。子进程各自还有自己的 CPU / 地址空间上限。
    document_parse: int = Field(default=2, ge=1)
    #: 本地 ONNX embedding 的同时推理批数。
    local_embedding: int = Field(default=2, ge=1)
    #: 等一个通道腾出位置的上限。超时的含义是「现在太忙」，不是「这件事做不成」。
    queue_wait_seconds: float = Field(default=30.0, gt=0)


class IngestConfig(StrictConfig):
    """上传与文档解析的硬输入边界。

    只限制原始字节不够：DOCX 是 ZIP，一份 200 KB 的上传展开后可以是几个 GB。
    每一项都必须在**读进内存之前或读进内存的过程中**可判，不能依赖超时机制 ——
    线程里的解析器无法终止，超时只停止等待。
    """

    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_pdf_pages: int = Field(default=500, ge=1)
    max_docx_entries: int = Field(default=5000, ge=1)
    #: ZIP 全部条目解压后的字节总量上限。
    max_uncompressed_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    #: 解压后 / 压缩前的比值上限。zip bomb 的判据是比值，不是大小。
    max_compression_ratio: float = Field(default=100.0, gt=1)
    #: 提取出的正文字符上限。超过即截断并在回执里说明。
    max_extracted_chars: int = Field(default=2_000_000, ge=1024)
    #: 解析子进程的墙钟上限，超时杀进程树。
    parse_timeout_seconds: float = Field(default=60.0, gt=0)
    #: 子进程自己的 CPU 时间上限（秒）。0 = 不设（平台不支持 RLIMIT 时也自动跳过）。
    parse_cpu_seconds: int = Field(default=60, ge=0)
    #: 子进程地址空间上限（字节）。0 = 不设。
    parse_address_space_bytes: int = Field(default=2 * 1024**3, ge=0)


class RunBudgetConfig(StrictConfig):
    """一次 Run 允许花掉多少。

    Run 被授权时按这些值封存一份快照（``runtime/budget.py``），之后改配置
    不影响在跑的 Run —— 与 Deadline 同一条规矩。墙钟**不在这里**：它由
    ``RunDeadlineSnapshot`` 一处拥有，在这里再写一个 max_wall_seconds 就是让
    同一件事有两个 owner。
    """

    enforce_limits: bool = False
    max_llm_calls: Optional[int] = Field(default=None, ge=1)
    max_tool_calls: Optional[int] = Field(default=None, ge=1)
    max_input_tokens: Optional[int] = Field(default=None, ge=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)
    max_cost_usd: Optional[float] = Field(default=None, gt=0)
    #: 同一个工具在一次 Run 里允许重试多少轮。
    max_tool_retries_per_target: Optional[int] = Field(default=None, ge=0)


class ProviderChannelConfig(StrictConfig):
    """按上游通道分配的同时在飞条数。**连接池容量不是产品预算。**

    底层 httpx 连接池上限 1000 不代表允许一次入库发 1000 条模型调用。限速器
    （`utils/rate_gate.py`）管两次请求之间的间隔，这里管同时在飞的条数，两件事。
    """

    #: primary 档（调研与编排）。
    primary_research_llm: int = Field(default=6, ge=1)
    #: fast 档的在线请求（快问快答、标题、约束归一）。
    online_fast_llm: int = Field(default=8, ge=1)
    #: 资料入库的逐段上下文前缀。与 online_fast_llm 走同一个上游，所以要独立配额，
    #: 否则一次上传把所有在线请求排到队尾。
    ingest_contextual_llm: int = Field(default=4, ge=1)
    #: 远程 embedding 服务的同时请求数（本地 ONNX 推理走 BlockingWorkConfig）。
    embedding: int = Field(default=4, ge=1)
    #: 没有 Run deadline 的调用（快问快答、授权之前）排队等位置的上限。有 deadline 的
    #: 那一档由窗口自己定界，不读这个值。
    max_queue_wait_seconds: float = Field(default=180.0, gt=0)


class BackgroundJobsConfig(StrictConfig):
    """durable 后台任务 worker 的边界。"""

    #: 队列空闲时的轮询间隔。入队方会直接唤醒 worker，所以这是通知丢失时的上界延迟。
    poll_seconds: float = Field(default=5.0, gt=0)
    #: 任务租约。执行中每 1/3 租约续一次；进程崩溃后租约过期，任务重新可领取。
    lease_seconds: int = Field(default=60, gt=0)
    #: 一次领取几条。单机产品不需要并行消费，默认一条一条来。
    batch_size: int = Field(default=1, ge=1)
    #: 已完成任务的保留天数。dead 任务不参与清理，留到用户确认。
    completed_retention_days: int = Field(default=30, ge=1)


class GeocodingConfig(StrictConfig):
    """OSM 地点 provider（Nominatim / Overpass）访问配置。"""

    # Nominatim 实例。默认公共实例（零 Key）；自托管实例可经 NOMINATIM_BASE_URL 覆盖以摆脱 1 req/s 限。
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    # Nominatim 合规要求明确标识应用的 User-Agent（禁用 http 库默认 UA）。
    user_agent: str = "JourneyPilot/1.0 (travel itinerary geocoder; https://github.com/journeypilot)"
    # /lookup（批量 osm_id，双语两轮）与 Overpass 的基准超时。这两个端点本来就慢：
    # /lookup 一次要 5 个对象的 addressdetails+namedetails，Overpass 另有
    # ``max(30.0, timeout_seconds)`` 作为下限。两者都只在身份 fallback 里跑，那条路径
    # 自带 20s 时间片（``_IDENTITY_FALLBACK_BUDGET_SECONDS``），不在首跳同步路径上。
    timeout_seconds: float = Field(default=10.0, gt=0)
    # /search 单独的超时：它是「用户敲下目的地」这一跳的同步阻塞点。
    # 上界由重试序列决定：限速器 1.1s 加 2 次尝试（见
    # ``nominatim_place_search._PROVIDER_MAX_ATTEMPTS``）要控制在 8s 内，
    # 1.1 + 2 × 3.4 = 7.9s，3.4 是满足该上界的最大单次超时。调大只会让调用方
    # 更晚拿到超时结果；偶发超时由第二次尝试覆盖，成功后写入缓存。
    search_timeout_seconds: float = Field(default=3.4, gt=0)
    # 公共 Nominatim ≤1 req/s；1.1s 留安全裕量（全局限速器串行保证）。
    min_interval_seconds: float = 1.1
    # 原始 /search 响应的复用窗口。OSM 的城市/车站/景点 relation 不会移动，与既有的
    # ``provider_snapshot_cache.place_identity_ttl_seconds`` 同为 7 天口径。
    search_cache_ttl_seconds: int = Field(default=7 * 24 * 60 * 60, gt=0)
    search_cache_key_prefix: str = Field(
        default="journeypilot:nominatim-search:v1",
        min_length=1,
    )
    search_cache_redis_timeout_seconds: float = Field(default=0.25, gt=0)


class RoutingConfig(StrictConfig):
    """步行与公共交通路线 provider 配置。

    两个上游按地理范围分工：amap 负责中国坐标系内的请求，Transitous/MOTIS
    负责其他地区。MOTIS 不含中国大陆的公共交通数据，amap 也不覆盖境外。
    """

    transitous_base_url: str = "https://api.transitous.org"
    amap_base_url: str = "https://restapi.amap.com"
    user_agent: str = "JourneyPilot/2.0 (https://github.com/journeypilot)"
    timeout_seconds: float = 20.0
    min_interval_seconds: float = 1.0


class ProviderSnapshotCacheConfig(StrictConfig):
    """可复用 Provider 快照的 Redis 缓存策略。"""

    enabled: bool = True
    redis_key_prefix: str = Field(
        default="journeypilot:provider-snapshot:v1",
        min_length=1,
    )
    redis_timeout_seconds: float = Field(default=0.25, gt=0)
    # 变动性低的实体身份可以缓存更久；路线结果保持较短有效期。
    place_identity_ttl_seconds: int = Field(default=7 * 24 * 60 * 60, gt=0)
    route_ttl_seconds: int = Field(default=300, gt=0)


class AgentToolPolicy(StrictConfig):
    """单个 worker agent 的工具访问策略。字段全带默认值：键可以只写一部分。"""

    servers: Set[str] = Field(default_factory=set)
    deny_tools: Set[str] = Field(default_factory=set)
    extra_tools: Set[str] = Field(default_factory=set)


class ToolExposureConfig(StrictConfig):
    """Tool Search 按需工具曝光策略。

    默认 ``deferred``：worker agent 不再全量注入工具 schema，只带压缩目录（名称+一行
    描述）进 system prompt，由 ``search_tools`` 元工具按需激活完整 schema。

    - ``mode``: ``deferred`` 走按需曝光；``full`` 切换为全量注入，便于排障。
    - ``worker_only``: 仅对 worker agent（destination/transport/accommodation/itinerary）
      启用；scope/orchestrator 等治理节点不动。
    - ``min_tools_threshold``: 该 agent 可用工具数 ``>=`` 阈值才 defer；阈值以下工具少，
      多一次 search 调用不划算，自动回落 full。
    """

    mode: str = "deferred"          # "deferred" | "full"
    worker_only: bool = True
    min_tools_threshold: int = 8


class ModelPricingItem(StrictConfig):
    """单条模型定价（USD / 1M tokens，读折扣型缓存计费）。

    台账层按 (model_request, provider) 前缀匹配到一条价格，写入时快照计算
    cost_usd。价格随时变动——`effective_from` 记录抓取日期，`source_url` 记录来源，用户
    可在 config.yaml 覆盖或追加档位。
    """

    pattern: str                                   # 模型名前缀（大小写不敏感），如 "MiniMax-M2.7"
    provider: str = ""                             # 可选 provider 约束（infer_provider 输出），空=不限
    input_per_1m: float = Field(default=0.0, ge=0)  # 未命中缓存的输入价
    cached_input_per_1m: Optional[float] = Field(default=None, ge=0)
    cache_write_per_1m: Optional[float] = Field(default=None, ge=0)  # 写入桶总价
    output_per_1m: float = Field(default=0.0, ge=0)  # 包含推理输出
    currency: str = "USD"
    effective_from: str = ""                        # 价格抓取/生效日期
    source_url: str = ""


class MCPServerItem(StrictConfig):
    """单个 MCP 服务器配置"""
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    sse_url: Optional[str] = None
    disabled: bool = False
    description: Optional[str] = None
    required_env: List[str] = Field(default_factory=list)
    # 该 server 两次调用之间的最小间隔。默认 0 表示不限速：多数 server 的配额
    # 按天计算，间隔限制针对每秒并发超限这一类拒绝（高德 CUQPS）。数值应从
    # 供应商控制台读取后写入 config.yaml，不要写死在代码里。MCPManager 的
    # per-server 锁已保证同一 server 的调用串行，这里只补调用间隔。
    min_interval_seconds: float = Field(default=0.0, ge=0)


# ---------------------------------------------------------------------------
# 根配置对象
# ---------------------------------------------------------------------------

class UsageConfig(StrictConfig):
    spool_path: str = "data/usage/outbox.sqlite3"
    flush_seconds: float = Field(default=2, ge=0.1)


class Settings(StrictConfig):
    """全局设置。优先级：环境变量 > config.yaml > 这里的默认值。

    默认值的原则：**安全、稳定、不产生意外费用**。api_key 默认为空，provider 必须由
    用户选（`backend/travel_agent/resources/providers/*.yaml` 帮他填），监听 localhost，运行时改模型默认关，
    重型增强默认关，预算与 Deadline 都是明确的有限值。
    """

    env: str = "development"
    debug: bool = False

    primary_model: PrimaryModelConfig = Field(default_factory=PrimaryModelConfig)
    fast_model: FastModelConfig = Field(default_factory=FastModelConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    checkpoint_retention: CheckpointRetentionConfig = Field(
        default_factory=CheckpointRetentionConfig
    )
    data_snapshots: DataSnapshotsConfig = Field(default_factory=DataSnapshotsConfig)
    run_control: RunControlConfig = Field(default_factory=RunControlConfig)
    run_deadline: RunDeadlineConfig = Field(default_factory=RunDeadlineConfig)
    run_budget: RunBudgetConfig = Field(default_factory=RunBudgetConfig)
    usage: UsageConfig = Field(default_factory=UsageConfig)
    background_jobs: BackgroundJobsConfig = Field(default_factory=BackgroundJobsConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    blocking_work: BlockingWorkConfig = Field(default_factory=BlockingWorkConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    provider_channels: ProviderChannelConfig = Field(default_factory=ProviderChannelConfig)
    geocoding: GeocodingConfig = Field(default_factory=GeocodingConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    provider_snapshot_cache: ProviderSnapshotCacheConfig = Field(
        default_factory=ProviderSnapshotCacheConfig
    )
    tool_exposure: ToolExposureConfig = Field(default_factory=ToolExposureConfig)
    model_pricing: List[ModelPricingItem] = Field(default_factory=lambda: _pricing())
    mcp_servers: Dict[str, MCPServerItem] = Field(default_factory=lambda: _mcp_servers())
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _pricing() -> List[ModelPricingItem]:
    # 延迟到这里 import：两份默认数据都要 import 本模块的类型，模块级引用会成环。
    from .pricing import default_model_pricing

    return default_model_pricing()


def _mcp_servers() -> Dict[str, MCPServerItem]:
    from .mcp_defaults import default_mcp_servers

    return default_mcp_servers()
