"""
Thợ Săn Điểm Vào — FastAPI Backend
Cung cấp REST API cho PWA mobile app.
"""
import sys, os, math, traceback, time, logging
from datetime import datetime, timedelta
from typing import Optional

# Trỏ vào thư mục gốc chứa search_stock_history.py
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import pandas as pd
import numpy as np
import json

# Data source: vnstock v3 (VCI) primary, yfinance fallback
from api.data_fetcher import fetch_history, fetch_latest_price, fetch_latest_prices_batch

# Import core logic từ project gốc
try:
    from search_stock_history import (
        is_hammer,
        generate_trading_plan,
        generate_recent_sessions_message,
        gui_tin_nhan_telegram,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
    )
except ImportError as e:
    print(f"[WARN] Không import được search_stock_history: {e}")
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID   = ""
    def is_hammer(row):
        body = abs(row['Close'] - row['Open'])
        lower = min(row['Open'], row['Close']) - row['Low']
        upper = row['High'] - max(row['Open'], row['Close'])
        if body > 0 and lower > 2 * body and upper < body:
            return row['Low'] * 0.98
        return float('nan')
    def generate_trading_plan(t, h, ht, kc, hm): return ""
    def generate_recent_sessions_message(t, h, n): return ""
    def gui_tin_nhan_telegram(m): return None

# ── PORTFOLIO FILE (dùng chung với GUI) ─────────────────────────────
PORTFOLIO_FILE = os.path.join(ROOT, "portfolio.json")

# Cache được quản lý trong data_fetcher.py (vnstock + yfinance fallback)

app = FastAPI(title="Thợ Săn Điểm Vào API", version="1.0.0")

# ── CORS — cho phép frontend truy cập ───────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global exception handler — trả về lỗi chi tiết ──────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"[ERROR] {request.url}\n{tb}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# ── Static files (serve PWA) ────────────────────────────────────────
WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))
if os.path.exists(WEB_DIR):
    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")


# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════
def _load_portfolio():
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_portfolio(data):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_float(val, default=0.0):
    """Convert numpy/pandas scalar to Python float safely."""
    try:
        v = float(val)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return default


def _filter_levels(levels_series, threshold=0.04):
    """Tự triển khai filter_levels - tránh lỗi .dropna() trên list."""
    if isinstance(levels_series, pd.Series):
        vals = sorted(levels_series.dropna().unique().tolist())
    else:
        vals = sorted([v for v in levels_series if v and not math.isnan(float(v))])
    filtered = []
    for lv in vals:
        if not filtered or abs(lv - filtered[-1]) / (filtered[-1] + 1e-9) > threshold:
            filtered.append(float(lv))
    return filtered


def _analyze_sup_res(hist, window=10):
    """Tự triển khai analyze_support_resistance."""
    lo = hist['Low']
    hi = hist['High']
    local_mins = lo[lo == lo.rolling(window=window, center=True).min()]
    local_maxs = hi[hi == hi.rolling(window=window, center=True).max()]
    sup = _filter_levels(local_mins, 0.04)
    res = _filter_levels(local_maxs, 0.04)
    min_abs = float(lo.min())
    max_abs = float(hi.max())
    if not any(abs(lv - min_abs) / (min_abs + 1e-9) < 0.02 for lv in sup):
        sup.append(min_abs)
    if not any(abs(lv - max_abs) / (max_abs + 1e-9) < 0.02 for lv in res):
        res.append(max_abs)
    return sup, res, min_abs, max_abs


