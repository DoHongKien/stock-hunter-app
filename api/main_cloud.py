"""
Thợ Săn Điểm Vào — FastAPI Backend (Cloud-ready)
Standalone version: không phụ thuộc thư mục ngoài.
"""
import os, sys, math, traceback, json, time
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pandas as pd
import numpy as np
import requests as http_requests

# Data source: vnstock v3 (VCI)
from api.data_fetcher import fetch_history, fetch_latest_price, fetch_latest_prices_batch

from api.core import (
    analyze_support_resistance, is_hammer,
    calc_rsi, calc_macd, calc_bb,
    determine_signal, generate_trading_plan,
    generate_recent_sessions_message, safe_float,
)

# ── CONFIG ───────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")

# Portfolio lưu trong /tmp (ephemeral trên cloud, OK cho demo)
# Để persistence thật: dùng Render Disk hoặc DB
PORTFOLIO_FILE = os.getenv("PORTFOLIO_FILE",
    os.path.join(os.path.dirname(__file__), "..", "portfolio.json"))

# ── APP ───────────────────────────────────────────────────────────────
app = FastAPI(title="Thợ Săn Điểm Vào API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

@app.exception_handler(Exception)
async def _err(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"[ERROR] {request.url}\n{tb}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# Serve PWA static files
_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web"))
if os.path.exists(_WEB):
    app.mount("/app", StaticFiles(directory=_WEB, html=True), name="web")

# Cache được quản lý trong data_fetcher.py (vnstock VCI, TTL 15/5 phút)
# TTL: 15 phút cho history, 5 phút cho giá đơn lẻ

# ── PORTFOLIO HELPERS ─────────────────────────────────────────────────
def _load_pf():
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_pf(data):
    try:
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Could not save portfolio: {e}")

# ── FETCH HISTORY ────────────────────────────────────────────────────
def _get_hist(ticker: str, dt_from: datetime, dt_to: datetime):
    """Wrapper tiện dụng: gọi fetch_history và raise 404 nếu không có dữ liệu."""
    try:
        return fetch_history(ticker, dt_from, dt_to)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Lỗi lấy dữ liệu: {e}")

# ── TELEGRAM ──────────────────────────────────────────────────────────
def _send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        http_requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"[WARN] Telegram error: {e}")

# ══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════
@app.get("/")
def root():
    return {"status": "ok", "message": "🏹 Thợ Săn Điểm Vào API"}

@app.get("/api/analyze/{ticker}")
def analyze(
    ticker: str,
    date_from: str = Query(default=None),
    date_to:   str = Query(default=None),
):
    raw   = ticker.upper().strip()
    today = datetime.now()

    try:
        dt_from = datetime.strptime(date_from, "%d/%m/%Y") if date_from else today - timedelta(days=182)
        dt_to   = datetime.strptime(date_to,   "%d/%m/%Y") if date_to   else today
    except ValueError:
        raise HTTPException(400, "Định dạng ngày sai — dùng DD/MM/YYYY")

    hist = _get_hist(raw, dt_from, dt_to)

    close     = safe_float(hist["Close"].iloc[-1])
    open_last = safe_float(hist["Open"].iloc[-1])
    high_last = safe_float(hist["High"].iloc[-1])
    low_last  = safe_float(hist["Low"].iloc[-1])
    vol_last  = int(hist["Volume"].iloc[-1])
    avg_vol   = safe_float(hist["Volume"].rolling(20).mean().iloc[-1], 1)

    sup, res, min_a, max_a = analyze_support_resistance(hist)
    ht = max([s for s in sup if s <= close], default=min_a)
    kc = min([r for r in res if r >= close], default=max_a)

    hammers   = hist.apply(is_hammer, axis=1)
    vol_surge = vol_last >= 1.5 * avg_vol
    hammer    = bool(hammers.notna().iloc[-1])
    at_sup    = (close - ht) / (ht + 1e-9) <= 0.03
    at_res    = close >= kc and (close - kc) / (kc + 1e-9) <= 0.03

    sig_name, sig_color = determine_signal(at_sup, at_res, vol_surge, hammer, close, open_last)

    rr_risk = ht - ht * 0.95
    rr      = (kc * 0.98 - ht) / rr_risk if rr_risk > 0 else 0

    rsi_val   = calc_rsi(hist)
    macd_data = calc_macd(hist)
    bb_data   = calc_bb(hist)

    # Recent sessions
    recent = hist[["Open","High","Low","Close","Volume"]].tail(30).copy()
    recent["pct_change"] = recent["Close"].pct_change() * 100
    sessions = []
    for idx, row in list(recent.iterrows())[::-1]:
        try:    date_str = idx.strftime("%d/%m/%Y")
        except: date_str = str(idx)[:10]
        pct = None if pd.isna(row["pct_change"]) else round(safe_float(row["pct_change"]), 2)
        sessions.append({
            "date":   date_str,
            "open":   round(safe_float(row["Open"]),  2),
            "high":   round(safe_float(row["High"]),  2),
            "low":    round(safe_float(row["Low"]),   2),
            "close":  round(safe_float(row["Close"]), 2),
            "volume": int(row["Volume"]),
            "pct":    pct,
        })

    try:    trading_plan = generate_trading_plan(raw, hist, ht, kc, hammers)
    except: trading_plan = ""

    return {
        "ticker":    raw,
        "date_from": dt_from.strftime("%d/%m/%Y"),
        "date_to":   dt_to.strftime("%d/%m/%Y"),
        "sessions":  len(hist),
        "close":     round(close, 2),
        "open":      round(open_last, 2),
        "high":      round(high_last, 2),
        "low":       round(low_last, 2),
        "volume":    vol_last,
        "avg_vol20": round(avg_vol, 0),
        "vol_ratio": round(vol_last / avg_vol, 2) if avg_vol else 0,
        "support":   round(ht, 2),
        "resistance":round(kc, 2),
        "support_levels":    [round(s, 2) for s in sorted(sup, reverse=True)],
        "resistance_levels": [round(r, 2) for r in sorted(res)],
        "signal":       sig_name,
        "signal_color": sig_color,
        "at_support":   at_sup,
        "at_resistance":at_res,
        "vol_surge":    vol_surge,
        "hammer":       hammer,
        "entry_zone":   round(ht, 2),
        "stop_loss":    round(ht * 0.95, 2),
        "take_profit":  round(kc * 0.98, 2),
        "rr_ratio":     round(rr, 2),
        "rsi":          rsi_val,
        "macd":         macd_data,
        "bollinger":    bb_data,
        "recent_sessions": sessions,
        "trading_plan": trading_plan,
    }


@app.get("/api/chart/{ticker}")
def chart_data(
    ticker: str,
    date_from: str = Query(default=None),
    date_to:   str = Query(default=None),
):
    raw   = ticker.upper().strip()
    today = datetime.now()
    dt_from = datetime.strptime(date_from, "%d/%m/%Y") if date_from else today - timedelta(days=182)
    dt_to   = datetime.strptime(date_to,   "%d/%m/%Y") if date_to   else today

    hist = _get_hist(raw, dt_from, dt_to)
    candles = []
    for idx, row in hist.iterrows():
        try:    ts = int(pd.Timestamp(idx).timestamp())
        except: continue
        candles.append({
            "time":   ts,
            "open":   round(safe_float(row["Open"]),  2),
            "high":   round(safe_float(row["High"]),  2),
            "low":    round(safe_float(row["Low"]),   2),
            "close":  round(safe_float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })
    return {"ticker": raw, "candles": candles}


@app.get("/api/price/{ticker}")
def get_price(ticker: str):
    """Lấy giá 1 mã (cache 5 phút, vnstock VCI)."""
    raw = ticker.upper().strip()
    price = fetch_latest_price(raw)
    if price is None:
        raise HTTPException(404, f"Không có dữ liệu cho '{raw}'")
    return {"ticker": raw, "price": price}


@app.get("/api/prices")
def get_prices_batch(tickers: str = Query(..., description="Danh sách mã, cách nhau bằng dấu phẩy")):
    """
    Lấy giá nhiều mã cùng lúc.
    Dùng vnstock (VCI) để lấy giá hàng loạt.
    VD: /api/prices?tickers=VNM,VCB,HPG
    """
    raws = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not raws:
        raise HTTPException(400, "Thiếu tham số tickers")
    return fetch_latest_prices_batch(raws)


@app.get("/api/portfolio")
def get_portfolio():
    return _load_pf()


class PortfolioItem(BaseModel):
    ticker:      str
    entry_date:  str
    entry_price: float
    quantity:    int
    note:        str = ""


@app.post("/api/portfolio")
def add_portfolio(item: PortfolioItem):
    data = _load_pf()
    data.append({
        "ticker":      item.ticker.upper().strip(),
        "entry_date":  item.entry_date,
        "entry_price": item.entry_price,
        "quantity":    item.quantity,
        "note":        item.note,
    })
    _save_pf(data)
    return {"ok": True, "total": len(data)}


@app.delete("/api/portfolio/{index}")
def delete_portfolio(index: int):
    data = _load_pf()
    if index < 0 or index >= len(data):
        raise HTTPException(404, "Không tìm thấy vị thế")
    data.pop(index)
    _save_pf(data)
    return {"ok": True, "total": len(data)}


@app.get("/api/portfolio/refresh")
def refresh_portfolio():
    """Dùng batch fetch để giảm số lượng request xuống tối thiểu."""
    data = _load_pf()
    if not data:
        return []

    tickers = [pos["ticker"] for pos in data]
    prices  = fetch_latest_prices_batch(tickers)

    results = []
    for i, pos in enumerate(data):
        from api.core import safe_float
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


@app.post("/api/telegram/{ticker}")
def send_telegram(ticker: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(400, "Chưa cấu hình Telegram (set env vars)")
    raw   = ticker.upper().strip()
    today = datetime.now()
    hist  = _get_hist(raw, today - timedelta(days=182), today)
    sup, res, min_a, max_a = analyze_support_resistance(hist)
    close = safe_float(hist["Close"].iloc[-1])
    ht    = max([s for s in sup if s <= close], default=min_a)
    kc    = min([r for r in res if r >= close], default=max_a)
    hm    = hist.apply(is_hammer, axis=1)
    _send_telegram(generate_recent_sessions_message(raw, hist, 10))
    _send_telegram(generate_trading_plan(raw, hist, ht, kc, hm))
    return {"ok": True}
