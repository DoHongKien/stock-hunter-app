"""
data_fetcher.py — Lấy dữ liệu OHLCV cho cổ phiếu Việt Nam
--------------------------------------------------------------
Sử dụng vnstock v3 (VCI source) — dữ liệu HOSE/HNX chính thức.
Yêu cầu vnstock >= 3.4.0 (source="TCBS" đã bị xóa từ phiên bản này).
"""
import time
import math
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── IN-MEMORY CACHE ───────────────────────────────────────────────────
# {ticker: {"df": DataFrame, "ts": float}}
_hist_cache: dict = {}
_price_cache: dict = {}

HIST_CACHE_TTL  = 900   # 15 phút cho OHLCV history
PRICE_CACHE_TTL = 300   # 5 phút cho giá đơn lẻ


def _safe_float(val, default=0.0) -> float:
    try:
        v = float(val)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return default


# ── VNSTOCK ───────────────────────────────────────────────────────────
def _fetch_vnstock(ticker: str, start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    """
    Dùng vnstock v3 (VCI source) để lấy dữ liệu lịch sử.
    Trả về DataFrame với columns: Open, High, Low, Close, Volume
    index là DatetimeIndex (naive).
    """
    try:
        from vnstock import Vnstock
        stock = Vnstock().stock(symbol=ticker.upper(), source="VCI")
        df = stock.quote.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1D",
        )
        if df is None or df.empty:
            return None

        # vnstock trả về: time, open, high, low, close, volume (lowercase)
        col_map = {
            "time":   "Date",
            "open":   "Open",
            "high":   "High",
            "low":    "Low",
            "close":  "Close",
            "volume": "Volume",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
        elif df.index.name and "time" in df.index.name.lower():
            df.index = pd.to_datetime(df.index)
            df.index.name = "Date"

        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                logger.warning(f"[vnstock] Thiếu cột {col}")
                return None

        logger.info(f"[vnstock] OK {ticker} — {len(df)} rows")
        return df

    except ImportError:
        logger.warning("[vnstock] Chưa cài — pip install 'vnstock>=3.4.0'")
        return None
    except Exception as e:
        logger.warning(f"[vnstock] Lỗi {ticker}: {e}")
        return None


# ── PUBLIC API ────────────────────────────────────────────────────────
def fetch_history(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    """
    Lấy OHLCV history. Thứ tự ưu tiên: cache → vnstock (VCI).
    Raises ValueError nếu không lấy được dữ liệu.
    """
    raw = ticker.upper().strip()
    cache_key = f"{raw}_{start.date()}_{end.date()}"

    entry = _hist_cache.get(cache_key)
    if entry and (time.time() - entry["ts"]) < HIST_CACHE_TTL:
        logger.debug(f"[cache-hit] {cache_key}")
        return entry["df"].copy()

    df = _fetch_vnstock(raw, start, end)

    if df is None or df.empty:
        raise ValueError(f"Không lấy được dữ liệu cho '{raw}'. Kiểm tra lại mã hoặc thử sau.")

    _hist_cache[cache_key] = {"df": df, "ts": time.time()}
    return df.copy()


def fetch_latest_price(ticker: str) -> Optional[float]:
    """Lấy giá đóng cửa mới nhất (cache 5 phút)."""
    raw = ticker.upper().strip()

    entry = _price_cache.get(raw)
    if entry and (time.time() - entry["ts"]) < PRICE_CACHE_TTL:
        return entry["price"]

    today = datetime.now()
    start = today - timedelta(days=7)

    try:
        df = fetch_history(raw, start, today)
        if df is None or df.empty:
            return None
        price = round(_safe_float(df["Close"].dropna().iloc[-1]), 2)
        _price_cache[raw] = {"price": price, "ts": time.time()}
        return price
    except Exception as e:
        logger.warning(f"[price] Lỗi {raw}: {e}")
        return None


def fetch_latest_prices_batch(tickers: list[str]) -> dict[str, Optional[float]]:
    """Lấy giá nhiều mã cùng lúc qua vnstock (VCI)."""
    result: dict = {}
    need_fetch: list[str] = []

    for raw in [t.upper().strip() for t in tickers]:
        entry = _price_cache.get(raw)
        if entry and (time.time() - entry["ts"]) < PRICE_CACHE_TTL:
            result[raw] = entry["price"]
        else:
            need_fetch.append(raw)

    if not need_fetch:
        return result

    fetched = _batch_vnstock(need_fetch)
    for raw in need_fetch:
        price = fetched.get(raw)
        result[raw] = price
        if price is not None:
            _price_cache[raw] = {"price": price, "ts": time.time()}

    for raw in [t.upper().strip() for t in tickers]:
        if raw not in result:
            result[raw] = None

    return result


def _batch_vnstock(tickers: list[str]) -> dict[str, Optional[float]]:
    """Lấy giá mới nhất của nhiều mã qua vnstock (VCI source)."""
    result: dict = {}
    today = datetime.now()
    start = today - timedelta(days=7)

    try:
        from vnstock import Vnstock  # check import once
    except ImportError:
        return result

    for raw in tickers:
        try:
            df = _fetch_vnstock(raw, start, today)
            if df is not None and not df.empty:
                price = round(_safe_float(df["Close"].dropna().iloc[-1]), 2)
                result[raw] = price
        except Exception:
            pass

    return result


def clear_cache():
    """Xóa toàn bộ cache (dùng cho testing)."""
    _hist_cache.clear()
    _price_cache.clear()
