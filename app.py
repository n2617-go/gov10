import streamlit as st
import akshare as ak
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import time

# 設定網頁標題
st.set_page_config(page_title="AKShare 台股監控儀表板", layout="wide")

@st.cache_data(ttl=30)
def fetch_realtime_data():
    """抓取即時報價 - 使用東方財富插件"""
    try:
        # 抓取全球即時行情快照
        df = ak.stock_zh_a_spot_em()
        return df
    except Exception as e:
        st.error(f"即時數據抓取失敗: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_history_data(symbol):
    """抓取歷史數據 - 使用通用歷史接口"""
    try:
        # AKShare 歷史數據接口，這裡使用通用格式
        # 註：若此接口在您的地區受限，建議搭配 yfinance 作為備援
        df = ak.stock_us_hist(symbol=f"116.{symbol}", period="daily", start_date="20240101", adjust="qfq")
        return df
    except:
        # 備援：嘗試另一個常見的台股歷史接口
        try:
            df = ak.stock_hk_hist(symbol=symbol, period="daily", start_date="20240101", adjust="qfq")
            return df
        except:
            return pd.DataFrame()

# --- 介面設計 ---

st.title("📈 台股即時監控 (AKShare 穩定版)")

# 側邊欄
with st.sidebar:
    st.header("搜尋設定")
    input_code = st.text_input("請輸入股票代碼", value="2330")
    refresh_btn = st.button("手動整理")
    auto_refresh = st.checkbox("自動刷新 (30s)")

# 數據處理邏輯
all_data = fetch_realtime_data()

if not all_data.empty:
    # 在東方財富數據中，台股通常被歸類在特定區塊，我們透過代碼匹配
    target_stock = all_data[all_data['代碼'] == input_code]
    
    if not target_stock.empty:
        stock_info = target_stock.iloc[0]
        
        # 顯示指標
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最新價", f"{stock_info['最新價']}", f"{stock_info['漲跌幅']}%")
        c2.metric("成交量", f"{stock_info['成交量']} 手")
        c3.metric("最高", f"{stock_info['最高']}")
        c4.metric("最低", f"{stock_info['最低']}")
        
        # 歷史圖表
        st.subheader(f"{input_code} 走勢分析")
        hist_df = fetch_history_data(input_code)
        
        if not hist_df.empty:
            fig = go.Figure(data=[go.Candlestick(
                x=hist_df['日期'],
                open=hist_df['開盤'],
                high=hist_df['最高'],
                low=hist_df['最低'],
                close=hist_df['收盤']
            )])
            fig.update_layout(xaxis_rangeslider_visible=False, height=450, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("暫時無法取得該代碼的歷史 K 線數據。")
            
        # 顯示原始清單 (供調試用)
        with st.expander("查看即時數據源清單"):
            st.dataframe(all_data.head(100))
    else:
        st.error(f"在即時清單中找不到代碼 {input_code}。請確認代碼是否正確，或嘗試更新 AKShare。")
else:
    st.warning("無法取得即時行情資料表。")

# 自動刷新
if auto_refresh:
    time.sleep(30)
    st.rerun()
