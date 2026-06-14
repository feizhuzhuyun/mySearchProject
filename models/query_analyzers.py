"""
查询解析器实现 — 本地规则引擎（无依赖，始终可用）。
"""
from models import register
from models.base import BaseQueryAnalyzer, SearchIntent


@register("query_analyzers")
class LocalQueryAnalyzer(BaseQueryAnalyzer):
    """
    本地规则引擎 — 不依赖任何模型。
    纯数字 → 69码搜索，含文字 → 关键字搜索。
    后续可扩展：含否定词 → 加入 exclude_terms。
    """

    name = "本地规则引擎"
    priority = 1

    def analyze(self, query: str) -> SearchIntent:
        query = query.strip()
        if not query:
            return SearchIntent()

        if query.isdigit():
            return SearchIntent(
                mode="code",
                include_terms=[query],
            )

        # 简单关键字搜索（后续可扩展复杂语义解析）
        return SearchIntent(
            mode="keyword",
            include_terms=[query],
        )