def _calc_rsi(hist, period=14):
    delta = hist["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / (loss.replace(0, np.nan).fillna(1e-9))
    val   = (100 - 100 / (1 + rs)).iloc[-1]
    return _safe_float(val, 50.0)


def _calc_macd(hist, fast=12, slow=26, signal=9):
    close    = hist["Close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd     = ema_fast - ema_slow
    sig      = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - sig
    return {
        "macd":           _safe_float(macd.iloc[-1]),
        "signal":         _safe_float(sig.iloc[-1]),
        "histogram":      _safe_float(histogram.iloc[-1]),
        "prev_histogram": _safe_float(histogram.iloc[-2] if len(histogram) >= 2 else 0),
    }


def _calc_bb(hist, period=20, std=2):
    close  = hist["Close"]
    mid    = close.rolling(period).mean()
    sd     = close.rolling(period).std()
    upper  = mid + std * sd
    lower  = mid - std * sd
    last_c = _safe_float(close.iloc[-1])
    u = _safe_float(upper.iloc[-1], last_c)
    l = _safe_float(lower.iloc[-1], last_c)
    m = _safe_float(mid.iloc[-1],   last_c)
    pct_b  = (last_c - l) / (u - l + 1e-9)
    return {"upper": round(u, 2), "middle": round(m, 2), "lower": round(l, 2), "pct_b": round(pct_b, 4)}


def _determine_signal(at_sup, at_res, vol_surge, hammer, close, open_price):
    if   at_sup and hammer:                              return "MUA THĂM DÒ",  "green"
    elif at_sup and vol_surge and close < open_price:    return "KHÔNG MUA",    "red"
    elif at_sup:                                         return "THEO DÕI",     "gold"
    elif at_res and vol_surge:                           return "BREAKOUT",     "green"
    elif at_res:                                         return "BULL TRAP?",   "orange"
    else:                                                return "QUAN SÁT",    "gray"


# ═══════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"status": "ok", "message": "🏹 Thợ Săn Điểm Vào API đang hoạt động"}


# ── 1. PHÂN TÍCH CỔ PHIẾU ───────────────────────────────────────────
@app.get("/api/analyze/{ticker}")
def analyze(
    ticker: str,
    date_from: str = Query(default=None, description="DD/MM/YYYY"),
    date_to:   str = Query(default=None, description="DD/MM/YYYY"),
):
    raw = ticker.upper().strip()
    today   = datetime.now()
    six_ago = today - timedelta(days=182)

    try:
        dt_from = datetime.strptime(date_from, "%d/%m/%Y") if date_from else six_ago
        dt_to   = datetime.strptime(date_to,   "%d/%m/%Y") if date_to   else today
    except ValueError:
        raise HTTPException(400, "Định dạng ngày sai — dùng DD/MM/YYYY")

    if dt_from >= dt_to:
        raise HTTPException(400, "Ngày bắt đầu phải trước ngày kết thúc")

    try:
        hist = fetch_history(raw, dt_from, dt_to)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Lỗi lấy dữ liệu: {e}")

    if hist.empty:
        raise HTTPException(404, f"Không có dữ liệu cho '{raw}' trong khoảng này")

    close     = _safe_float(hist["Close"].iloc[-1])
    open_last = _safe_float(hist["Open"].iloc[-1])
    high_last = _safe_float(hist["High"].iloc[-1])
    low_last  = _safe_float(hist["Low"].iloc[-1])
    vol_last  = int(hist["Volume"].iloc[-1])

    # Phân tích HT/KC — dùng bản tự triển khai an toàn hơn
    sup, res, min_a, max_a = _analyze_sup_res(hist)
    ht = max([s for s in sup if s <= close], default=min_a)
    kc = min([r for r in res if r >= close], default=max_a)

    # Tín hiệu
    hammers   = hist.apply(is_hammer, axis=1)
    avg_vol   = float(hist["Volume"].rolling(20).mean().iloc[-1])
    vol_surge = vol_last >= 1.5 * avg_vol
    hammer    = bool(hammers.notna().iloc[-1])
    at_sup    = (close - ht) / ht <= 0.03 if ht else False
    at_res    = close >= kc and (close - kc) / kc <= 0.03 if kc else False

    sig_name, sig_color = _determine_signal(at_sup, at_res, vol_surge, hammer, close, open_last)

    # Các chỉ số kỹ thuật
    rr_risk   = ht - ht * 0.95
    rr        = (kc * 0.98 - ht) / rr_risk if rr_risk > 0 else 0

    rsi_val   = _calc_rsi(hist)
    macd_data = _calc_macd(hist)
    bb_data   = _calc_bb(hist)

    # Phần trăm thay đổi 30 phiên gần nhất
    recent = hist[["Open", "High", "Low", "Close", "Volume"]].tail(30).copy()
    recent["pct_change"] = recent["Close"].pct_change() * 100
    sessions = []
    for idx, row in list(recent.iterrows())[::-1]:
        try:
            date_str = idx.strftime("%d/%m/%Y")
        except Exception:
            date_str = str(idx)[:10]
        pct = _safe_float(row["pct_change"], None) if not pd.isna(row["pct_change"]) else None
        sessions.append({
            "date":   date_str,
            "open":   round(_safe_float(row["Open"]),  2),
            "high":   round(_safe_float(row["High"]),  2),
            "low":    round(_safe_float(row["Low"]),   2),
            "close":  round(_safe_float(row["Close"]), 2),
            "volume": int(row["Volume"]),
            "pct":    round(pct, 2) if pct is not None else None,
        })

    # Trading plan text
    try:
        trading_plan = generate_trading_plan(raw, hist, ht, kc, hammers)
    except Exception:
        trading_plan = ""

    return {
        "ticker":    raw,
        "date_from": dt_from.strftime("%d/%m/%Y"),
        "date_to":   dt_to.strftime("%d/%m/%Y"),
        "sessions":  len(hist),
        # Giá
        "close":     round(close, 2),
        "open":      round(open_last, 2),
        "high":      round(high_last, 2),
        "low":       round(low_last, 2),
        "volume":    vol_last,
        "avg_vol20": round(avg_vol, 0),
        "vol_ratio": round(vol_last / avg_vol, 2) if avg_vol else 0,
        # HT/KC
        "support":   round(ht, 2),
        "resistance":round(kc, 2),
        "support_levels":    [round(s, 2) for s in sorted(sup, reverse=True)],
        "resistance_levels": [round(r, 2) for r in sorted(res)],
        # Tín hiệu
        "signal":       sig_name,
        "signal_color": sig_color,
        "at_support":   at_sup,
        "at_resistance":at_res,
        "vol_surge":    vol_surge,
        "hammer":       hammer,
        # Trading plan
        "entry_zone":   round(ht, 2),
        "stop_loss":    round(ht * 0.95, 2),
        "take_profit":  round(kc * 0.98, 2),
        "rr_ratio":     round(rr, 2),
        # Chỉ số kỹ thuật
        "rsi":          rsi_val,
        "macd":         macd_data,
        "bollinger":    bb_data,
        # Dữ liệu bảng phiên
        "recent_sessions": sessions,
        # Text plan
        "trading_plan": trading_plan,
    }


# ── 2. DỮ LIỆU BIỂU ĐỒ (OHLCV) ──────────────────────────────────────
@app.get("/api/chart/{ticker}")
def chart_data(
    ticker: str,
    date_from: str = Query(default=None),
    date_to:   str = Query(default=None),
):
    raw = ticker.upper().strip()
    today   = datetime.now()
    six_ago = today - timedelta(days=182)

    dt_from = datetime.strptime(date_from, "%d/%m/%Y") if date_from else six_ago
    dt_to   = datetime.strptime(date_to,   "%d/%m/%Y") if date_to   else today

    try:
        hist = fetch_history(raw, dt_from, dt_to)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if hist.empty:
        raise HTTPException(404, "Không có dữ liệu")

    candles = []
    for idx, row in hist.iterrows():
        try:
            ts = int(pd.Timestamp(idx).timestamp())
        except Exception:
            continue
        candles.append({
            "time":   ts,
            "open":   round(_safe_float(row["Open"]),   2),
            "high":   round(_safe_float(row["High"]),   2),
            "low":    round(_safe_float(row["Low"]),    2),
            "close":  round(_safe_float(row["Close"]),  2),
            "volume": int(row["Volume"]),
        })
    return {"ticker": raw, "candles": candles}


# ── 3. THÔNG TIN CÔNG TY (vnstock) ──────────────────────────────────
@app.get("/api/company/{ticker}")
def get_company_info(ticker: str):
    """
    Lấy tên công ty, sàn giao dịch, ngành từ vnstock (VCI source).
    - Tên công ty: listing.symbols_by_exchange() → organ_name
    - Ngành: company.overview() → icb_name2 / icb_name3
    """
    raw = ticker.upper().strip()
    info: dict = {"ticker": raw, "company_name": "", "exchange": "", "industry": ""}
    try:
        from vnstock import Vnstock
        stock = Vnstock().stock(symbol=raw, source="VCI")

        # Lấy tên công ty và sàn từ listing
        try:
            listing_df = stock.listing.symbols_by_exchange()
            row = listing_df[listing_df["symbol"] == raw]
            if not row.empty:
                info["company_name"] = str(row.iloc[0].get("organ_name", "")).strip()
                info["exchange"]     = str(row.iloc[0].get("exchange", "")).strip()
        except Exception as e:
            logger.warning(f"[company] listing error {raw}: {e}")

        # Lấy ngành từ company overview
        try:
            ov = stock.company.overview()
            if ov is not None and not ov.empty:
                r = ov.iloc[0]
                industry = str(r.get("icb_name3") or r.get("icb_name2") or "").strip()
                if industry and industry.lower() not in ("nan", "none", ""):
                    info["industry"] = industry
        except Exception as e:
            logger.warning(f"[company] overview error {raw}: {e}")

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"[company] error {raw}: {e}")
    return info


# ── 4. GIÁ HIỆN TẠI (dùng cho portfolio localStorage) ───────────────
@app.get("/api/price/{ticker}")
def get_price(ticker: str):
    """Lấy giá 1 mã (cache 5 phút, vnstock primary → yfinance fallback)."""
    raw = ticker.upper().strip()
    price = fetch_latest_price(raw)
    if price is None:
        raise HTTPException(404, f"Không có dữ liệu cho '{raw}'")
    return {"ticker": raw, "price": price}


@app.get("/api/prices")
def get_prices_batch(tickers: str = Query(..., description="Danh sách mã, cách nhau bằng dấu phẩy")):
    """
    Lấy giá nhiều mã cùng lúc.
    Dùng vnstock (TCBS) làm primary, yfinance batch làm fallback.
    VD: /api/prices?tickers=VNM,VCB,HPG
    """
    raws = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not raws:
        raise HTTPException(400, "Thiếu tham số tickers")
    return fetch_latest_prices_batch(raws)


# ── 5. PORTFOLIO CRUD ──────────────────────────────────────────────
@app.get("/api/portfolio")
def get_portfolio():
    return _load_portfolio()


class PortfolioItem(BaseModel):
    ticker:      str
    entry_date:  str
    entry_price: float
    quantity:    int
    note:        str = ""


@app.post("/api/portfolio")
def add_portfolio(item: PortfolioItem):
    data = _load_portfolio()
    data.append({
        "ticker":      item.ticker.upper().strip(),
        "entry_date":  item.entry_date,
        "entry_price": item.entry_price,
        "quantity":    item.quantity,
        "note":        item.note,
    })
    _save_portfolio(data)
    return {"ok": True, "total": len(data)}


@app.delete("/api/portfolio/{index}")
def delete_portfolio(index: int):
    data = _load_portfolio()
    if index < 0 or index >= len(data):
        raise HTTPException(404, "Không tìm thấy vị thế")
    data.pop(index)
    _save_portfolio(data)
    return {"ok": True, "total": len(data)}


# ── 6. CẬP NHẬT GIÁ PORTFOLIO ────────────────────────────────────────
@app.get("/api/portfolio/refresh")
def refresh_portfolio():
    """Dùng batch fetch để giảm số lượng request xuống tối thiểu."""
    data = _load_portfolio()
    if not data:
        return []

    # Batch fetch tất cả giá cùng lúc
    tickers = [pos["ticker"] for pos in data]
    prices  = fetch_latest_prices_batch(tickers)

    results = []
    for i, pos in enumerate(data):
        close = prices.get(pos["ticker"])
        pnl   = (close - pos["entry_price"]) / pos["entry_price"] * 100 if close else None
        results.append({
            "index":         i,
            "ticker":        pos["ticker"],
            "entry_date":    pos["entry_date"],
            "entry_price":   pos["entry_price"],
            "quantity":      pos["quantity"],
            "note":          pos.get("note", ""),
            "current_price": round(close, 2) if close else 0.0,
            "pnl_pct":       round(pnl, 2) if pnl is not None else None,
            "pnl_amount":    round((close - pos["entry_price"]) * pos["quantity"], 0) if pnl is not None else None,
        })
    return results


# ── 7. GỬI TELEGRAM ──────────────────────────────────────────────────
@app.post("/api/telegram/{ticker}")
def send_telegram(ticker: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(400, "Chưa cấu hình Telegram")
    raw = ticker.upper().strip()
    try:
        today = datetime.now()
        hist = fetch_history(raw, today - timedelta(days=182), today)
        if hist.empty:
            raise HTTPException(404, "Không có dữ liệu")
        sup, res, min_a, max_a = _analyze_sup_res(hist)
        close = _safe_float(hist["Close"].iloc[-1])
        ht    = max([s for s in sup if s <= close], default=min_a)
        kc    = min([r for r in res if r >= close], default=max_a)
        hammers = hist.apply(is_hammer, axis=1)
        sessions_msg = generate_recent_sessions_message(raw, hist, 10)
        plan_msg     = generate_trading_plan(raw, hist, ht, kc, hammers)
        gui_tin_nhan_telegram(sessions_msg)
        gui_tin_nhan_telegram(plan_msg)
        return {"ok": True, "message": "Đã gửi Telegram thành công"}
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR telegram] {tb}")
        raise HTTPException(500, f"Lỗi: {e}")
