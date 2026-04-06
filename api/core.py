"""
Core phân tích kỹ thuật — standalone, không phụ thuộc thư mục ngoài.
"""
import math
import pandas as pd
import numpy as np


# ── SUPPORT / RESISTANCE ────────────────────────────────────────────
def filter_levels(levels_series, threshold=0.04):
    if isinstance(levels_series, pd.Series):
        vals = sorted(levels_series.dropna().unique().tolist())
    else:
        vals = sorted([v for v in levels_series if v and not math.isnan(float(v))])
    filtered = []
    for lv in vals:
        if not filtered or abs(lv - filtered[-1]) / (filtered[-1] + 1e-9) > threshold:
            filtered.append(float(lv))
    return filtered


def analyze_support_resistance(hist, window=10):
    lo = hist['Low']
    hi = hist['High']
    local_mins = lo[lo == lo.rolling(window=window, center=True).min()]
    local_maxs = hi[hi == hi.rolling(window=window, center=True).max()]
    sup = filter_levels(local_mins, 0.04)
    res = filter_levels(local_maxs, 0.04)
    min_abs = float(lo.min())
    max_abs = float(hi.max())
    if not any(abs(lv - min_abs) / (min_abs + 1e-9) < 0.02 for lv in sup):
        sup.append(min_abs)
    if not any(abs(lv - max_abs) / (max_abs + 1e-9) < 0.02 for lv in res):
        res.append(max_abs)
    return sup, res, min_abs, max_abs


# ── CANDLE PATTERNS ──────────────────────────────────────────────────
def is_hammer(row):
    body = abs(row['Close'] - row['Open'])
    lower = min(row['Open'], row['Close']) - row['Low']
    upper = row['High'] - max(row['Open'], row['Close'])
    if body > 0 and lower > 2 * body and upper < body:
        return row['Low'] * 0.98
    return float('nan')


# ── TECHNICAL INDICATORS ────────────────────────────────────────────
def safe_float(val, default=0.0):
    try:
        v = float(val)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return default


