"""行情与 K 线。K 线经 AkShare 取自新浪财经；实时报价直接取自腾讯财经，新浪财经作后备。

AkShare 是同步库，调用都放到线程里；结果做短时间缓存，避免多人同时问同一只股票时重复抓取。
"""

import asyncio
import csv
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import httpx
import pandas as pd

from app.tools.base import ToolError, ToolResult

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")

MINUTE_PERIODS = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
DAY_PERIODS = {"daily": "日K", "weekly": "周K", "monthly": "月K"}
# 取这么多根 K 线大约要往前推多少个自然日
_DAYS_PER_BAR = {"daily": 1.6, "weekly": 7.5, "monthly": 32}

DATA_DIR = Path(__file__).parent / "data"

_cache: dict[tuple, tuple[float, Any]] = {}
_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
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


def _build_table(pairs: list[tuple[str, str]]) -> dict[str, dict[str, str]]:
    by_code = {code: name.replace(" ", "") for code, name in pairs}
    by_name = {_normalize(name): code for code, name in by_code.items()}
    return {"by_code": by_code, "by_name": by_name}


def _read_bundled_table() -> dict[str, dict[str, str]]:
    with (DATA_DIR / "stocks.csv").open(encoding="utf-8", newline="") as f:
        return _build_table([(row["code"], row["name"]) for row in csv.DictReader(f)])


def _fetch_table() -> dict[str, dict[str, str]]:
    df = ak.stock_info_a_code_name()
    return _build_table([(str(c), str(n)) for c, n in zip(df["code"], df["name"])])


# 股票名称表。先用随代码发布的快照，保证任何时候都能按简称查；
# 后台定期从交易所刷新，以便认出新上市和改名的股票。刷新失败就继续用手头这份。
_table = _read_bundled_table()


async def keep_stock_table_fresh() -> None:
    """后端启动后在后台一直运行：立即刷新一次名称表，之后每 12 小时一次。"""
    global _table
    while True:
        try:
            fresh = await asyncio.to_thread(_fetch_table)
            if len(fresh["by_code"]) > 3000:  # 明显残缺的结果不采用
                _table = fresh
            await asyncio.sleep(12 * 3600)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 交易所网站偶尔取不到，不影响使用
            logger.warning("股票名称表刷新失败，继续使用现有名称表，30 分钟后重试")
            await asyncio.sleep(1800)


