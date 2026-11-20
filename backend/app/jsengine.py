"""串行调用需要执行 JavaScript 的 AkShare 接口。

部分 AkShare 接口（新浪交易日历、新浪日 K、同花顺行业板块）会在进程内用 py_mini_racer
（内嵌 V8 引擎）解密数据。V8 在多个线程同时初始化或运行时会让整个进程崩溃（段错误），
Python 无法捕获，后端会被 systemd 重启。所以这些接口一律经 call() 一个一个地执行。
"""

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
_LOCK = threading.Lock()


def call(fn: Callable[..., T], *args, **kwargs) -> T:
    """在线程里调用（如 asyncio.to_thread(call, fn, ...)）。等太久就放弃，避免线程池被排队占满。"""
    if not _LOCK.acquire(timeout=90):
        raise TimeoutError("另一个需要执行 JavaScript 的数据请求还没结束")
    try:
        return fn(*args, **kwargs)
    finally:
        _LOCK.release()
