import streamlit as st
import akshare as ak
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import time

# 設定網頁標題與佈局
st.set_page_config(page_title="台股即時監控儀表板", layout="wide")

## --- 功能函式庫 ---

@st.cache_data(ttl=60)  # 緩存 60 秒，避免頻繁請求被封鎖
def get_tw_stock_realtime(symbol):
    """
    獲取台股即時行情 (AKShare 接口可能隨版本更新，此處以通用邏輯示範)
    註：AKShare 獲取台股通常透過個股代碼，例如 '0050'
    """
    try:
        # 使用 akshare 抓取台股行情數據
        # 這裡建議使用 stock_zh_a_spot_em 的邏輯，但需過濾台股代碼
        # 或者使用專門的台股接口（若 AKShare 當時版本支援）
        df = ak.stock_hk_spot_em() # 舉例：部分版本台股在海外/特定接口
        # 實務上推薦：使用 yfinance 作為台股備援，或 AKShare 的通用個股接口
        df = ak.stock_tw_spot_em() # 最新版 AKShare 支援台股接口
        return df[df['代碼'] == symbol]
    except Exception as e:
        return None

def get_history_data(symbol, period="daily"):
    """獲取歷史 K 線數據"""
    # 這裡以 0050 為例，轉換格式
    try:
        df = ak.stock_tw_hist(symbol=symbol, period=period, start_date="20240101")
        return df
    except:
        return pd.DataFrame()

## --- Streamlit 介面設計 ---

st.title("📈 台股即時/歷史股價監控")

# 側邊欄：輸入參數
with st.sidebar:
    st.header("設定")
    stock_code = st.text_input("輸入股票代碼 (例如: 2330)", value="2330")
    auto_refresh = st.checkbox("開啟自動刷新 (每 30 秒)", value=False)
    
    st.info("註：台股開盤時間為 09:00 - 13:30")

# 主介面佈局
col1, col2, col3 = st.columns(3)

# 獲取數據
try:
    # 1. 抓取即時數據 (開盤中)
    realtime_df = ak.stock_tw_spot_em()
    stock_info = realtime_df[realtime_df['代碼'] == stock_code].iloc[0]

    with col1:
        st.metric("最新股價", f"{stock_info['最新價']}", f"{stock_info['漲跌幅']}%")
    with col2:
        st.metric("成交量", f"{stock_info['成交量']} 張")
    with col3:
        st.metric("最高/最低", f"{stock_info['最高']} / {stock_info['最低']}")

    # 2. 繪製 K 線圖 (開盤後/歷史)
    st.subheader(f"歷史走勢圖 - {stock_code}")
    hist_df = ak.stock_tw_hist(symbol=stock_code, period="daily", start_date="20240101", adjust="qfq")
    
    if not hist_df.empty:
        fig = go.Figure(data=[go.Candlestick(
            x=hist_df['日期'],
            open=hist_df['開盤'],
            high=hist_df['最高'],
            low=hist_df['最低'],
            close=hist_df['收盤'],
            name='K線'
        )])
        fig.update_layout(xaxis_rangeslider_visible=False, height=500)
        st.plotly_chart(fig, use_container_width=True)
    
    # 3. 顯示原始數據表格
    with st.expander("查看詳細數據表"):
        st.write(hist_df.tail(10))

except Exception as e:
    st.error(f"無法獲取數據，請檢查代碼是否正確。錯誤訊息: {e}")

# 自動刷新邏輯
if auto_refresh:
    time.sleep(30)
    st.rerun()
