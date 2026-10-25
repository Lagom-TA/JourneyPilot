"""Runtime model mutation and persistence without HTTP dependencies."""

import logging

from travel_agent.config.loader import get_settings, persist_model_config
from travel_agent.llm.router import ModelTier, get_model_router

logger = logging.getLogger(__name__)


class RuntimeModelConfigDisabled(PermissionError):
    pass


class RuntimeModelConfigPersistenceError(RuntimeError):
    pass


class RuntimeModelConfigInvalid(ValueError):
    pass


def update_runtime_model(
    *,
    tier: str,
    api_key: str,
    model_name: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, str]:
    try:
        selected_tier = {"primary": ModelTier.PRIMARY, "fast": ModelTier.FAST}.get(
            tier, ModelTier.PRIMARY
        )
        settings = get_settings()
        if not settings.server.allow_runtime_model_config:
            raise RuntimeModelConfigDisabled(
                "运行时模型配置接口未启用；在 config.yaml 里设 "
                "server.allow_runtime_model_config: true，或设环境变量 "
                "JOURNEYPILOT_SERVER__ALLOW_RUNTIME_MODEL_CONFIG=1"
            )
        model = (
            settings.primary_model
            if selected_tier == ModelTier.PRIMARY
            else settings.fast_model
        )
        api_key = api_key.strip() if api_key else model.api_key
        model.api_key = api_key
        model.model_name = model_name
        model.base_url = base_url
        model.max_tokens = max_tokens
        model.temperature = temperature
        router = get_model_router()
        router.update_model(
            tier=selected_tier,
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            persist_model_config(
                tier,
                {
                    "api_key": api_key,
                    "model_name": model_name,
                    "base_url": base_url,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
        except FileNotFoundError as exc:
            raise RuntimeModelConfigPersistenceError(str(exc)) from exc
        logger.info(f"模型配置已更新: {model_name} ({tier})")
        return {"status": "success", "message": f"{tier} 模型已更新为 {model_name}"}
    except (RuntimeModelConfigDisabled, RuntimeModelConfigPersistenceError):
        raise
    except Exception as exc:
        raise RuntimeModelConfigInvalid(str(exc)) from exc
