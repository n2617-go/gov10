import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import pytz
import json
import os
import streamlit.components.v1 as components
from datetime import datetime, time as dt_time, timedelta
from FinMind.data import DataLoader
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands

# ===========================================================================
# --- 0. 基礎設定 ---
# ===========================================================================
tw_tz         = pytz.timezone("Asia/Taipei")
MARKET_OPEN      = dt_time(9, 0)
MARKET_CLOSE     = dt_time(13, 30)
AFTERHOURS_START = dt_time(14, 0)
TG_SAVE_FILE  = "tg_config.json"
USER_DATA_DIR = "user_data"
ALERT_DIR     = "alert_state"
LS_KEY        = "tw_stock_browser_id"
# 預設股票結構增加門檻欄位
DEFAULT_STOCKS = [{"id": "2330", "name": "台積電", "threshold": 3.0, "reset": 1.0}]

os.makedirs(USER_DATA_DIR, exist_ok=True)
os.makedirs(ALERT_DIR, exist_ok=True)

def now_tw() -> datetime:
    return datetime.now(tw_tz)

def is_market_open() -> bool:
    n = now_tw()
    if n.weekday() >= 5: return False
    return MARKET_OPEN <= n.time() <= MARKET_CLOSE

def is_after_hours() -> bool:
    n = now_tw(); t = n.time(); wday = n.weekday()
    if wday >= 5: return True
    if t >= AFTERHOURS_START or t < MARKET_OPEN: return True
    return False

def today_str() -> str:
    return now_tw().strftime("%Y-%m-%d")

# ===========================================================================
# --- 1. 使用者識別與檔案管理 ---
# ===========================================================================
def get_browser_id_component():
    components.html(f"""
    <script>
    (function() {{
        const KEY = "{LS_KEY}";
        let bid = localStorage.getItem(KEY);
        if (!bid) {{
            bid = (typeof crypto !== "undefined" && crypto.randomUUID)
                  ? crypto.randomUUID()
                  : Math.random().toString(36).slice(2) + Date.now().toString(36);
            localStorage.setItem(KEY, bid);
        }}
        const url = new URL(window.parent.location.href);
        if (url.searchParams.get("bid") !== bid) {{
            url.searchParams.set("bid", bid);
            window.parent.history.replaceState(null, "", url.toString());
            window.parent.location.reload();
        }}
    }})();
    </script>
    """, height=0)

def safe_bid(bid: str) -> str:
    return "".join(c for c in bid if c.isalnum() or c in "-_")[:64]

def user_file(bid: str) -> str:
    return os.path.join(USER_DATA_DIR, safe_bid(bid) + ".json")

def load_user_stocks(bid: str) -> list:
    path = user_file(bid)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else list(DEFAULT_STOCKS)
        except: pass
    return list(DEFAULT_STOCKS)

def save_user_stocks(bid: str, stocks: list):
    try:
        with open(user_file(bid), "w", encoding="utf-8") as f:
            json.dump(stocks, f, ensure_ascii=False, indent=2)
    except: pass

# ===========================================================================
# --- 2. 通知狀態與 Telegram 設定 ---
# ===========================================================================
def alert_state_file(bid: str) -> str:
    return os.path.join(ALERT_DIR, safe_bid(bid) + "_alert.json")

def load_alert_state(bid: str) -> dict:
    path = alert_state_file(bid); today = today_str()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today: return data
        except: pass
    return {"date": today, "states": {}}

