"""条件选股（验收 B7）：按估值、行情、技术指标、财务、行业概念任一类或组合条件筛选 A 股。

数据分三部分，各有各的更新节奏：
- 实时部分：行情、估值、区间涨跌幅（腾讯排行接口，全市场约 28 次请求）和股息率、52 周高低点
  （腾讯批量报价，约 19 次请求）。选股时现取，60 秒内复用。
- 财务部分：最新报告期的业绩报表与资产负债率、近三年年报 ROE（东方财富，经 AkShare）。
  每天更新一次，存入数据库 screen_data 表，重启后直接读取。
- 技术部分：由每只股票最近 130 根日 K（腾讯）算出均线、MACD、RSI。每个交易日收盘后更新一次，
  同样存库。约 5600 次请求，后台进行，不影响使用。
行业取自东方财富业绩报表的"所处行业"；概念取自腾讯的概念板块，问到哪个概念再取它的成分股。

所有判断（是否满足条件）都由程序完成，模型只负责把用户的话翻译成条件、解读结果。
"""

import asyncio
import difflib
import json
import logging
import math
import time
from datetime import date, datetime, timedelta
from typing import Any

import akshare as ak
import httpx
import pandas as pd
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ScreenData, now
from app.tools import market
from app.tools.base import ToolError, ToolResult
from app.tools.market import SHANGHAI

logger = logging.getLogger(__name__)

# 字段：键 -> (中文名, 单位, 类别, 是否布尔)。类别决定需要哪部分数据
FIELDS: dict[str, tuple[str, str, str, bool]] = {
    "pe_ttm": ("市盈率TTM", "倍", "live", False),
    "pb": ("市净率", "倍", "live", False),
    "mktcap": ("总市值", "亿", "live", False),
    "float_mktcap": ("流通市值", "亿", "live", False),
    "dividend_yield": ("股息率", "%", "live", False),
    "price": ("最新价", "元", "live", False),
    "pct_chg": ("今日涨跌幅", "%", "live", False),
    "turnover": ("换手率", "%", "live", False),
    "volume_ratio": ("量比", "", "live", False),
    "amount": ("成交额", "亿", "live", False),
    "main_inflow": ("主力净流入", "亿", "live", False),
    "ret_5d": ("5日涨跌幅", "%", "live", False),
    "ret_20d": ("20日涨跌幅", "%", "live", False),
    "ret_60d": ("60日涨跌幅", "%", "live", False),
    "ret_ytd": ("年初至今涨跌幅", "%", "live", False),
    "ret_52w": ("52周涨跌幅", "%", "live", False),
    "from_high_52w": ("距52周高点", "%", "live", False),
    "new_high_52w": ("创52周新高", "", "live", True),
    "ma_bull": ("均线多头排列", "", "tech", True),
    "above_ma20": ("站上20日线", "", "tech", True),
    "above_ma60": ("站上60日线", "", "tech", True),
    "macd_golden": ("近3日MACD金叉", "", "tech", True),
    "rsi14": ("RSI14", "", "tech", False),
    "roe": ("ROE(最新报告期)", "%", "fin", False),
    "roe_annual": ("ROE(最新年报)", "%", "fin", False),
    "roe_min_3y": ("近三年年报ROE最低", "%", "fin", False),
    "revenue_yoy": ("营收同比", "%", "fin", False),
    "profit_yoy": ("净利润同比", "%", "fin", False),
    "gross_margin": ("毛利率", "%", "fin", False),
    "debt_ratio": ("资产负债率", "%", "fin", False),
    "eps": ("每股收益", "元", "fin", False),
    "bps": ("每股净资产", "元", "fin", False),
}
OPS = [">", ">=", "<", "<=", "=", "between"]
# 模型有时写成别的符号，统一换成标准写法
_OP_ALIASES = {"==": "=", "≥": ">=", "≤": "<=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "=",
               "大于": ">", "小于": "<", "不低于": ">=", "不高于": "<=", "介于": "between"}
# 这些估值字段为负表示亏损（或净资产为负），设"低于某值"的条件时不应把亏损股算进来
_POSITIVE_ONLY = {"pe_ttm", "pb"}
_LABEL_TO_FIELD = {label: key for key, (label, *_rest) in FIELDS.items()}
MAX_ROWS = 50

