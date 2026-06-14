"""
模型抽象接口 — 所有模型插件实现这些基类。
删除任意实现文件不影响 app 启动，核心功能始终可用。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 搜索意图（QueryAnalyzer 输出）
# ---------------------------------------------------------------------------
@dataclass
class SearchIntent:
    """将用户自然语言查询转为结构化搜索参数。"""
    mode: str = "keyword"           # "code" | "keyword" | "image"
    include_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    is_complex: bool = False        # True → 需要语义解析


# ---------------------------------------------------------------------------
# 抽象接口
# ---------------------------------------------------------------------------
class BaseFeatureExtractor(ABC):
    """图像特征提取器 — CLIP / DINOv2 等实现此接口。"""

    name: str = ""            # 显示名 "CLIP ViT-B/32"
    dim: int = 0              # 输出向量维度
    priority: int = 10        # UI 排序（小在前）

    @abstractmethod
    def extract_batch(self, paths: list[str]) -> "np.ndarray":
        """批量提取特征向量。"""
        ...

    @abstractmethod
    def extract_single(self, path: str) -> "np.ndarray":
        """单张提取（用于拖图搜索）。"""
        ...


class BaseQueryAnalyzer(ABC):
    """查询解析器 — 自然语言 → SearchIntent。"""

    name: str = ""            # "本地规则引擎" | "云端 LLM"

    @abstractmethod
    def analyze(self, query: str) -> SearchIntent:
        """解析用户输入，返回结构化搜索意图。"""
        ...


class BaseOCREngine(ABC):
    """OCR 引擎 — 图像 → 文字。"""

    name: str = ""

    @abstractmethod
    def extract_text(self, image_path: str) -> str:
        ...
