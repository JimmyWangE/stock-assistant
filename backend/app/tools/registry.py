"""模型可调用的工具清单，以及按名称执行工具的入口。"""

import inspect
import json
import logging

from app.tools import fundamentals, market, news
from app.tools.base import ToolError, ToolResult

logger = logging.getLogger(__name__)

_SYMBOL = {"type": "string", "description": "股票的 6 位代码或简称，如 600519 或 贵州茅台"}

# 工具定义每次提问都会发给模型，占用上下文，描述要短
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_quote",
            "description": "查询一只 A 股股票的最新行情：最新价、涨跌幅、今开、最高、最低、昨收、成交量、成交额",
            "parameters": {
                "type": "object",
                "properties": {"symbol": _SYMBOL},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_kline",
            "description": "获取一只 A 股股票的 K 线并向用户展示 K 线图，同时返回区间涨跌幅、高低点、均线等摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": _SYMBOL,
                    "period": {
                        "type": "string",
                        "enum": [*market.MINUTE_PERIODS, *market.DAY_PERIODS],
                        "description": "K 线周期，默认 daily",
                    },
                    "count": {"type": "integer", "description": "K 线根数，20 到 250，默认 120"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financials",
            "description": "获取一只 A 股股票最近几个报告期的主要财务指标（营收、净利润、同比、毛利率、ROE、负债率等）并向用户展示表格",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": _SYMBOL,
                    "periods": {"type": "integer", "description": "报告期个数，2 到 8，默认 6"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_news",
            "description": "获取一只 A 股股票最近的新闻，含标题、时间、摘要和原文链接",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": _SYMBOL,
                    "limit": {"type": "integer", "description": "条数，1 到 10，默认 6"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_news",
            "description": "获取最新的财经与政策资讯（不限个股），可按关键词筛选，含标题、时间、摘要和原文链接",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "筛选关键词，如 央行、新能源；留空看最新"},
                    "limit": {"type": "integer", "description": "条数，1 到 12，默认 8"},
                },
            },
        },
    },
]

_HANDLERS = {
    "get_stock_quote": market.get_stock_quote,
    "get_kline": market.get_kline,
    "get_financials": fundamentals.get_financials,
    "get_stock_news": news.get_stock_news,
    "get_market_news": news.get_market_news,
}

# 工具执行期间显示给用户的状态
STATUS = {
    "get_stock_quote": "正在查询行情…",
    "get_kline": "正在获取 K 线…",
    "get_financials": "正在获取财务数据…",
    "get_stock_news": "正在查找相关新闻…",
    "get_market_news": "正在获取最新资讯…",
}


async def run_tool(name: str, arguments: str) -> ToolResult:
    """执行一次工具调用。任何失败都转成"数据未获取"的文字结果，让模型继续作答（验收 B9）。"""
    handler = _HANDLERS.get(name)
    if handler is None:
        return ToolResult(text=f"数据未获取：没有名为 {name} 的工具。")
    try:
        params = json.loads(arguments or "{}")
        if not isinstance(params, dict):
            raise ValueError("参数不是对象")
        # 先单独检查参数名对不对，这样工具内部的故障不会被误报成"参数不正确"
        inspect.signature(handler).bind(**params)
    except (ValueError, TypeError) as exc:
        return ToolResult(text=f"数据未获取：工具参数不正确（{exc}）。")
    try:
        return await handler(**params)
    except ToolError as exc:
        return ToolResult(text=f"数据未获取：{exc}")
    except Exception:  # noqa: BLE001 数据源的任何故障都不能中断回答
        logger.exception("工具 %s 执行失败", name)
        return ToolResult(text="数据未获取：数据源暂时不可用。请如实告知用户这部分数据没有取到。")
