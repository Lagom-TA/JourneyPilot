"""不含密钥的配置投影。"""

from typing import Any, Dict


def public_config_payload(settings: Any) -> Dict[str, Any]:
    """供 /api/config 读取的配置投影，不包含 API Key 明文。"""

    primary = getattr(settings, "primary_model", None)
    fast = getattr(settings, "fast_model", None)
    server = getattr(settings, "server", None)
    return {
        "primary_model": {
            "model_name": getattr(primary, "model_name", None),
            "base_url": getattr(primary, "base_url", None),
            "api_key_set": bool(getattr(primary, "api_key", None)),
        },
        "fast_model": {
            "model_name": getattr(fast, "model_name", None),
            "base_url": getattr(fast, "base_url", None),
            "api_key_set": bool(getattr(fast, "api_key", None)),
        },
        "server": {
            "allow_runtime_model_config": bool(
                getattr(server, "allow_runtime_model_config", False)
            ),
        },
        "rag": {
            "chunk_size": settings.rag.chunk_size,
            "top_k": settings.rag.top_k,
            "embedding_model": settings.embedding.model_name,
        },
        "env": settings.env,
    }
