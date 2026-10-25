from __future__ import annotations
import logging
from typing import Dict, Optional
from .errors import PresetNotFound, PresetUnavailable

logger = logging.getLogger(__name__)


async def load_preset_context(
    preset_id: Optional[str], user_id: str
) -> tuple[str, Dict[str, str]]:
    """加载预设，返回 (进 prompt 的那段文本, 交给 Constraint Pack 的那几项)。

    交两份出去而不是一份，是因为一个 preset 里有两类东西，归两层负责：指令与重点关注
    是给模型看的散文，节奏与预算档位是可执行约束、要进 pack 参与仲裁（见
    ``PresetInjector.PRESET_PACK_CONSTRAINT_CATEGORIES``）。在一份字符串里同时表达
    这两件事，就是那三个「风格」互不相认的起点。

    - 未传 preset_id：返回空串与空字典（不注入风格）。
    - 显式 preset 不存在或无权访问：HTTP 404（资源语义，非 500）。
    - 存储层异常：HTTP 500，明确业务文案。
    """
    if not preset_id:
        return "", {}

    from travel_agent.conversation.preset_context import PresetInjector
    from travel_agent.storage.preset_store import PresetStore

    try:
        preset_store = PresetStore()
        preset = await preset_store.get_preset(preset_id, user_id=user_id or None)
    except Exception as e:
        logger.warning(f"加载预设失败: {e}", exc_info=True)
        raise PresetUnavailable() from e

    if not preset:
        raise PresetNotFound()

    try:
        context = PresetInjector.build_context(preset)
        pack_constraints = PresetInjector.pack_constraints(preset)
        await preset_store.increment_usage(preset_id)
    except Exception as e:
        logger.warning(f"预设上下文构建失败: {e}", exc_info=True)
        raise PresetUnavailable() from e

    logger.info(f"预设已加载: {preset.name} (id={preset_id})")
    return context, pack_constraints