def _exchange_prefix(code: str) -> str:
    if code.startswith(("6", "9")) and not code.startswith("92"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    return "bj"


def resolve_stock(symbol: str) -> tuple[str, str]:
    """把用户或模型给的"代码或简称"解析成（6 位代码，简称）。"""
    text = _normalize(symbol)
    digits = re.search(r"\d{6}", text)
    by_code, by_name = _table["by_code"], _table["by_name"]
    if digits:
        # 名称表可能还没收录新上市的股票，所以不认识的代码也放行，由数据源判断是否存在
        code = digits.group()
        return code, by_code.get(code, code)
    if text in by_name:
        code = by_name[text]
        return code, by_code[code]
    matches = [code for name, code in by_name.items() if text and text in name]
    if len(matches) == 1:
        return matches[0], by_code[matches[0]]
    if len(matches) > 1:
        names = "、".join(by_code[c] for c in matches[:8])
        raise ToolError(f"「{symbol}」对应多只股票：{names}。请用 6 位代码或完整简称重新查询。")
    raise ToolError(f"未找到股票「{symbol}」，请确认名称或提供 6 位代码。")


def _sina_url(code: str) -> str:
    return f"https://finance.sina.com.cn/realstock/company/{_exchange_prefix(code)}{code}/nc.shtml"


def _tencent_url(code: str) -> str:
    return f"https://gu.qq.com/{_exchange_prefix(code)}{code}/gp"


def _cite(source: str, title: str, url: str) -> str:
    """来源行。直接给出写好的 Markdown 链接，让模型照抄，避免它把来源名称和链接配错。"""
    return f"来源（请原样写在回答末尾）：[{source}·{title}]({url})"


def _minute_bars(code: str, period: str, adjust: str = "") -> pd.DataFrame:
    df = ak.stock_zh_a_hist_min_sina(
        symbol=_exchange_prefix(code) + code, period=period, adjust=adjust
    )
    if df is None or df.empty:
        raise ToolError("数据源没有返回分钟行情，请确认股票代码是否正确")
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
        raise ToolError("数据源没有返回 K 线数据，请确认股票代码是否正确")
    df["date"] = pd.to_datetime(df["date"])
    return df.reset_index(drop=True)


def _num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def _parse_tencent(body: str) -> dict[str, Any] | None:
    """腾讯报价是一行用 ~ 分隔的文本；字段位置是固定的。"""
    if "none_match" in body or '"' not in body:
        return None
    f = body.split('"')[1].split("~")
    if len(f) < 38 or not f[3]:
        return None
    return {
        "name": f[1],
        "price": float(f[3]),
        "prev_close": float(f[4]),
        "open": float(f[5]),
        "high": float(f[33]),
        "low": float(f[34]),
        "volume_lots": float(f[36]),
        "amount_yi": float(f[37]) / 1e4,  # 原始单位是万元
        "time": datetime.strptime(f[30], "%Y%m%d%H%M%S"),
        "source": "腾讯财经",
        "url": _tencent_url,
    }


def _parse_sina(body: str) -> dict[str, Any] | None:
    """新浪报价是一行用逗号分隔的文本。"""
    if '"' not in body:
        return None
    f = body.split('"')[1].split(",")
    if len(f) < 32 or not f[0]:
        return None
    return {
        "name": f[0],
        "price": float(f[3]),
        "prev_close": float(f[2]),
        "open": float(f[1]),
        "high": float(f[4]),
        "low": float(f[5]),
        "volume_lots": float(f[8]) / 100,  # 原始单位是股
        "amount_yi": float(f[9]) / 1e8,  # 原始单位是元
        "time": datetime.strptime(f"{f[30]} {f[31]}", "%Y-%m-%d %H:%M:%S"),
        "source": "新浪财经",
        "url": _sina_url,
    }


async def _realtime_quote(code: str) -> dict[str, Any] | None:
    """取实时报价：先腾讯，取不到再新浪。两家都不可用时返回 None，由调用方退到分钟线。

    实测腾讯报价比当前时间滞后 1–5 秒（交易所快照本身约 3 秒一次）。
    AkShare 没有封装单只股票的实时报价，所以这里直接请求两家的公开报价接口。
    """
    symbol = _exchange_prefix(code) + code
    sources = (
        (f"https://qt.gtimg.cn/q={symbol}", {}, _parse_tencent),
        (
            f"https://hq.sinajs.cn/list={symbol}",
            {"Referer": "https://finance.sina.com.cn"},
            _parse_sina,
        ),
    )
    async with httpx.AsyncClient(timeout=3) as client:
        for url, headers, parse in sources:
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                quote = parse(resp.content.decode("gbk", errors="replace"))
            except Exception:  # noqa: BLE001 这一家不可用就换下一家
                logger.warning("实时报价接口不可用：%s", url.split("/")[2])
                continue
            if quote is None:
                # 接口正常但不认识这个代码
                raise ToolError(f"没有代码为 {code} 的 A 股股票。")
            return quote
    return None


async def _minute_quote(code: str) -> dict[str, Any]:
    """实时接口都不可用时的后备：用 1 分钟线拼出行情，最多滞后约 1 分钟。"""
    minutes = await _cached(("min", code, "1", ""), 3, lambda: _minute_bars(code, "1"))
    last = minutes.iloc[-1]
    as_of: datetime = last["day"].to_pydatetime()
    today = minutes[minutes["day"].dt.date == as_of.date()]
    start = (as_of - timedelta(days=20)).strftime("%Y%m%d")
    days = await _cached(
        ("day", code, "daily", "", start[:6]), 600, lambda: _day_bars(code, "daily", start, "")
    )
    earlier = days[days["date"].dt.date < as_of.date()]
    return {
        "name": None,
        "price": float(last["close"]),
        "prev_close": float(earlier.iloc[-1]["close"]) if not earlier.empty else None,
        "open": float(today.iloc[0]["open"]),
        "high": float(today["high"].max()),
        "low": float(today["low"].min()),
        "volume_lots": float(today["volume"].sum()) / 100,
        "amount_yi": float(today["amount"].sum()) / 1e8,
        "time": as_of,
        "source": "新浪财经（分钟线，实时接口暂不可用）",
        "url": _sina_url,
    }


async def get_stock_quote(symbol: str) -> ToolResult:
    code, name = resolve_stock(symbol)
    hit = _quote_cache.get(code)
    if hit and time.monotonic() - hit[0] < 1:  # 1 秒内多人问同一只股票，只取一次
        quote = hit[1]
    else:
        quote = await _realtime_quote(code) or await _minute_quote(code)
        _quote_cache[code] = (time.monotonic(), quote)

    name = quote["name"] or name
    price, prev = quote["price"], quote["prev_close"]
    lines = [f"{name}（{code}）行情，数据时间 {quote['time']:%Y-%m-%d %H:%M:%S}（北京时间）"]
    if price <= 0:
        lines.append(f"当前没有成交价（可能停牌或尚未开盘），昨收 {_num(prev or 0)} 元")
    else:
        lines.append(f"最新价 {_num(price)} 元")
        if prev:
            lines.append(
                f"涨跌额 {price - prev:+.2f} 元，涨跌幅 {(price - prev) / prev * 100:+.2f}%，"
                f"昨收 {_num(prev)} 元"
            )
        lines.append(
            f"今开 {_num(quote['open'])}，最高 {_num(quote['high'])}，最低 {_num(quote['low'])}，"
            f"成交量 {quote['volume_lots']:.0f} 手，成交额 {quote['amount_yi']:.2f} 亿元"
        )
    lines.append(_cite(quote["source"], f"{name}（{code}）行情", quote["url"](code)))
    if price <= 0:
        return ToolResult(text="\n".join(lines))
    # 行情卡片：由页面直接展示，数字不经模型转述
    card = {
        "type": "quote",
        "name": name,
        "code": code,
        "price": price,
        "prev_close": prev,
        "open": quote["open"],
        "high": quote["high"],
        "low": quote["low"],
        "volume_lots": quote["volume_lots"],
        "amount_yi": quote["amount_yi"],
        "as_of": f"{quote['time']:%Y-%m-%d %H:%M:%S}",
        "source": {"name": quote["source"], "url": quote["url"](code)},
    }
    return ToolResult(text="\n".join(lines), blocks=[card])


async def get_kline(symbol: str, period: str = "daily", count: int = 120) -> ToolResult:
    if period not in MINUTE_PERIODS and period not in DAY_PERIODS:
        raise ToolError(f"不支持的周期「{period}」")
    count = max(20, min(int(count), 250))
    code, name = resolve_stock(symbol)

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
        "source": {"name": "新浪财经", "url": _sina_url(code)},
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
    lines.append(_cite("新浪财经", f"{name}（{code}）K 线", _sina_url(code)))
    return ToolResult(text="\n".join(lines), blocks=[block])