def save_alert_state(bid: str, state: dict):
    try:
        with open(alert_state_file(bid), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except: pass

def load_tg_config() -> dict:
    if os.path.exists(TG_SAVE_FILE):
        try:
            with open(TG_SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"tg_token": "", "tg_chat_id": "", "tg_threshold": 3.0, "tg_reset": 1.0, "finmind_token": ""}

# ===========================================================================
# --- 3. FinMind & 數據抓取邏輯 (保留原功能) ---
# ===========================================================================
def get_finmind_loader():
    dl = DataLoader()
    token = st.session_state.get("finmind_token", "")
    if token: dl.login_by_token(api_token=token)
    return dl

@st.cache_data(ttl=60)
def fetch_all_quotes() -> dict:
    try:
        dl = get_finmind_loader()
        df = dl.taiwan_stock_quote(stock_id="")
        if df is None or df.empty: return {}
        result = {}
        for _, row in df.iterrows():
            sid = str(row.get("stock_id", ""))
            if not sid: continue
            result[sid] = {
                "price": float(row.get("close", row.get("price", 0))),
                "pct": float(row.get("change_rate", row.get("ChangeRate", 0))),
                "open": float(row.get("open", 0))
            }
        return result
    except: return {}

def get_quote(stock_id: str) -> dict:
    return fetch_all_quotes().get(stock_id, {})

def fetch_momentum_analysis(stock_id: str, pct: float, tg_threshold: float) -> dict:
    try:
        dl = get_finmind_loader(); today = today_str()
        df = dl.taiwan_stock_minute(stock_id=stock_id, start_date=today, end_date=today)
        if df is None or df.empty: return {}
        vol_col = next((c for c in ["volume", "Volume", "vol"] if c in df.columns), None)
        if not vol_col: return {}
        df[vol_col] = pd.to_numeric(df[vol_col], errors="coerce").fillna(0)
        recent = df.tail(6)
        if len(recent) < 2: return {}
        cur_vol = float(recent.iloc[-1][vol_col])
        avg_vol = float(recent.iloc[:-1][vol_col].mean())
        ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0
        
        # 意涵判斷
        is_up, is_down = pct >= tg_threshold, pct <= -tg_threshold
        if is_up and ratio >= 1.5: impl = "🚀 短線意涵：帶量突破"
        elif is_up and ratio < 1.0: impl = "⚠️ 短線意涵：虛假拉抬"
        elif is_down and ratio >= 1.5: impl = "💣 短線意涵：帶量殺盤"
        elif is_down and ratio < 1.0: impl = "🔍 短線意涵：洗盤觀察"
        else: impl = ""
        
        label = f"🔥 爆量({ratio:.1f}倍)" if ratio >= 2.0 else f"📈 放量({ratio:.1f}倍)" if ratio >= 1.5 else "➡️ 量能正常" if ratio >= 1.0 else f"📉 縮量({ratio*100:.0f}%)"
        return {"cur_vol": int(cur_vol), "avg_vol": int(avg_vol), "ratio": round(ratio, 2), "momentum_label": label, "short_impl": impl}
    except: return {}

# ===========================================================================
# --- 4. 盤後分析與技術指標 ---
# ===========================================================================
def fetch_finmind_close_volume(stock_id: str) -> tuple:
    try:
        dl = get_finmind_loader(); today = today_str()
        start = (now_tw() - timedelta(days=7)).strftime("%Y-%m-%d")
        df = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=today)
        if df is None or df.empty: return 0.0, ""
        row = df.sort_values("date").iloc[-1]
        for col in ["Trading_Volume", "volume", "Volume"]:
            if col in row.index: return round(float(row[col])/1000), str(row.get("date",""))
        return 0.0, ""
    except: return 0.0, ""

def run_afterhours_analysis(bid: str, stock: dict, pct: float, hist_df: pd.DataFrame, tg_threshold: float) -> str:
    sid = stock["id"]; alert_state = load_alert_state(bid); s = alert_state.setdefault("states", {}).setdefault(sid, {})
    if s.get("ah_date") == today_str() and s.get("ah_threshold") == tg_threshold: return s.get("ah_impl", "")
    
    # 計算 5MAV
    vols = pd.to_numeric(hist_df["Volume"], errors="coerce").dropna()
    mav5 = round(vols.iloc[-5:].mean()/1000) if len(vols) >= 5 else 0
    if mav5 <= 0: return ""
    
    close_vol, _ = fetch_finmind_close_volume(sid)
    if close_vol <= 0: return ""
    
    ratio = close_vol / mav5
    if pct >= tg_threshold and ratio > 1.1: impl = "📈 盤後意涵：量增上漲，可考慮留倉"
    elif pct >= tg_threshold and ratio < 0.9: impl = "⚠️ 盤後意涵：量縮上漲，不宜追高"
    elif pct <= -tg_threshold and ratio > 1.1: impl = "💣 盤後意涵：趨勢轉弱，建議避開"
    elif pct <= -tg_threshold and ratio < 0.9: impl = "🔍 盤後意涵：量縮下跌，可尋買點"
    else: impl = ""
    
    s.update({"ah_impl": impl, "ah_date": today_str(), "ah_threshold": tg_threshold, "ah_vol": int(close_vol), "ah_mav5": int(mav5), "ah_ratio": round(ratio,2)})
    save_alert_state(bid, alert_state)
    return impl