_RANK_URL = (
    "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList?_appver=11.17.0"
    "&board_code={board}&sort_type=price&direct=down&offset={offset}&count=200"
)
_CONCEPT_LIST_URL = (
    "https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank?board_type=gn"
    "&sort_type=priceRatio&direct=down&offset={offset}&count=200"
)
_HEADERS = {"User-Agent": "Mozilla/5.0"}

# 内存中的数据。财务、技术两部分启动时从数据库读出，后台更新后同时写回数据库
_live: tuple[float, pd.DataFrame] | None = None
_live_lock = asyncio.Lock()
_fin: dict[str, Any] | None = None
_tech: dict[str, Any] | None = None
_concepts: tuple[float, dict[str, str]] | None = None
_members: dict[str, tuple[float, set[str]]] = {}


def _num(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


# ---------------------------------------------------------------- 实时部分


async def _rank_all(client: httpx.AsyncClient, url: str) -> list[dict]:
    """腾讯排行接口每页最多 200 条：先取第一页拿到总数，其余页并发取。"""
    resp = await client.get(url.format(offset=0))
    data = resp.json()["data"]
    rows = list(data["rank_list"])
    pages = await asyncio.gather(
        *(client.get(url.format(offset=o)) for o in range(200, int(data["total"]), 200))
    )
    for page in pages:
        rows.extend(page.json()["data"]["rank_list"])
    return rows


async def _fetch_live() -> pd.DataFrame:
    async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as client:
        rank, quotes = await asyncio.gather(
            _rank_all(client, _RANK_URL.replace("{board}", "aStock")),
            market.fetch_quote_fields(market.all_codes()),
        )
    records = {}
    for r in rank:
        code = r["code"][2:]
        records[code] = {
            "code": code,
            "name": r["name"],
            "price": _num(r.get("zxj")),
            "pct_chg": _num(r.get("zdf")),
            "pe_ttm": _num(r.get("pe_ttm")),
            "pb": _num(r.get("pn")),
            "mktcap": _num(r.get("zsz")),
            "float_mktcap": _num(r.get("ltsz")),
            "turnover": _num(r.get("hsl")),
            "volume_ratio": _num(r.get("lb")),
            "amount": _num(r.get("turnover")) / 1e4,  # 原始单位是万元
            "main_inflow": _num(r.get("zljlr")) / 1e4,  # 原始单位是万元
            "ret_5d": _num(r.get("zdf_d5")),
            "ret_20d": _num(r.get("zdf_d20")),
            "ret_60d": _num(r.get("zdf_d60")),
            "ret_ytd": _num(r.get("zdf_y")),
            "ret_52w": _num(r.get("zdf_w52")),
        }
    as_of = ""
    for f in quotes:
        if len(f) < 69 or f[2] not in records:
            continue
        row = records[f[2]]
        row["dividend_yield"] = _num(f[64])
        row["high_52w"] = _num(f[67])
        row["time"] = f[30]
        as_of = max(as_of, f[30])
    if len(records) < 3000:
        raise ToolError(f"实时行情只取到 {len(records)} 只股票，数据不完整，请稍后再试")
    df = pd.DataFrame(records.values()).set_index("code")
    df["from_high_52w"] = (df["price"] / df["high_52w"] - 1) * 100
    df["new_high_52w"] = df["price"] >= df["high_52w"]
    df.attrs["as_of"] = (
        datetime.strptime(as_of, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S") if as_of else ""
    )
    return df


async def _get_live() -> pd.DataFrame:
    global _live
    async with _live_lock:
        if _live is None or time.monotonic() - _live[0] > 60:
            _live = (time.monotonic(), await _fetch_live())
        return _live[1]


# ---------------------------------------------------------------- 财务部分


def _quarter_ends(today: date) -> list[str]:
    """从今天往前的季度末日期，最近的在前。"""
    ends = []
    year = today.year
    while len(ends) < 8:
        for month, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
            d = date(year, month, day)
            if d < today:
                ends.append(d.strftime("%Y%m%d"))
        year -= 1
    return ends[:8]


def _report(fn, period: str) -> pd.DataFrame | None:
    """取一期报表；该期还没有足够多的公司披露时返回 None，由调用方往前找。"""
    try:
        df = fn(date=period)
    except Exception:  # noqa: BLE001 该期没有数据时接口会报错
        return None
    return df if df is not None and len(df) > 3000 else None


def _fetch_financials() -> dict[str, Any]:
    """同步函数，放在线程里跑。约 5 次请求，每次约 6 秒。"""
    today = datetime.now(SHANGHAI).date()
    latest = None
    for period in _quarter_ends(today):
        latest = _report(ak.stock_yjbb_em, period)
        if latest is not None:
            break
    if latest is None:
        raise RuntimeError("最近两年都没有取到业绩报表")
    balance = _report(ak.stock_zcfz_em, period)

    annual: list[tuple[int, pd.DataFrame]] = []
    for year in range(today.year - 1, today.year - 6, -1):
        df = _report(ak.stock_yjbb_em, f"{year}1231")
        if df is not None:
            annual.append((year, df))
        if len(annual) == 3:
            break

    def by_code(df: pd.DataFrame, column: str) -> dict[str, float]:
        return {str(c): _num(v) for c, v in zip(df["股票代码"], df[column])}

    roe_years = [by_code(df, "净资产收益率") for _, df in annual]
    debt = by_code(balance, "资产负债率") if balance is not None else {}
    rows = {}
    for _, r in latest.iterrows():
        code = str(r["股票代码"])
        history = [years.get(code, math.nan) for years in roe_years]
        rows[code] = {
            "roe": _num(r["净资产收益率"]),
            "roe_annual": history[0] if history else math.nan,
            # 三年都有数据才算，缺一年就不参与"近三年"类条件
            "roe_min_3y": min(history) if len(history) == 3 and not any(map(math.isnan, history)) else math.nan,
            "revenue_yoy": _num(r["营业总收入-同比增长"]),
            "profit_yoy": _num(r["净利润-同比增长"]),
            "gross_margin": _num(r["销售毛利率"]),
            "debt_ratio": debt.get(code, math.nan),
            "eps": _num(r["每股收益"]),
            "bps": _num(r["每股净资产"]),
            "industry": str(r["所处行业"]) if isinstance(r["所处行业"], str) else "",
        }
    return {
        "period": f"{period[:4]}-{period[4:6]}-{period[6:]}",
        "annual_years": [year for year, _ in annual],
        "rows": rows,
        "fetched_at": datetime.now(SHANGHAI).strftime("%Y-%m-%d %H:%M"),
    }


# ---------------------------------------------------------------- 技术部分


def _ema(values: list[float], span: int) -> list[float]:
    k = 2 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def _indicators(closes: list[float]) -> dict[str, float] | None:
    """均线、MACD（12,26,9）、RSI14（Wilder 平滑）。不足 60 根 K 线的股票不算。"""
    if len(closes) < 60:
        return None

    def ma(n: int) -> float:
        return sum(closes[-n:]) / n

    dif = [a - b for a, b in zip(_ema(closes, 12), _ema(closes, 26))]
    dea = _ema(dif, 9)
    golden = any(
        dif[i - 1] <= dea[i - 1] and dif[i] > dea[i] for i in range(len(dif) - 3, len(dif))
    )
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:])]
    avg_gain, avg_loss = sum(gains[:14]) / 14, sum(losses[:14]) / 14
    for g, l in zip(gains[14:], losses[14:]):
        avg_gain = (avg_gain * 13 + g) / 14
        avg_loss = (avg_loss * 13 + l) / 14
    rsi = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return {
        "ma5": ma(5),
        "ma10": ma(10),
        "ma20": ma(20),
        "ma60": ma(60),
        "macd_golden": golden,
        "rsi14": round(rsi, 2),
    }


