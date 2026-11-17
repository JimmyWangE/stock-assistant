"""行情与 K 线：数据经 AkShare 取自新浪财经。

AkShare 是同步库，调用都放到线程里；结果做短时间缓存，避免多人同时问同一只股票时重复抓取。
"""

import asyncio
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

from app.tools.base import ToolError, ToolResult

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")

MINUTE_PERIODS = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
DAY_PERIODS = {"daily": "日K", "weekly": "周K", "monthly": "月K"}
# 取这么多根 K 线大约要往前推多少个自然日
_DAYS_PER_BAR = {"daily": 1.6, "weekly": 7.5, "monthly": 32}

_cache: dict[tuple, tuple[float, Any]] = {}
_locks: dict[tuple, asyncio.Lock] = {}


async def _cached(key: tuple, ttl: float, fn: Callable[[], Any]) -> Any:
    """ttl 秒内同一个 key 只真正抓取一次；并发请求排队等第一个的结果。"""
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        value = await asyncio.to_thread(fn)
        _cache[key] = (time.monotonic(), value)
        return value


def _normalize(text: str) -> str:
    # 股票简称里有全角字母和空格（如"万  科Ａ"），统一后再比较
    return unicodedata.normalize("NFKC", text).replace(" ", "").upper()


def _load_stock_table() -> dict[str, dict[str, str]]:
    df = ak.stock_info_a_code_name()
    by_code = {str(code): str(name).replace(" ", "") for code, name in zip(df["code"], df["name"])}
    by_name = {_normalize(name): code for code, name in by_code.items()}
    return {"by_code": by_code, "by_name": by_name}


async def _stock_table() -> dict[str, dict[str, str]]:
    return await _cached(("stock_table",), 12 * 3600, _load_stock_table)


async def warm_up() -> None:
    """启动时预先加载股票名称表。加载要十秒左右，不能让第一个提问的人来等。"""
    try:
        await _stock_table()
    except Exception:  # noqa: BLE001 预热失败不影响启动，用到时会再试
        logger.warning("股票名称表预加载失败，将在首次查询时重试")


