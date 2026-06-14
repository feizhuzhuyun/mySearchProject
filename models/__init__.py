"""
模型注册表 + 懒加载 — 删除任意实现文件不影响 app 启动。
"""
import importlib
import logging

logger = logging.getLogger(__name__)

_registry: dict[str, dict[str, type]] = {
    "feature_extractors": {},
    "query_analyzers": {},
    "ocr_engines": {},
}


def register(category: str):
    """装饰器：将模型类注册到指定类别。失败静默跳过。"""
    if category not in _registry:
        raise ValueError(f"Unknown category: {category}")

    def wrapper(cls):
        # 类名作为 key（可被同名覆盖，即"后注册的覆盖先注册的"）
        _registry[category][cls.__name__] = cls
        logger.debug("Registered %s → %s", category, cls.__name__)
        return cls

    return wrapper


def get_available(category: str) -> list[dict]:
    """返回可供 UI 下拉框使用的模型列表，按 priority 排序。"""
    items = []
    for cls_name, cls in _registry.get(category, {}).items():
        items.append({
            "id": cls_name,
            "label": getattr(cls, "name", cls_name),
            "priority": getattr(cls, "priority", 10),
        })
    items.sort(key=lambda x: x["priority"])
    return items


def get_instance(category: str, model_id: str, **kwargs):
    """懒加载模型实例。加载失败返回 None，不抛异常。"""
    cls = _registry.get(category, {}).get(model_id)
    if cls is None:
        logger.warning("Model not found: %s/%s", category, model_id)
        return None
    try:
        return cls(**kwargs)
    except Exception as exc:
        logger.warning("Failed to init %s/%s: %s", category, model_id, exc)
        return None


def is_registered(category: str, model_id: str) -> bool:
    """检查模型是否已注册且可用。"""
    return model_id in _registry.get(category, {})


# ── 自动发现模型插件 ──────────────────────────────────────────────
# 尝试导入各实现文件。导入成功 → @register 将类写入 _registry。
# 导入失败 → _registry 该类别为空 → UI 显示"未安装"。

for _module in ("feature_extractors", "query_analyzers", "ocr_engines"):
    try:
        importlib.import_module(f".{_module}", package="models")
    except ImportError:
        logger.debug("Model module not available: %s", _module)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", _module, exc)