async def _fetch_technicals() -> dict[str, Any]:
    """逐只取日 K 算指标。腾讯会封禁请求过快的来源，所以限速：4 个并发、每次请求后歇 0.15 秒，
    约每秒 20 次，全市场约 5 分钟。每个交易日只跑一次。"""
    codes = market.all_codes()
    rows: dict[str, dict] = {}
    last_dates: list[str] = []
    gate = asyncio.Semaphore(4)
    blocked = False

    async def one(client: httpx.AsyncClient, symbol: str) -> None:
        nonlocal blocked
        if blocked:
            return
        async with gate:
            try:
                bars = await market.fetch_day_bars(client, symbol, 130)
            except market.SourceBlocked:
                blocked = True
                return
            except Exception:  # noqa: BLE001 个别股票取不到就跳过
                return
            finally:
                await asyncio.sleep(0.15)
        result = _indicators([float(b[2]) for b in bars])
        if result:
            rows[symbol[2:]] = result
            last_dates.append(bars[-1][0])

    async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as client:
        await asyncio.gather(*(one(client, s) for s in codes))
    if blocked:
        raise RuntimeError(f"数据源限流，本轮中止（已算出 {len(rows)} 只），稍后重试")
    if len(rows) < 3000:
        raise RuntimeError(f"只算出 {len(rows)} 只股票的技术指标")
    return {
        # 多数股票最后一根 K 线的日期，即"技术指标截至哪天收盘"
        "as_of": max(set(last_dates), key=last_dates.count),
        "rows": rows,
        "fetched_at": datetime.now(SHANGHAI).strftime("%Y-%m-%d %H:%M"),
    }


