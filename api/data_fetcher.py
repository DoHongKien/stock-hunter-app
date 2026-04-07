"""
data_fetcher.py — Lấy dữ liệu OHLCV cho cổ phiếu Việt Nam
--------------------------------------------------------------
Ưu tiên sử dụng vnstock v3 (VCI source) → dữ liệu HOSE/HNX chính thức.
vnstock ≥ 3.4 không còn hỗ trợ source="TCBS"; dùng VCI thay thế.
Fallback sang yfinance nếu vnstock thất bại.
"""
import time
import math
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

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


# ── VNSTOCK (PRIMARY) ─────────────────────────────────────────────────
def _fetch_vnstock(ticker: str, start: datetime, end: datetime) -> Optional[pd.DataFrame]:
    """
    Dùng vnstock v3 (VCI source) để lấy dữ liệu lịch sử.
    Trả về DataFrame với columns: Open, High, Low, Close, Volume
    index là DatetimeIndex (naive, UTC+7).

    Lưu ý: vnstock ≥ 3.4 không còn hỗ trợ source="TCBS".
    Dùng VCI (ổn định) → fallback KBS.
    """
    try:
        from vnstock import Vnstock  # lazy import
        stock = Vnstock().stock(symbol=ticker.upper(), source="VCI")
        df = stock.quote.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1D",
        )
        if df is None or df.empty:
            return None

        # vnstock trả về: time, open, high, low, close, volume (lowercase)
        # Chuẩn hoá về uppercase columns
        col_map = {
            "time":   "Date",
            "open":   "Open",
            "high":   "High",
            "low":    "Low",
            "close":  "Close",
            "volume": "Volume",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # Set index
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
        elif df.index.name and "time" in df.index.name.lower():
            df.index = pd.to_datetime(df.index)
            df.index.name = "Date"

        # Đảm bảo index là naive datetime
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Đảm bảo có đủ columns
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                logger.warning(f"[vnstock] Thiếu cột {col}")
                return None

        logger.info(f"[vnstock] OK {ticker} — {len(df)} rows")
        return df

    except ImportError:
        logger.warning("[vnstock] Chưa cài — pip install vnstock")
        return None
    except Exception as e:
        logger.warning(f"[vnstock] Lỗi {ticker}: {e}")
        return None


# ── YFINANCE (FALLBACK) ───────────────────────────────────────────────
def _fetch_yfinance(ticker: str, start: datetime, end: datetime, retries: int = 2) -> Optional[pd.DataFrame]:
    """
    Dùng yfinance với retry + delay (tránh rate-limit).
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("[yfinance] Chưa cài")
        return None

    sym = f"{ticker}.VN" if not ticker.upper().endswith(".VN") else ticker.upper()

    for attempt in range(retries + 1):
        try:
            hist = yf.Ticker(sym).history(
                start=start.strftime("%Y-%m-%d"),
                end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
            )
            if hist.empty:
                return None
            # Strip timezone
            if hasattr(hist.index, "tz") and hist.index.tz is not None:
                hist.index = hist.index.tz_localize(None)
            logger.info(f"[yfinance] OK {ticker} — {len(hist)} rows")
            return hist
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str or "too many" in err_str:
                wait = (attempt + 1) * 10  # 10s, 20s
                logger.warning(f"[yfinance] Rate-limit {ticker}, chờ {wait}s (lần {attempt+1})")
                time.sleep(wait)
            else:
                logger.warning(f"[yfinance] Lỗi {ticker}: {e}")
                break

    return None


# ── PUBLIC API ────────────────────────────────────────────────────────
def fetch_history(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    """
    Lấy OHLCV history. Thứ tự ưu tiên: cache → vnstock → yfinance.
    Raises ValueError nếu không lấy được dữ liệu.
    """
    raw = ticker.upper().strip()
    cache_key = f"{raw}_{start.date()}_{end.date()}"

    # Kiểm tra cache
    entry = _hist_cache.get(cache_key)
    if entry and (time.time() - entry["ts"]) < HIST_CACHE_TTL:
        logger.debug(f"[cache-hit] {cache_key}")
        return entry["df"].copy()

    # Thử vnstock trước
    df = _fetch_vnstock(raw, start, end)

    # Fallback yfinance
    if df is None:
        logger.info(f"[fallback] Dùng yfinance cho {raw}")
        df = _fetch_yfinance(raw, start, end)

    if df is None or df.empty:
        raise ValueError(f"Không lấy được dữ liệu cho '{raw}'. Thử lại sau.")

    # Lưu cache
    _hist_cache[cache_key] = {"df": df, "ts": time.time()}
    return df.copy()


def fetch_latest_price(ticker: str) -> Optional[float]:
    """
    Lấy giá đóng cửa mới nhất (có cache 5 phút).
    """
    raw = ticker.upper().strip()

    # Kiểm tra price cache
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
    """
    Lấy giá nhiều mã cùng lúc.
    Với vnstock, chạy từng mã (đã cache nên nhanh).
    Với yfinance, dùng yf.download() batch để giảm request.
    """
    result: dict = {}
    need_fetch: list[str] = []

    # Kiểm tra cache trước
    for raw in [t.upper().strip() for t in tickers]:
        entry = _price_cache.get(raw)
        if entry and (time.time() - entry["ts"]) < PRICE_CACHE_TTL:
            result[raw] = entry["price"]
        else:
            need_fetch.append(raw)

    if not need_fetch:
        return result

    # Thử vnstock batch
    fetched_by_vnstock = _batch_vnstock(need_fetch)
    still_need = []
    for raw in need_fetch:
        if raw in fetched_by_vnstock and fetched_by_vnstock[raw] is not None:
            result[raw] = fetched_by_vnstock[raw]
            _price_cache[raw] = {"price": fetched_by_vnstock[raw], "ts": time.time()}
        else:
            still_need.append(raw)

    # Fallback: yfinance batch cho những mã còn lại
    if still_need:
        fetched_by_yf = _batch_yfinance(still_need)
        for raw, price in fetched_by_yf.items():
            result[raw] = price
            if price is not None:
                _price_cache[raw] = {"price": price, "ts": time.time()}

    # Đảm bảo tất cả tickers đều có key
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


def _batch_yfinance(tickers: list[str]) -> dict[str, Optional[float]]:
    """Batch download bằng yf.download() — 1 request thay vì N requests."""
    result: dict = {raw: None for raw in tickers}
    if not tickers:
        return result

    try:
        import yfinance as yf
        syms = [f"{r}.VN" if not r.endswith(".VN") else r for r in tickers]

        df = yf.download(
            syms if len(syms) > 1 else syms[0],
            period="5d",
            auto_adjust=True,
            progress=False,
        )

        if df.empty:
            return result

        if len(syms) == 1:
            close = round(float(df["Close"].dropna().iloc[-1]), 2) if not df.empty else None
            result[tickers[0]] = close
        else:
            try:
                close_df = df["Close"]
            except KeyError:
                close_df = df.xs("Close", axis=1, level=0)

            for raw, sym in zip(tickers, syms):
                try:
                    s = close_df[sym].dropna()
                    result[raw] = round(float(s.iloc[-1]), 2) if not s.empty else None
                except Exception:
                    result[raw] = None

    except Exception as e:
        logger.warning(f"[yfinance-batch] Lỗi: {e}")

    return result


def clear_cache():
    """Xóa toàn bộ cache (dùng cho testing)."""
    _hist_cache.clear()
    _price_cache.clear()