def calc_rsi(hist, period=14):
    delta = hist["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / (loss.replace(0, np.nan).fillna(1e-9))
    val   = (100 - 100 / (1 + rs)).iloc[-1]
    return safe_float(val, 50.0)


def calc_macd(hist, fast=12, slow=26, signal=9):
    close     = hist["Close"]
    ema_fast  = close.ewm(span=fast, adjust=False).mean()
    ema_slow  = close.ewm(span=slow, adjust=False).mean()
    macd      = ema_fast - ema_slow
    sig       = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - sig
    return {
        "macd":           safe_float(macd.iloc[-1]),
        "signal":         safe_float(sig.iloc[-1]),
        "histogram":      safe_float(histogram.iloc[-1]),
        "prev_histogram": safe_float(histogram.iloc[-2] if len(histogram) >= 2 else 0),
    }


def calc_bb(hist, period=20, std=2):
    close  = hist["Close"]
    mid    = close.rolling(period).mean()
    sd     = close.rolling(period).std()
    upper  = mid + std * sd
    lower  = mid - std * sd
    last_c = safe_float(close.iloc[-1])
    u = safe_float(upper.iloc[-1], last_c)
    l = safe_float(lower.iloc[-1], last_c)
    m = safe_float(mid.iloc[-1],   last_c)
    pct_b = (last_c - l) / (u - l + 1e-9)
    return {"upper": round(u, 2), "middle": round(m, 2), "lower": round(l, 2), "pct_b": round(pct_b, 4)}


# ── SIGNAL ──────────────────────────────────────────────────────────
def determine_signal(at_sup, at_res, vol_surge, hammer, close, open_price):
    if   at_sup and hammer:                              return "MUA THĂM DÒ",  "green"
    elif at_sup and vol_surge and close < open_price:    return "KHÔNG MUA",    "red"
    elif at_sup:                                         return "THEO DÕI",     "gold"
    elif at_res and vol_surge:                           return "BREAKOUT",     "green"
    elif at_res:                                         return "BULL TRAP?",   "orange"
    else:                                                return "QUAN SÁT",    "gray"


# ── TRADING PLAN TEXT ────────────────────────────────────────────────
def generate_trading_plan(raw_ticker, hist, ht, kc, hammer_markers):
    latest_close = hist['Close'].iloc[-1]
    avg_vol_20   = hist['Volume'].rolling(20).mean().iloc[-1]
    last_vol     = hist['Volume'].iloc[-1]
    vol_dot_bien = last_vol >= 1.5 * avg_vol_20
    co_nen_bua   = hammer_markers.notna().iloc[-1]

    msg  = f"🔭 <b>BÁO CÁO DÒ ĐƯỜNG MÃ: {raw_ticker}</b>\n"
    msg += "=" * 35 + "\n"
    msg += f"Giá hiện tại: <b>{latest_close:,.0f} VNĐ</b>\n\n"
    msg += f"📉 Hỗ trợ gần nhất: {ht:,.0f} VNĐ\n"
    msg += f"📈 Kháng cự gần nhất: {kc:,.0f} VNĐ\n"

    if co_nen_bua:
        msg += f"\n🔥 <b>[TÍN HIỆU]: ĐÃ PHÁT HIỆN NẾN BÚA!</b>\n"
    if vol_dot_bien:
        msg += f"💥 <b>[DÒNG TIỀN ĐỘT BIẾN]: KL gấp 1.5× TB20.</b>\n"

    msg += "\n💡 <b>LỜI KHUYÊN:</b>\n"
    if (latest_close - ht) / ht <= 0.03:
        if co_nen_bua:
            msg += "🟢 <b>MUA THĂM DÒ 30%</b>\n"
        elif vol_dot_bien and latest_close < hist['Open'].iloc[-1]:
            msg += "🔴 <b>KHÔNG BẮT DAO RƠI</b>\n"
        else:
            msg += "🟡 <b>ĐƯA VÀO TẦM NGẮM</b>\n"
    elif latest_close >= kc and (latest_close - kc) / kc <= 0.03:
        msg += "🚀 <b>BREAKOUT</b>\n" if vol_dot_bien else "⚠️ <b>CẨN THẬN BULL TRAP</b>\n"
    else:
        msg += "⏸️ <b>NO ACTION</b>\n"

    msg += f"\n🎯 <b>KẾ HOẠCH:</b>\n"
    msg += f"👉 Entry: {ht:,.0f}–{ht*1.02:,.0f} VNĐ\n"
    msg += f"✂️ Stop Loss: {ht*0.95:,.0f} VNĐ\n"
    msg += f"💰 Take Profit: {kc*0.98:,.0f} VNĐ\n"

    rr_risk   = ht - ht * 0.95
    rr_reward = kc * 0.98 - ht
    rr        = rr_reward / rr_risk if rr_risk > 0 else 0
    msg += f"⚖️ R/R: 1:{rr:.1f} {'(Kèo thơm!)' if rr >= 2 else '(Kèo xấu!)'}\n"
    return msg


def generate_recent_sessions_message(raw_ticker, hist, n=10):
    df = hist[['Open', 'High', 'Low', 'Close', 'Volume']].tail(n).copy()
    df['%Change'] = df['Close'].pct_change() * 100
    try:
        latest_date = df.index[-1].strftime("%d/%m/%Y")
    except Exception:
        latest_date = str(df.index[-1])[:10]

    msg  = f"📋 <b>{n} PHIÊN GẦN NHẤT — {raw_ticker}</b>  <i>(đến {latest_date})</i>\n"
    msg += "─" * 30 + "\n\n"

    for idx, row in list(df.iterrows())[::-1]:
        try:
            date_str = idx.strftime("%d/%m/%Y")
        except Exception:
            date_str = str(idx)[:10]
        pct = row["%Change"]
        if math.isnan(pct):
            chg_txt, emoji = "—", "⚪"
        elif pct > 0:
            chg_txt, emoji = f"▲ {pct:.2f}%", "🟢"
        elif pct < 0:
            chg_txt, emoji = f"▼ {abs(pct):.2f}%", "🔴"
        else:
            chg_txt, emoji = "→ 0.00%", "⚪"
        vol_m = row["Volume"] / 1_000_000
        msg += f"{emoji} <b>{date_str}</b>  {chg_txt}  │ Đóng: <b>{row['Close']:,.0f}</b>\n"
        msg += f"   Mở: {row['Open']:,.0f} │ Cao: {row['High']:,.0f} │ Thấp: {row['Low']:,.0f} │ KL: {vol_m:.2f}M\n\n"
    return msg.rstrip("\n")
