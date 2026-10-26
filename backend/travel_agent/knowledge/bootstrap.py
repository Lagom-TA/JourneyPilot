"""可选的本地出厂语料启动引导。"""

import logging

from travel_agent.config.loader import get_settings

logger = logging.getLogger(__name__)


async def bootstrap_factory_corpus() -> list[str]:
    """只填充空集合，不覆盖已有数据；失败返回问题清单，不阻断服务。"""

    if not get_settings().embedding.enabled:
        return []

    from travel_agent.knowledge.factory_seed import ensure_factory_corpus

    try:
        report = await ensure_factory_corpus()
    except Exception as exc:
        logger.exception("出厂语料自举失败")
        return [f"出厂语料自举失败（{exc}）"]

    if report.loaded:
        logger.info(
            "出厂语料自举：灌入 %s%s",
            "、".join(
                f"{name} {count} 段" for name, count in sorted(report.loaded.items())
            ),
            "（种子 embedder 与当前配置不符，向量已重算）" if report.reembedded else "",
        )
    elif not report.problems:
        logger.info("出厂语料就位：%s", report.present)
    return list(report.problems)
