"""Framework-independent application lifespan."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from travel_agent.bootstrap.assembly import build_components
from travel_agent.bootstrap.registry import set_components
from travel_agent.bootstrap.shutdown import shutdown_components
from travel_agent.config import get_settings
from travel_agent.config.capabilities import capability_gaps
from travel_agent.integrations.pdf_readiness import probe_pdf_font
from travel_agent.knowledge.bootstrap import bootstrap_factory_corpus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def application_lifespan() -> AsyncGenerator[None, None]:
    """应用生命周期管理：启动时初始化，关闭时清理"""
    settings = get_settings()
    gaps = capability_gaps(settings)
    if gaps:
        for gap in gaps:
            logger.error("增强依赖缺失：%s", gap.message())
        raise RuntimeError(
            "配置选择的增强能力缺少依赖：" + "；".join(gap.message() for gap in gaps)
        )

    try:
        logger.info("JourneyPilot API 启动中...")
        components = await build_components(settings)
        set_components(components)
        degraded: list[str] = []
        report = components.schema_report
        if report is None or not report.compatible:
            problems = "；".join(report.problems) if report else "合同校验未执行"
            action = (report.next_action if report else "") or "journeypilot doctor"
            degraded.append(f"数据库合同校验未通过（{problems}）→ {action}")
        else:
            try:
                await components.preset_store.ensure_presets()
                await components.product_configuration_store.ensure_seed()
                logger.info("预设与产品配置初始化完成")
            except Exception as e:
                logger.warning(f"预设初始化失败: {e}")
            corpus_problems = await bootstrap_factory_corpus()
            if corpus_problems:
                logger.error(
                    "出厂语料未就位，知识库检索会静默返回 0 条"
                    "（详见 GET /api/health/ready 的 knowledge_corpus）| %s",
                    "；".join(corpus_problems),
                )
            recovery = components.run_recovery_service
            if recovery is not None:
                try:
                    recovery_report = await recovery.sweep()
                    recovery_report.log_summary()
                except Exception as e:
                    logger.error("启动恢复普查失败: %s", e, exc_info=True)
                    degraded.append(f"启动恢复普查失败（{e}）")
                recovery.start()
            worker = components.background_job_worker
            if worker is not None:
                try:
                    await worker.cleanup()
                except Exception as e:
                    logger.warning("后台任务清理失败: %s", e)
                worker.start()
        pdf_problem = await probe_pdf_font()
        if pdf_problem:
            logger.error(
                "PDF 导出不可用，规划与问答不受影响"
                "（详见 GET /api/health/ready 的 pdf_export）| %s",
                pdf_problem,
            )
        if (
            not components.checkpointer_available
            and settings.run_control.plan_gate_enabled
        ):
            degraded.append(
                f"LangGraph checkpointer 不可用（{components.checkpointer_init_error}）"
            )
        if degraded:
            logger.error(
                "系统降级启动，请勿放行流量（详见 GET /api/health/ready）| %s | "
                "工具: %d 个 | 模型: %s",
                "；".join(degraded),
                components.tool_registry.count,
                settings.primary_model.model_name,
            )
        else:
            logger.info(
                f"系统就绪 | 工具: {components.tool_registry.count} 个 | "
                f"模型: {settings.primary_model.model_name}"
            )
        yield
    finally:
        logger.info("JourneyPilot API 关闭中，清理资源...")
        await shutdown_components()
