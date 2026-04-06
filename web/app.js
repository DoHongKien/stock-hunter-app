/* ═══════════════════════════════════════════════════════════════
   THỢ SĂN ĐIỂM VÀO — PWA App Logic
   ═══════════════════════════════════════════════════════════════ */

// ── SERVICE WORKER REGISTRATION ─────────────────────────────────
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}

// ── CONFIG ──────────────────────────────────────────────────────
const CFG_KEY = "stockhunter_api";
let API_BASE = localStorage.getItem(CFG_KEY) || "http://localhost:8000";

// ── STATE ───────────────────────────────────────────────────────
let currentTicker  = null;
let currentData    = null;
let lwChart        = null;
let seriesCandle   = null;
let seriesLine     = null;
let currentSeries  = null;
let deferredPrompt = null;

// ── PWA INSTALL PROMPT ───────────────────────────────────────────
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  document.getElementById("btn-install").classList.remove("hidden");
});
function installPWA() {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  deferredPrompt.userChoice.then(() => { deferredPrompt = null; });
}

// ── TOAST ────────────────────────────────────────────────────────
let _toastTimer = null;
function showToast(msg, ms = 2500) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove("show"), ms);
}

// ── TAB NAVIGATION ───────────────────────────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll(".tab-page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  btn.classList.add("active");

  if (name === "portfolio") loadPortfolio();
  if (name === "settings") loadSettings();
}

// ── DATE HELPERS ─────────────────────────────────────────────────
function fmtDateInput(d) {
  return d.toISOString().split("T")[0]; // YYYY-MM-DD for <input type=date>
}
function inputToAPI(v) {
  // Convert YYYY-MM-DD → DD/MM/YYYY
  if (!v) return null;
  const [y, m, d] = v.split("-");
  return `${d}/${m}/${y}`;
}
function setRange(days) {
  const to   = new Date();
  const from = new Date(to.getTime() - days * 86400000);
  document.getElementById("inp-from").value = fmtDateInput(from);
  document.getElementById("inp-to").value   = fmtDateInput(to);
}
function initDates() {
  const to   = new Date();
  const from = new Date(to.getTime() - 182 * 86400000);
  document.getElementById("inp-to").value   = fmtDateInput(to);
  document.getElementById("inp-from").value = fmtDateInput(from);
  document.getElementById("pf-date").value  = fmtDateInput(to);
}

// ── FORMAT HELPERS ───────────────────────────────────────────────
function fmtPrice(v) {
  if (v == null || isNaN(v)) return "—";
  return new Intl.NumberFormat("vi-VN").format(Math.round(v));
}
function fmtPct(v, force=false) {
  if (v == null || isNaN(v)) return "—";
  const sign = v >= 0 ? "▲" : "▼";
  return `${sign} ${Math.abs(v).toFixed(2)}%`;
}
function fmtVol(v) {
  if (!v || isNaN(v)) return "—";
  if (v >= 1e6) return `${(v/1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v/1e3).toFixed(1)}K`;
  return v.toString();
}

// ── API CALL ─────────────────────────────────────────────────────
async function apiFetch(path, opts={}) {
  const r = await fetch(API_BASE + path, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

// ── CHECK API ────────────────────────────────────────────────────
async function checkApi() {
  const badge = document.getElementById("api-badge");
  try {
    const d = await apiFetch("/");
    badge.textContent = "API ✓";
    badge.className   = "badge badge-on";
    document.getElementById("info-api").textContent = API_BASE;
    return true;
  } catch {
    badge.textContent = "API ✗";
    badge.className   = "badge badge-off";
    return false;
  }
}

// ══════════════════════════════════════════════════════════════════
// ANALYZE TAB
// ══════════════════════════════════════════════════════════════════
async function doAnalyze() {
  const ticker = document.getElementById("inp-ticker").value.trim().toUpperCase();
  if (!ticker) { showToast("⚠️ Nhập mã cổ phiếu!"); return; }

  const dateFrom = inputToAPI(document.getElementById("inp-from").value);
  const dateTo   = inputToAPI(document.getElementById("inp-to").value);

  // Show loading
  document.getElementById("analyze-loading").classList.remove("hidden");
  document.getElementById("analyze-error").classList.add("hidden");
  document.getElementById("analyze-results").classList.add("hidden");
  document.getElementById("loading-ticker").textContent = ticker;
  document.getElementById("btn-analyze").disabled = true;

  try {
    // Build URL
    const params = new URLSearchParams();
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo)   params.set("date_to",   dateTo);

    const [data, chartData] = await Promise.all([
      apiFetch(`/api/analyze/${ticker}?${params}`),
      apiFetch(`/api/chart/${ticker}?${params}`),
    ]);

    currentTicker = ticker;
    currentData   = data;

    renderAnalysis(data);
    renderChart(chartData.candles, data);

    document.getElementById("analyze-results").classList.remove("hidden");
    document.getElementById("header-sub").textContent = `${ticker} · ${data.date_to}`;

    // Pre-fill quick-add
    document.getElementById("qa-price").value = Math.round(data.support);

  } catch (e) {
    const errEl = document.getElementById("analyze-error");
    errEl.textContent = `❌ ${e.message}`;
    errEl.classList.remove("hidden");
  } finally {
    document.getElementById("analyze-loading").classList.add("hidden");
    document.getElementById("btn-analyze").disabled = false;
  }
}

// ── Enter key ───────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("inp-ticker").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doAnalyze();
  });
  initDates();
  checkApi();
  document.getElementById("cfg-api").value = API_BASE;
});