def get_history_cached(stock_id: str) -> pd.DataFrame:
    cache = st.session_state.hist_cache; today = today_str()
    if stock_id in cache and cache[stock_id]["cached_date"] == today: return cache[stock_id]["df"].copy()
    df = pd.DataFrame()
    for suffix in [".TW", ".TWO"]:
        try:
            temp = yf.download(stock_id + suffix, period="6mo", progress=False)
            if not temp.empty: df = temp; break
        except: continue
    if df.empty: return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df = df.astype(float).ffill()
    df.index = pd.to_datetime(df.index).normalize()
    df = df[df.index <= (pd.Timestamp(today) - timedelta(days=1))]
    cache[stock_id] = {"df": df, "cached_date": today}
    return df.copy()

def calc_indicators(df: pd.DataFrame):
    if len(df) < 30: return None
    close = pd.Series(df["Close"].values.flatten(), index=df.index).astype(float)
    high = pd.Series(df["High"].values.flatten(), index=df.index).astype(float)
    low = pd.Series(df["Low"].values.flatten(), index=df.index).astype(float)
    try:
        df = df.copy()
        df["MA5"] = SMAIndicator(close, window=5).sma_indicator()
        df["MA10"] = SMAIndicator(close, window=10).sma_indicator()
        df["MA20"] = SMAIndicator(close, window=20).sma_indicator()
        stoch = StochasticOscillator(high, low, close, window=9)
        df["K"], df["D"] = stoch.stoch(), stoch.stoch_signal()
        df["MACD_diff"] = MACD(close).macd_diff()
        df["RSI"] = RSIIndicator(close).rsi()
        df["BBM"] = BollingerBands(close).bollinger_mavg()
        return df
    except: return None

@st.cache_data(ttl=60)
def fetch_and_analyze(stock_id: str):
    hist_df = get_history_cached(stock_id)
    if hist_df.empty: return None
    
    # 縫合今日棒
    if is_market_open():
        quote = get_quote(stock_id)
        if quote:
            today = pd.Timestamp(today_str())
            prev_c = float(hist_df.iloc[-1]["Close"])
            row = pd.Series({"Open": quote.get("open", prev_c), "High": max(quote.get("open", prev_c), quote["price"]), 
                             "Low": min(quote.get("open", prev_c), quote["price"]), "Close": quote["price"], "Volume": 0.0}, name=today)
            df = pd.concat([hist_df, pd.DataFrame([row])])
            src = "📡 即時縫合"
        else: df = hist_df; src = "🗂 歷史資料"
    else: df = hist_df; src = "🗂 歷史資料"
    
    df = calc_indicators(df)
    if df is None: return None
    last, prev = df.iloc[-1], df.iloc[-2]
    
    # 評分邏輯
    score, details = 0, []
    if last["MA5"] > last["MA10"] > last["MA20"]: details.append("✅ 均線多頭"); score += 1
    if prev["K"] <= prev["D"] and last["K"] > last["D"] and (last["K"]-last["D"])>=1:
        lbl = "✅ KD 低檔金叉" if (last["K"]+last["D"])/2 < 20 else "✅ KD 標準金叉"
        details.append(lbl); score += 1
    if last["MACD_diff"] > 0: details.append("✅ MACD 轉正"); score += 1
    if last["RSI"] > 50: details.append("✅ RSI 強勢"); score += 1
    if last["Close"] > last["BBM"]: details.append("✅ 站穩月線"); score += 1
    
    dm = {5:("S","🔥續抱","red"), 4:("A","🚀偏多","orange"), 3:("B","📈試單","green"), 2:("C","⚖️觀望","blue"), 1:("D","📉避險","gray"), 0:("E","🚫不進場","black")}
    grade, action, color = dm[score]
    
    # 漲跌幅
    if is_market_open():
        q = get_quote(stock_id); pct = q.get("pct", 0.0); price = q.get("price", float(last["Close"]))
    else:
        pct = (float(last["Close"]) - float(prev["Close"])) / float(prev["Close"]) * 100; price = float(last["Close"])
        
    return {"price": price, "pct": pct, "grade": grade, "action": action, "color": color, "details": details, "k": float(last["K"]), "d": float(last["D"]), "source": src, "hist_df": hist_df}