# ---------------------------------------------------------------- 后台更新与存库


def _json_safe(value: Any) -> Any:
    """PostgreSQL 的 JSON 不接受 NaN（服务器实测写库失败），存库前换成 null。"""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


async def _save(name: str, payload: dict) -> None:
    payload = _json_safe(payload)
    async with SessionLocal() as db:
        row = await db.get(ScreenData, name)
        if row is None:
            db.add(ScreenData(name=name, payload=payload, updated_at=now()))
        else:
            row.payload, row.updated_at = payload, now()
        await db.commit()


async def _load() -> None:
    global _fin, _tech
    async with SessionLocal() as db:
        for row in await db.scalars(select(ScreenData)):
            if row.name == "financials":
                _fin = row.payload
            elif row.name == "technicals":
                _tech = row.payload


def _tech_stale(now_sh: datetime) -> bool:
    """技术指标是否需要更新：收盘（15:10）后，若还不是今天的数据就更新；没有数据时立即更新。"""
    if _tech is None:
        return True
    if now_sh.weekday() >= 5 or (now_sh.hour, now_sh.minute) < (15, 10):
        return False
    return _tech["as_of"] < now_sh.strftime("%Y-%m-%d") and _tech.get("checked") != now_sh.strftime("%Y-%m-%d")