// ── RENDER ANALYSIS ─────────────────────────────────────────────
function renderAnalysis(d) {
  // Signal
  const sigMap = {
    "MUA THĂM DÒ": { icon: "🟢", desc: "Giá về vùng HT + Nến Hammer. Cơ hội mua thăm dò 20-30% vị thế.", cls: "green" },
    "KHÔNG MUA":   { icon: "🔴", desc: "Chạm HT nhưng Vol xả mạnh. Không bắt dao rơi!", cls: "red" },
    "THEO DÕI":    { icon: "🟡", desc: "Giá gần HT nhưng chưa có xác nhận. Chờ thêm 1-2 phiên.", cls: "gold" },
    "BREAKOUT":    { icon: "🚀", desc: "Phá kháng cự với Volume đột biến. Momentum mạnh!", cls: "green" },
    "BULL TRAP?":  { icon: "⚠️", desc: "Vượt KC nhưng thiếu Volume. Cẩn thận bẫy tăng!", cls: "orange" },
    "QUAN SÁT":   { icon: "⏸", desc: "Giá ở vùng trung lập. Chờ giá về HT hoặc áp KC.", cls: "gray" },
  };
  const sig = sigMap[d.signal] || { icon: "📊", desc: d.signal, cls: "gray" };
  const banner = document.getElementById("signal-banner");
  banner.className = `signal-banner ${sig.cls}`;
  document.getElementById("signal-icon").textContent = sig.icon;
  document.getElementById("signal-name").textContent = d.signal;
  document.getElementById("signal-desc").textContent = sig.desc;

  // Prices
  setText("m-close", fmtPrice(d.close));
  // Pct change từ recent sessions
  const last2 = d.recent_sessions;
  const pct = last2 && last2.length >= 2 ? last2[0].pct : null;
  const pctEl = document.getElementById("m-pct");
  if (pct != null) {
    pctEl.textContent = fmtPct(pct);
    pctEl.className = `metric-sub ${pct >= 0 ? "green" : "red"}`;
  }

  setText("m-support", fmtPrice(d.support));
  const supPct = ((d.close - d.support) / d.support * 100).toFixed(2);
  setText("m-support-pct", `+${supPct}% từ HT`);

  setText("m-resistance", fmtPrice(d.resistance));
  const resPct = ((d.resistance - d.close) / d.close * 100).toFixed(2);
  setText("m-resistance-pct", `còn ${resPct}% tới KC`);

  const rrEl = document.getElementById("m-rr");
  rrEl.textContent = `1:${d.rr_ratio.toFixed(2)}`;
  rrEl.className = `metric-value ${d.rr_ratio >= 2 ? "green" : d.rr_ratio >= 1 ? "gold" : "red"}`;
  setText("m-rr-sub", d.rr_ratio >= 2 ? "✅ Kèo thơm" : "⚠️ Chờ điểm tốt hơn");

  // Indicators
  // RSI
  const rsi = d.rsi;
  setBar("rsi-bar", rsi, 100,
    rsi >= 70 ? "var(--red)" : rsi <= 30 ? "var(--green)" : rsi >= 60 ? "var(--gold)" : "var(--accent)");
  const rsiEl = document.getElementById("rsi-val");
  rsiEl.textContent = rsi.toFixed(1);
  rsiEl.className = `ind-val mono ${rsi >= 70 ? "red" : rsi <= 30 ? "green" : ""}`;

  // MACD histogram
  const mh = d.macd.histogram;
  const mhMax = 5; // approximate scale
  const mhPct = Math.min(Math.abs(mh) / mhMax * 100, 100);
  setBar("macd-bar", mhPct, 100, mh >= 0 ? "var(--green)" : "var(--red)");
  const macdEl = document.getElementById("macd-val");
  macdEl.textContent = mh.toFixed(3);
  macdEl.className = `ind-val mono ${mh > 0 ? "green" : mh < 0 ? "red" : ""}`;

  // BB %B
  const bb = d.bollinger.pct_b * 100;
  setBar("bb-bar", bb, 100,
    bb >= 80 ? "var(--red)" : bb <= 20 ? "var(--green)" : "var(--accent)");
  setText("bb-val", d.bollinger.pct_b.toFixed(2));
  document.getElementById("bb-val").className = `ind-val mono`;

  // Volume ratio
  const volR = d.vol_ratio * 50; // scale: 2x = full bar
  setBar("vol-bar", Math.min(volR, 100), 100,
    d.vol_surge ? "var(--orange)" : d.vol_ratio >= 0.8 ? "var(--accent)" : "var(--text-dim)");
  const volEl = document.getElementById("vol-val");
  volEl.textContent = `×${d.vol_ratio.toFixed(2)}`;
  volEl.className = `ind-val mono ${d.vol_surge ? "orange" : ""}`;

  // Plan
  setText("plan-entry",  fmtPrice(d.entry_zone));
  setText("plan-sl",     fmtPrice(d.stop_loss));
  setText("plan-tp",     fmtPrice(d.take_profit));
  const rrnote = document.getElementById("plan-rr-note");
  rrnote.textContent = d.rr_ratio >= 2
    ? `✅ R/R = 1:${d.rr_ratio.toFixed(2)} — Kèo đạt chuẩn, có thể vào lệnh`
    : `⚠️ R/R = 1:${d.rr_ratio.toFixed(2)} — Chưa đạt chuẩn 1:2, nên chờ`;
  rrnote.style.color = d.rr_ratio >= 2 ? "var(--green)" : "var(--gold)";

  // Sessions table
  const tbody = document.getElementById("sessions-body");
  tbody.innerHTML = "";
  (d.recent_sessions || []).slice(0, 15).forEach(s => {
    const tr = document.createElement("tr");
    const pct = s.pct;
    const cls = pct == null ? "flat" : pct > 0 ? "up" : pct < 0 ? "down" : "flat";
    const pctTxt = pct == null ? "—" : `${pct > 0 ? "▲" : pct < 0 ? "▼" : "→"} ${Math.abs(pct).toFixed(2)}%`;
    tr.innerHTML = `
      <td>${s.date}</td>
      <td class="${cls}">${fmtPrice(s.close)}</td>
      <td class="${cls}">${pctTxt}</td>
      <td>${fmtVol(s.volume)}</td>
    `;
    tbody.appendChild(tr);
  });
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}
function setBar(id, val, max, color) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.width  = `${Math.min(val / max * 100, 100)}%`;
  el.style.background = color;
}