# ===========================================================================
# --- 5. 通知邏輯 (支援個別門檻) ---
# ===========================================================================
def check_and_notify(bid: str, stock: dict, pct: float, res: dict, tg_token: str, tg_chat_id: str, tg_threshold: float, tg_reset: float) -> str:
    if not tg_token or not tg_chat_id: return "⚪ 未設定通知"
    sid = stock["id"]; alert_state = load_alert_state(bid); s = alert_state.setdefault("states", {}).setdefault(sid, {"alerted":False, "momentum":{}})
    abs_pct = abs(pct)
    
    if s["alerted"]:
        if abs_pct <= tg_reset:
            s.update({"alerted": False, "alerted_at": "", "momentum": {}})
            save_alert_state(bid, alert_state)
            return f"🔓 已重置 ({pct:+.2f}%)"
        mom = s.get("momentum", {}); m_lbl = mom.get("momentum_label", ""); s_impl = mom.get("short_impl", "")
        return f"🔒 鎖定({s.get('alerted_at')}) " + (m_lbl if m_lbl else "") + (f" {s_impl}" if s_impl else "")
    else:
        if abs_pct >= tg_threshold:
            momentum = fetch_momentum_analysis(sid, pct, tg_threshold)
            s["momentum"] = momentum
            msg = f"🔔 <b>【價格異動】</b>\n標的：{stock['name']}({sid})\n股價：{res['price']:.2f} ({pct:+.2f}%)\n評級：{res['grade']} ({res['action']})\n指標：{', '.join(res['details'])}\n門檻：{tg_threshold}% / {tg_reset}%"
            if momentum.get("short_impl"): msg += f"\n\n{momentum['short_impl']}\n{momentum['momentum_label']}"
            requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json={"chat_id":tg_chat_id, "text":msg, "parse_mode":"HTML"})
            s.update({"alerted": True, "alerted_at": now_tw().strftime("%H:%M")})
            save_alert_state(bid, alert_state)
            return f"✅ 已發送({s['alerted_at']})"
        return f"⚪ 監控中({pct:+.2f}%)"

# ===========================================================================
# --- 6. 介面設計 ---
# ===========================================================================
st.set_page_config(page_title="台股決策系統 V8.0", layout="centered")

