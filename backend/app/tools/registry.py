"""模型可调用的工具清单，以及按名称执行工具的入口。"""

import json
import logging

from app.tools import market
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
]

_HANDLERS = {
    "get_stock_quote": market.get_stock_quote,
    "get_kline": market.get_kline,
}

# 工具执行期间显示给用户的状态
STATUS = {
    "get_stock_quote": "正在查询行情…",
    "get_kline": "正在获取 K 线…",
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
        return await handler(**params)
    except ToolError as exc:
        return ToolResult(text=f"数据未获取：{exc}")
    except (ValueError, TypeError) as exc:
        return ToolResult(text=f"数据未获取：工具参数不正确（{exc}）。")
    except Exception:  # noqa: BLE001 数据源的任何故障都不能中断回答
        logger.exception("工具 %s 执行失败", name)
        return ToolResult(text="数据未获取：数据源暂时不可用。请如实告知用户这部分数据没有取到。")