def _exchange_prefix(code: str) -> str:
    if code.startswith(("6", "9")) and not code.startswith("92"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    return "bj"


async def resolve_stock(symbol: str) -> tuple[str, str]:
    """把用户或模型给的"代码或简称"解析成（6 位代码，简称）。"""
    text = _normalize(symbol)
    digits = re.search(r"\d{6}", text)
    try:
        table = await _stock_table()
    except Exception:  # noqa: BLE001 名称表取不到时，只要给的是代码仍可继续
        table = {"by_code": {}, "by_name": {}}

    if digits:
        code = digits.group()
        if table["by_code"] and code not in table["by_code"]:
            raise ToolError(f"没有代码为 {code} 的 A 股股票。")
        return code, table["by_code"].get(code, code)
    if not table["by_name"]:
        raise ToolError("股票名称表暂时取不到，请改用 6 位代码查询。")
    if text in table["by_name"]:
        code = table["by_name"][text]
        return code, table["by_code"][code]
    matches = [code for name, code in table["by_name"].items() if text and text in name]
    if len(matches) == 1:
        return matches[0], table["by_code"][matches[0]]
    if len(matches) > 1:
        names = "、".join(table["by_code"][c] for c in matches[:8])
        raise ToolError(f"「{symbol}」对应多只股票：{names}。请用 6 位代码或完整简称重新查询。")
    raise ToolError(f"未找到股票「{symbol}」，请确认名称或提供 6 位代码。")


def _source_url(code: str) -> str:
    return f"https://finance.sina.com.cn/realstock/company/{_exchange_prefix(code)}{code}/nc.shtml"


def _minute_bars(code: str, period: str, adjust: str = "") -> pd.DataFrame:
    df = ak.stock_zh_a_hist_min_sina(
        symbol=_exchange_prefix(code) + code, period=period, adjust=adjust
    )
    if df is None or df.empty:
        raise ToolError("数据源没有返回分钟行情")
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["day"] = pd.to_datetime(df["day"])
    return df.dropna(subset=["close"]).reset_index(drop=True)


def _day_bars(code: str, period: str, start: str, adjust: str) -> pd.DataFrame:
    df = ak.stock_zh_a_hist_sina(
        symbol=_exchange_prefix(code) + code,
        period=period,
        start_date=start,
        end_date="21000101",
        adjust=adjust,
    )
    if df is None or df.empty:
        raise ToolError("数据源没有返回 K 线数据")
    df["date"] = pd.to_datetime(df["date"])
    return df.reset_index(drop=True)


def _num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


async def get_stock_quote(symbol: str) -> ToolResult:
    code, name = await resolve_stock(symbol)
    minutes = await _cached(("min", code, "1", ""), 3, lambda: _minute_bars(code, "1"))
    last = minutes.iloc[-1]
    as_of: datetime = last["day"].to_pydatetime()
    today = minutes[minutes["day"].dt.date == as_of.date()]

    # 昨收取自日线里早于"最新交易日"的最后一根；日线不常变，缓存久一些
    start = (as_of - timedelta(days=20)).strftime("%Y%m%d")
    days = await _cached(
        ("day", code, "daily", "", start[:6]), 600, lambda: _day_bars(code, "daily", start, "")
    )
    earlier = days[days["date"].dt.date < as_of.date()]
    lines = [
        f"{name}（{code}）行情，数据时间 {as_of:%Y-%m-%d %H:%M}（北京时间，分钟级行情，非逐笔）",
        f"最新价 {_num(last['close'])} 元",
    ]
    if not earlier.empty:
        prev_close = float(earlier.iloc[-1]["close"])
        change = float(last["close"]) - prev_close
        lines.append(
            f"涨跌额 {change:+.2f} 元，涨跌幅 {change / prev_close * 100:+.2f}%，昨收 {_num(prev_close)} 元"
        )
    lines.append(
        f"今开 {_num(today.iloc[0]['open'])}，最高 {_num(today['high'].max())}，"
        f"最低 {_num(today['low'].min())}，"
        f"成交量 {today['volume'].sum() / 100:.0f} 手，成交额 {today['amount'].sum() / 1e8:.2f} 亿元"
    )
    lines.append(f"来源：新浪财经 {_source_url(code)}")
    return ToolResult(text="\n".join(lines))


async def get_kline(symbol: str, period: str = "daily", count: int = 120) -> ToolResult:
    if period not in MINUTE_PERIODS and period not in DAY_PERIODS:
        raise ToolError(f"不支持的周期「{period}」")
    count = max(20, min(int(count), 250))
    code, name = await resolve_stock(symbol)

    if period in MINUTE_PERIODS:
        minutes = MINUTE_PERIODS[period]
        # 分钟线用不复权数据：复权后的分钟线不含当天，而看分钟线通常就是为了看当天
        df = await _cached(("min", code, minutes, ""), 20, lambda: _minute_bars(code, minutes))
        df = df.tail(count)
        times = [t.strftime("%Y-%m-%d %H:%M") for t in df["day"]]
        label = f"{minutes}分钟K（不复权）"
    else:
        start_dt = datetime.now(SHANGHAI) - timedelta(days=int(count * _DAYS_PER_BAR[period]) + 15)
        start = start_dt.strftime("%Y%m%d")
        df = await _cached(
            ("day", code, period, "qfq", start), 300, lambda: _day_bars(code, period, start, "qfq")
        )
        df = df.tail(count)
        times = [t.strftime("%Y-%m-%d") for t in df["date"]]
        label = DAY_PERIODS[period] + "（前复权）"

    df = df.reset_index(drop=True)
    closes = df["close"].astype(float)
    # 图表数据：每根为 [时间, 开, 收, 低, 高, 成交量]，顺序与图表库的蜡烛图一致
    bars = [
        [t, round(o, 3), round(c, 3), round(lo, 3), round(hi, 3), int(v)]
        for t, o, c, lo, hi, v in zip(
            times, df["open"], df["close"], df["low"], df["high"], df["volume"]
        )
    ]
    title = f"{name}（{code}）{label}"
    block = {
        "type": "kline",
        "title": title,
        "as_of": times[-1],
        "source": {"name": "新浪财经", "url": _source_url(code)},
        "bars": bars,
    }

    # 给模型的是摘要而不是全部数据：上下文有限，图已经由页面展示
    hi_i, lo_i = int(df["high"].idxmax()), int(df["low"].idxmin())
    lines = [
        f"{title}，共 {len(df)} 根，{times[0]} 至 {times[-1]}。K 线图已由系统展示给用户，无需罗列数据。",
        f"区间涨跌幅 {(closes.iloc[-1] / closes.iloc[0] - 1) * 100:+.2f}%"
        f"（首根收盘 {_num(closes.iloc[0])}，最新收盘 {_num(closes.iloc[-1])}）",
        f"区间最高 {_num(df['high'][hi_i])}（{times[hi_i]}），最低 {_num(df['low'][lo_i])}（{times[lo_i]}）",
    ]
    averages = [f"MA{n} {_num(closes.tail(n).mean())}" for n in (5, 10, 20) if len(df) >= n]
    lines.append("最新均线：" + "，".join(averages))
    recent = "；".join(
        f"{t[5:]} 开{_num(o)} 收{_num(c)}" for t, o, c, *_ in bars[-8:]
    )
    lines.append(f"最近 8 根：{recent}")
    lines.append(f"来源：新浪财经 {_source_url(code)}")
    return ToolResult(text="\n".join(lines), blocks=[block])