st.markdown("""
<style>
.block-container { padding-top: 1rem !important; }
.stock-card { background: #1e1e2e; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 12px; margin-bottom: 8px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-title { font-size: 1.2rem; font-weight: 700; }
.card-price { font-size: 1.5rem; font-weight: 800; text-align: right; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.8rem; margin-right: 4px; background: rgba(255,255,255,0.1); }
.action-red { color: #ff6b6b; } .action-orange { color: #f6ad55; } .action-green { color: #51cf66; }
.threshold-box { font-size: 0.7rem; color: #a0aec0; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

st.title("🤖 台股 AI 分級決策 V8.0")
browser_id = st.query_params.get("bid", "")
if not browser_id: get_browser_id_component(); st.stop()

# 自動重新整理
if is_market_open():
    components.html("<script>setTimeout(function(){window.parent.location.reload();}, 60000);</script>", height=0)
    st.success("🟢 開盤中 - 每分鐘自動掃描")

# 側邊欄設定
with st.sidebar:
    st.header("⚙️ 全域預設設定")
    st.session_state.finmind_token = st.text_input("FinMind Token", type="password", value=load_tg_config()["finmind_token"])
    st.session_state.tg_token = st.text_input("Bot Token", type="password", value=load_tg_config()["tg_token"])
    st.session_state.tg_chat_id = st.text_input("Chat ID", value=load_tg_config()["tg_chat_id"])
    st.session_state.tg_threshold = st.number_input("預設觸發門檻%", value=3.0, step=0.5)
    st.session_state.tg_reset = st.number_input("預設重置門檻%", value=1.0, step=0.5)
    if st.button("💾 儲存全域設定"): 
        with open(TG_SAVE_FILE,"w") as f: json.dump({"tg_token":st.session_state.tg_token, "tg_chat_id":st.session_state.tg_chat_id, "tg_threshold":st.session_state.tg_threshold, "tg_reset":st.session_state.tg_reset, "finmind_token":st.session_state.finmind_token}, f)
        st.success("已儲存")

# 新增股票
with st.container(border=True):
    c1, c2, c3 = st.columns([1,1,1])
    nid = c1.text_input("代號")
    nname = c2.text_input("名稱")
    if c3.button("➕ 新增股票", use_container_width=True) and nid and nname:
        st.session_state.my_stocks.append({"id":nid, "name":nname, "threshold":st.session_state.tg_threshold, "reset":st.session_state.tg_reset})
        save_user_stocks(browser_id, st.session_state.my_stocks); st.rerun()

# 股票列表顯示
st.session_state.my_stocks = load_user_stocks(browser_id)
if "hist_cache" not in st.session_state: st.session_state.hist_cache = {}

for idx, stock in enumerate(st.session_state.my_stocks):
    res = fetch_and_analyze(stock["id"])
    if res:
        # 決定門檻
        s_th = stock.get("threshold", st.session_state.tg_threshold)
        s_rs = stock.get("reset", st.session_state.tg_reset)
        
        # 通知邏輯
        alert_msg = check_and_notify(browser_id, stock, res["pct"], res, st.session_state.tg_token, st.session_state.tg_chat_id, s_th, s_rs)
        ah_impl = run_afterhours_analysis(browser_id, stock, res["pct"], res["hist_df"], s_th) if is_after_hours() else ""

        # UI 卡片
        col_card, col_ctrl = st.columns([7, 3])
        with col_card:
            pct_color = "#ff6b6b" if res["pct"] > 0 else "#51cf66" if res["pct"] < 0 else "#868e96"
            st.markdown(f"""
            <div class="stock-card">
                <div class="card-header">
                    <span class="card-title">{stock['name']} ({stock['id']})</span>
                    <div class="card-price" style="color:{pct_color}">{res['price']:.2f}<br><span style="font-size:0.9rem">{res['pct']:+.2f}%</span></div>
                </div>
                <div>
                    <span class="badge" style="color:{res['color']}">{res['grade']} {res['action']}</span>
                    <span class="badge">{res['source']}</span>
                </div>
                <div style="font-size:0.8rem; margin-top:5px; opacity:0.8;">指標：{", ".join(res['details'])}</div>
                <div style="font-size:0.8rem; color:#f6ad55; margin-top:5px;">{ah_impl}</div>
                <div class="threshold-box">🔔 {alert_msg} (門檻: {s_th}% / {s_rs}%)</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col_ctrl:
            st.caption("個別門檻設定")
            new_th = st.number_input("觸發%", value=float(s_th), step=0.1, key=f"th_{stock['id']}", label_visibility="collapsed")
            new_rs = st.number_input("重置%", value=float(s_rs), step=0.1, key=f"rs_{stock['id']}", label_visibility="collapsed")
            if new_th != s_th or new_rs != s_rs:
                st.session_state.my_stocks[idx]["threshold"] = new_th
                st.session_state.my_stocks[idx]["reset"] = new_rs
                save_user_stocks(browser_id, st.session_state.my_stocks); st.rerun()
            if st.button("🗑", key=f"del_{stock['id']}", use_container_width=True):
                st.session_state.my_stocks.pop(idx); save_user_stocks(browser_id, st.session_state.my_stocks); st.rerun()
    else:
        st.error(f"無法取得 {stock['name']} 資料")