// ── CHART ────────────────────────────────────────────────────────
let _chartType = "candlestick";
function setChartType(type, btn) {
  _chartType = type;
  document.querySelectorAll(".ct-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  if (!currentData || !lwChart) return;
  // Rebuild chart with current data
  if (seriesCandle) { try { lwChart.removeSeries(seriesCandle); } catch {} seriesCandle = null; }
  if (seriesLine)   { try { lwChart.removeSeries(seriesLine);   } catch {} seriesLine   = null; }
  addChartSeries(window._lastCandles || [], currentData);
}

function renderChart(candles, data) {
  window._lastCandles = candles;
  const container = document.getElementById("chart-container");
  container.innerHTML = "";

  lwChart = LightweightCharts.createChart(container, {
    width:  container.clientWidth,
    height: 300,
    layout: {
      background: { type: "solid", color: "#161b22" },
      textColor:  "#8b949e",
    },
    grid: {
      vertLines: { color: "#21262d" },
      horzLines: { color: "#21262d" },
    },
    rightPriceScale: { borderColor: "#30363d" },
    timeScale: {
      borderColor: "#30363d",
      timeVisible: true,
      secondsVisible: false,
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
  });

  addChartSeries(candles, data);

  // Resize observer
  const ro = new ResizeObserver(() => {
    lwChart.applyOptions({ width: container.clientWidth });
  });
  ro.observe(container);
}

function addChartSeries(candles, data) {
  if (_chartType === "candlestick") {
    seriesCandle = lwChart.addCandlestickSeries({
      upColor:          "#3fb950",
      downColor:        "#f85149",
      borderUpColor:    "#3fb950",
      borderDownColor:  "#f85149",
      wickUpColor:      "#3fb950",
      wickDownColor:    "#f85149",
    });
    // Convert timestamp to seconds
    const bars = candles.map(c => ({
      time:  c.time,
      open:  c.open, high: c.high, low: c.low, close: c.close,
    }));
    seriesCandle.setData(bars);
    currentSeries = seriesCandle;

    // Support line
    if (data && data.support) {
      const supLine = lwChart.addLineSeries({
        color: "rgba(88,166,255,0.6)", lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        lastValueVisible: true,
        priceLineVisible: false,
      });
      const times = candles.map(c => c.time);
      supLine.setData(times.map(t => ({ time: t, value: data.support })));
    }
    if (data && data.resistance) {
      const resLine = lwChart.addLineSeries({
        color: "rgba(248,81,73,0.6)", lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        lastValueVisible: true,
        priceLineVisible: false,
      });
      const times = candles.map(c => c.time);
      resLine.setData(times.map(t => ({ time: t, value: data.resistance })));
    }
  } else {
    seriesLine = lwChart.addLineSeries({
      color: "#58a6ff", lineWidth: 2,
      lastValueVisible: true,
      priceLineVisible: false,
    });
    seriesLine.setData(candles.map(c => ({ time: c.time, value: c.close })));
    currentSeries = seriesLine;
  }
  lwChart.timeScale().fitContent();
}

// ── TELEGRAM ─────────────────────────────────────────────────────
async function sendTelegram() {
  if (!currentTicker) return;
  const btn = document.getElementById("btn-telegram");
  btn.disabled = true; btn.textContent = "⏳ Đang gửi...";
  try {
    await apiFetch(`/api/telegram/${currentTicker}`, { method: "POST" });
    showToast("✅ Đã gửi về Telegram!");
  } catch (e) {
    showToast(`❌ ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "📱 Gửi phân tích về Telegram";
  }
}

// ── QUICK ADD PORTFOLIO ───────────────────────────────────────────
async function quickAddPortfolio() {
  if (!currentTicker) { showToast("⚠️ Chưa có mã phân tích!"); return; }
  const price = parseFloat(document.getElementById("qa-price").value);
  const qty   = parseInt(document.getElementById("qa-qty").value) || 0;
  const note  = document.getElementById("qa-note").value.trim();

  if (!price || price <= 0) { showToast("⚠️ Nhập giá vào hợp lệ!"); return; }

  try {
    await apiFetch("/api/portfolio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker:      currentTicker,
        entry_date:  new Date().toLocaleDateString("vi-VN"),
        entry_price: price,
        quantity:    qty,
        note,
      }),
    });
    showToast(`✅ Đã thêm ${currentTicker} vào danh mục!`);
    document.getElementById("qa-price").value = "";
    document.getElementById("qa-qty").value   = "";
    document.getElementById("qa-note").value  = "";
  } catch (e) {
    showToast(`❌ ${e.message}`);
  }
}

// ══════════════════════════════════════════════════════════════════
// PORTFOLIO TAB
// ══════════════════════════════════════════════════════════════════
async function loadPortfolio() {
  const loading = document.getElementById("portfolio-loading");
  const empty   = document.getElementById("portfolio-empty");
  const list    = document.getElementById("portfolio-list");
  loading.classList.remove("hidden");
  empty.classList.add("hidden");
  list.innerHTML = "";

  try {
    const items = await apiFetch("/api/portfolio/refresh");
    loading.classList.add("hidden");

    if (!items || items.length === 0) {
      empty.classList.remove("hidden");
      return;
    }

    items.forEach(item => {
      const card = document.createElement("div");
      card.className = "portfolio-item";

      const pnl = item.pnl_pct;
      const pnlCls = pnl == null ? "neutral" : pnl >= 0 ? "positive" : "negative";
      const pnlTxt = pnl == null ? "—" : `${pnl >= 0 ? "▲" : "▼"} ${Math.abs(pnl).toFixed(2)}%`;
      const amtTxt = item.pnl_amount != null
        ? `${item.pnl_amount >= 0 ? "+" : ""}${fmtPrice(item.pnl_amount)}đ`
        : "";

      card.innerHTML = `
        <div class="pf-header">
          <div>
            <div class="pf-ticker">${item.ticker}</div>
            <div class="pf-date">${item.entry_date}</div>
          </div>
          <div class="pf-pnl">
            <div class="pf-pnl-pct ${pnlCls}">${pnlTxt}</div>
            <div class="pf-pnl-amount">${amtTxt}</div>
          </div>
        </div>
        <div class="pf-details">
          <div class="pf-detail-item">
            <div class="pf-detail-label">Giá vào</div>
            <div class="pf-detail-val">${fmtPrice(item.entry_price)}</div>
          </div>
          <div class="pf-detail-item">
            <div class="pf-detail-label">Giá hiện tại</div>
            <div class="pf-detail-val ${pnlCls}">${item.current_price ? fmtPrice(item.current_price) : "—"}</div>
          </div>
          <div class="pf-detail-item">
            <div class="pf-detail-label">Số CP</div>
            <div class="pf-detail-val">${item.quantity.toLocaleString()}</div>
          </div>
        </div>
        <div class="pf-footer">
          <span class="pf-note">${item.note || ""}</span>
          <div>
            <button class="btn-analyze-pf" onclick="analyzePf('${item.ticker}')">🔍</button>
            <button class="btn-delete" onclick="deletePortfolio(${item.index}, this)">🗑</button>
          </div>
        </div>
      `;
      list.appendChild(card);
    });
  } catch (e) {
    loading.classList.add("hidden");
    showToast(`❌ ${e.message}`);
  }
}

function analyzePf(ticker) {
  document.getElementById("inp-ticker").value = ticker;
  switchTab("analyze", document.getElementById("nav-analyze"));
  doAnalyze();
}

async function deletePortfolio(index, btn) {
  try {
    await apiFetch(`/api/portfolio/${index}`, { method: "DELETE" });
    showToast("🗑 Đã xóa vị thế");
    loadPortfolio();
  } catch (e) {
    showToast(`❌ ${e.message}`);
  }
}

async function addPortfolioManual() {
  const ticker = document.getElementById("pf-ticker").value.trim().toUpperCase();
  const date   = document.getElementById("pf-date").value;
  const price  = parseFloat(document.getElementById("pf-price").value);
  const qty    = parseInt(document.getElementById("pf-qty").value) || 0;
  const note   = document.getElementById("pf-note").value.trim();

  if (!ticker) { showToast("⚠️ Nhập mã CP!"); return; }
  if (!price || price <= 0) { showToast("⚠️ Nhập giá vào hợp lệ!"); return; }

  const fmtDate = date ? (() => {
    const [y, m, d] = date.split("-");
    return `${d}/${m}/${y}`;
  })() : new Date().toLocaleDateString("vi-VN");

  try {
    await apiFetch("/api/portfolio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, entry_date: fmtDate, entry_price: price, quantity: qty, note }),
    });
    showToast(`✅ Đã thêm ${ticker}!`);
    document.getElementById("pf-ticker").value = "";
    document.getElementById("pf-price").value  = "";
    document.getElementById("pf-qty").value    = "";
    document.getElementById("pf-note").value   = "";
    loadPortfolio();
  } catch (e) {
    showToast(`❌ ${e.message}`);
  }
}

// ══════════════════════════════════════════════════════════════════
// SETTINGS TAB
// ══════════════════════════════════════════════════════════════════
function loadSettings() {
  document.getElementById("cfg-api").value = API_BASE;
  document.getElementById("info-api").textContent = API_BASE;
}

async function saveConfig() {
  const url = document.getElementById("cfg-api").value.trim().replace(/\/$/, "");
  if (!url) return;
  API_BASE = url;
  localStorage.setItem(CFG_KEY, url);
  document.getElementById("info-api").textContent = url;

  const status = document.getElementById("cfg-status");
  status.textContent = "Đang kiểm tra kết nối...";
  status.className = "cfg-status";

  const ok = await checkApi();
  status.textContent = ok ? "✅ Kết nối thành công!" : "❌ Không kết nối được. Kiểm tra lại URL và server.";
  status.className = `cfg-status ${ok ? "cfg-ok" : "cfg-err"}`;
}

// ── INIT ────────────────────────────────────────────────────────
window.addEventListener("load", () => {
  setTimeout(() => {
    document.getElementById("splash").style.opacity = "0";
    document.getElementById("splash").style.transition = "opacity .4s";
    setTimeout(() => {
      document.getElementById("splash").remove();
      document.getElementById("app").classList.remove("hidden");
    }, 400);
  }, 1200);
});