async def keep_screener_fresh() -> None:
    """后台任务：启动时读库；财务每天更新一次，技术指标每个交易日收盘后更新一次。"""
    global _fin, _tech
    try:
        await _load()
    except Exception:  # noqa: BLE001
        logger.exception("读取选股数据快照失败")
    while True:
        now_sh = datetime.now(SHANGHAI)
        today = now_sh.strftime("%Y-%m-%d")
        if _fin is None or _fin["fetched_at"][:10] < today:
            try:
                started = time.monotonic()
                _fin = await asyncio.to_thread(_fetch_financials)
                await _save("financials", _fin)
                logger.info(
                    "选股财务数据已更新：%s 报告期，%d 只，用时 %.0f 秒",
                    _fin["period"], len(_fin["rows"]), time.monotonic() - started,
                )
            except Exception as exc:  # noqa: BLE001 下一轮再试
                logger.warning("选股财务数据更新失败：%r", exc)
        if _tech_stale(now_sh):
            try:
                started = time.monotonic()
                fresh = await _fetch_technicals()
                # 节假日收盘后取到的仍是上一交易日，记下今天已检查过，避免反复抓取
                fresh["checked"] = today
                _tech = fresh
                await _save("technicals", _tech)
                logger.info(
                    "选股技术指标已更新：截至 %s，%d 只，用时 %.0f 秒",
                    _tech["as_of"], len(_tech["rows"]), time.monotonic() - started,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("选股技术指标更新失败：%r", exc)
        await asyncio.sleep(600)


# ---------------------------------------------------------------- 行业与概念


async def _concept_names() -> dict[str, str]:
    global _concepts
    if _concepts is None or time.monotonic() - _concepts[0] > 12 * 3600:
        async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as client:
            rows = await _rank_all(client, _CONCEPT_LIST_URL)
        _concepts = (time.monotonic(), {r["name"]: r["code"] for r in rows})
    return _concepts[1]


def _pick(text: str, names: list[str], kind: str) -> list[str]:
    """按名称找行业或概念：先精确，再包含；都没有就报错并给出相近的名称。"""
    text = text.strip().removesuffix("行业").removesuffix("板块").removesuffix("概念") or text.strip()
    plain = {n: n.rstrip("Ⅱ").removesuffix("概念") for n in names}
    # 依次尝试：名称相同（忽略"Ⅱ""概念"后缀）→ 以该词开头 → 包含该词。取第一种有结果的，
    # 避免"白酒"同时匹配到"非白酒"
    for rule in (
        lambda n: plain[n] == text,
        lambda n: plain[n].startswith(text),
        lambda n: text in plain[n] and not plain[n].startswith("非"),
    ):
        hits = [n for n in names if rule(n)]
        if hits:
            return hits
    close = difflib.get_close_matches(text, names, n=6, cutoff=0.3)
    hint = f"相近的有：{'、'.join(close)}。" if close else ""
    raise ToolError(f"没有名为「{text}」的{kind}。{hint}可换一个名称再试。")


async def _concept_members(text: str) -> tuple[list[str], set[str]]:
    names = await _concept_names()
    picked = _pick(text, list(names), "概念")[:3]
    members: set[str] = set()
    async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as client:
        for name in picked:
            code = names[name]
            hit = _members.get(code)
            if hit is None or time.monotonic() - hit[0] > 6 * 3600:
                rows = await _rank_all(client, _RANK_URL.replace("{board}", code))
                hit = (time.monotonic(), {r["code"][2:] for r in rows})
                _members[code] = hit
            members |= hit[1]
    return picked, members


# ---------------------------------------------------------------- 选股


def _describe(cond: dict) -> str:
    label, unit, _, is_bool = FIELDS[cond["field"]]
    if is_bool:
        return label if cond["value"] else f"非{label}"
    if cond["op"] == "between":
        low, high = cond["value"]
        return f"{label} 在 {low:g}~{high:g}{unit} 之间"
    return f"{label} {cond['op']} {cond['value']:g}{unit}"


def _normalize(conditions: list) -> list[dict]:
    """校验并规范化条件。出错时的提示会交给模型，让它改正后重试。"""
    if isinstance(conditions, str):
        # 模型有时把数组写成了 JSON 字符串
        try:
            conditions = json.loads(conditions)
        except ValueError:
            raise ToolError("conditions 应为数组，例如 [{\"field\": \"pe_ttm\", \"op\": \"<\", \"value\": 15}]") from None
    if isinstance(conditions, dict):
        conditions = [conditions]
    out = []
    for raw in conditions or []:
        if isinstance(raw, dict) and raw.get("field") in _LABEL_TO_FIELD:
            raw = {**raw, "field": _LABEL_TO_FIELD[raw["field"]]}
        if not isinstance(raw, dict) or raw.get("field") not in FIELDS:
            raise ToolError(
                f"条件 {raw} 的 field 不正确，可用字段：{'、'.join(FIELDS)}。"
                "如果用户要求的条件不在其中，请如实告诉用户暂不支持。"
            )
        field = raw["field"]
        is_bool = FIELDS[field][3]
        op = str(raw.get("op") or "=").strip()
        op = _OP_ALIASES.get(op, op)
        value = raw.get("value", True if is_bool else None)
        if isinstance(value, str) and op == "between":
            try:
                value = json.loads(value)
            except ValueError:
                pass
        if is_bool:
            if isinstance(value, str):
                value = value.lower() not in ("false", "0", "否")
            out.append({"field": field, "op": "=", "value": bool(value)})
            continue
        if op not in OPS:
            raise ToolError(f"条件 {raw} 的 op 不正确，可用：{'、'.join(OPS)}")
        try:
            if op == "between":
                low, high = sorted(float(v) for v in value)
                value = [low, high]
            else:
                value = float(value)
        except (TypeError, ValueError):
            raise ToolError(f"条件 {raw} 的 value 不是数值（between 时为 [下限, 上限]）") from None
        out.append({"field": field, "op": op, "value": value})
    return out


def _mask(series: pd.Series, cond: dict) -> pd.Series:
    v, op = cond["value"], cond["op"]
    if FIELDS[cond["field"]][3]:
        return series.fillna(False).astype(bool) == v
    if op == "between":
        return series.between(v[0], v[1])
    return {
        ">": series > v,
        ">=": series >= v,
        "<": series < v,
        "<=": series <= v,
        "=": (series - v).abs() < 1e-9,
    }[op]


def _fmt(field: str, value: Any) -> str:
    if field == "industry":
        return value or "—"
    label, unit, _, is_bool = FIELDS[field]
    if is_bool:
        return "是" if value else "否"
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if unit == "亿":
        return f"{value:,.2f} 亿"
    if field in ("pct_chg", "ret_5d", "ret_20d", "ret_60d", "ret_ytd", "ret_52w", "from_high_52w",
                 "revenue_yoy", "profit_yoy", "main_inflow"):
        return f"{value:+.2f}{unit}"
    return f"{value:.2f}{unit}"


async def screen_stocks(
    conditions: list | None = None,
    industry: str = "",
    concept: str = "",
    sort_by: str = "",
    order: str = "",
    limit: int = 20,
    include_st: bool = False,
) -> ToolResult:
    conds = _normalize(conditions or [])
    industry, concept = (industry or "").strip(), (concept or "").strip()
    if not conds and not industry and not concept:
        raise ToolError("没有给出任何筛选条件")
    if sort_by and sort_by not in FIELDS:
        raise ToolError(f"sort_by 不正确，可用字段：{'、'.join(FIELDS)}")
    limit = max(1, min(int(limit or 20), MAX_ROWS))

    groups = {FIELDS[c["field"]][2] for c in conds}
    if sort_by:
        groups.add(FIELDS[sort_by][2])
    if industry:
        groups.add("fin")
    if "fin" in groups and _fin is None:
        raise ToolError("财务数据正在准备（服务启动后首次约需半分钟），请稍后再试")
    if "tech" in groups and _tech is None:
        raise ToolError("技术指标正在计算（服务启动后首次约需两三分钟），请稍后再试")

    df = (await _get_live()).copy()
    # 停牌或当天无成交的股票不参与筛选
    df = df[(df["price"] > 0) & (df["amount"] > 0)]
    if not include_st:
        df = df[~df["name"].str.contains("ST", case=False, na=False)]
    if _fin is not None:
        # 存库时 NaN 变成了 null，读回来是 None；统一转回数值列里的 NaN
        fin = pd.DataFrame.from_dict(_fin["rows"], orient="index")
        numeric = [c for c in fin.columns if c != "industry"]
        fin[numeric] = fin[numeric].apply(pd.to_numeric, errors="coerce")
        fin["industry"] = fin["industry"].fillna("")
        df = df.join(fin, how="left")
    if _tech is not None:
        tech = pd.DataFrame.from_dict(_tech["rows"], orient="index")
        tech[["ma5", "ma10", "ma20", "ma60", "rsi14"]] = tech[["ma5", "ma10", "ma20", "ma60", "rsi14"]].apply(
            pd.to_numeric, errors="coerce"
        )
        df = df.join(tech, how="left")
        # 价格与均线的比较用最新价，均线用截至上一个收盘的数据
        df["above_ma20"] = df["price"] > df["ma20"]
        df["above_ma60"] = df["price"] > df["ma60"]
        df["ma_bull"] = (df["ma5"] > df["ma10"]) & (df["ma10"] > df["ma20"]) & (df["ma20"] > df["ma60"])
    total = len(df)

    scope: list[str] = []
    if industry:
        names = sorted({n for n in df["industry"].dropna().unique() if n})
        picked = _pick(industry, names, "行业")
        df = df[df["industry"].isin(picked)]
        scope.append(f"行业：{'、'.join(picked[:5])}{'等' if len(picked) > 5 else ''}")
    if concept:
        picked, members = await _concept_members(concept)
        df = df[df.index.isin(members)]
        scope.append(f"概念：{'、'.join(picked)}")
    positive_only = False
    for cond in conds:
        df = df[_mask(df[cond["field"]], cond)]
        # "市盈率低于 10"指盈利且估值低，亏损股的市盈率为负，不算满足
        if cond["field"] in _POSITIVE_ONLY and cond["op"] in ("<", "<=", "between"):
            df = df[df[cond["field"]] > 0]
            positive_only = True

    # 没指定排序时按第一个数值条件排：要求"低于"的从低到高，要求"高于"的从高到低；都没有就按市值
    first = next((c for c in conds if not FIELDS[c["field"]][3]), None)
    sort_field = sort_by or (first["field"] if first else "mktcap")
    if order not in ("asc", "desc"):
        order = "asc" if not sort_by and first and first["op"] in ("<", "<=", "between") else "desc"
    df = df.sort_values(sort_field, ascending=(order == "asc"), na_position="last")
    shown = df.head(limit)

    # 表格列：名称、最新价、涨跌幅、各条件字段、排序字段、行业
    columns = ["price", "pct_chg"]
    for field in [c["field"] for c in conds] + [sort_field]:
        if field not in columns:
            columns.append(field)
    if "industry" in df.columns:
        columns.append("industry")

    live = await _get_live()
    notes = [f"行情时间 {live.attrs.get('as_of', '')}"]
    if _fin is not None and ({"fin"} & groups or industry):
        years = _fin["annual_years"]
        notes.append(
            f"财务为 {_fin['period']} 报告期"
            + (f"，年报 ROE 取 {years[-1]}–{years[0]} 年" if years else "")
        )
    if _tech is not None and "tech" in groups:
        notes.append(f"技术指标的均线、MACD、RSI 截至 {_tech['as_of']} 收盘")
    notes.append("已排除停牌" + ("" if include_st else "和 ST 股票"))
    if positive_only:
        notes.append("市盈率、市净率为负（亏损或资不抵债）的股票不参与“低于”类条件")
    rule = "；".join(scope + [_describe(c) for c in conds]) or "无"
    order_text = f"按{FIELDS[sort_field][0]}{'从低到高' if order == 'asc' else '从高到低'}"

    block = {
        "type": "table",
        "title": f"条件选股：共 {len(df)} 只符合" + (f"，显示前 {len(shown)} 只" if len(df) > len(shown) else ""),
        "columns": ["股票", *("行业" if f == "industry" else FIELDS[f][0] for f in columns)],
        "rows": [
            [f"{r['name']}（{code}）", *(_fmt(f, r.get(f)) for f in columns)]
            for code, r in shown.iterrows()
        ],
        "note": f"条件：{rule}。{order_text}。" + "；".join(notes) + "。",
        "source": {"name": "腾讯财经、东方财富", "url": "https://gu.qq.com/"},
    }
    if not len(shown):
        block["rows"] = []

    lines = [
        f"条件选股结果：在 {total} 只股票中，共 {len(df)} 只满足全部条件（{rule}），{order_text}。",
        "；".join(notes) + "。",
        "完整结果表格已展示给用户，不要再用表格或逐行列出这些股票；用几句话概括特征，点名两三只做简评。下面是排在前面的股票，供你解读：",
    ]
    for code, r in shown.head(10).iterrows():
        lines.append(
            f"{r['name']}（{code}）："
            + "，".join(f"{FIELDS[f][0]} {_fmt(f, r.get(f))}" for f in columns if f != "industry")
            + (f"，{r['industry']}" if isinstance(r.get("industry"), str) and r.get("industry") else "")
        )
    if not len(df):
        lines.append("没有股票满足全部条件。请告诉用户，并建议放宽哪一条。")
    lines.append("来源（请原样写在回答末尾）：[腾讯财经](https://gu.qq.com/)、[东方财富数据中心](https://data.eastmoney.com/bbsj/)")
    return ToolResult(text="\n".join(lines), blocks=[block] if len(df) else [])
