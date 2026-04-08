import streamlit as st
import akshare as ak
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# 網頁基本設定
st.set_page_config(page_title="2330 專用監控面板", layout="centered")

def get_2330_info(symbol="2330"):
    """抓取 2330 即時概況"""
    try:
        # 取得個股即時基本面與快照資料
        df = ak.stock_individual_info_em(symbol=symbol)
        if df is not None:
            # 將表格轉為字典格式，方便提取
            data_dict = dict(zip(df['項目'], df['值']))
            return data_dict
        return None
    except Exception as e:
        st.error(f"即時數據抓取失敗: {e}")
        return None

def get_2330_hist(symbol="2330"):
    """抓取 2330 歷史 K 線數據"""
    try:
        # 抓取今年起的日線數據
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date="20250101", adjust="qfq")
        return df
    except Exception as e:
        st.error(f"歷史數據抓 tree 失敗: {e}")
        return pd.DataFrame()

# --- 網頁畫面佈局 ---

st.title("🛡️ 2330 台積電即時監控")
st.divider()

# 按鈕觸發抓取
if st.button("更新數據") or 'first_run' not in st.session_state:
    st.session_state['first_run'] = True
    
    with st.spinner('正在與 AKShare 伺服器通訊中...'):
        # 1. 抓取數據
        info = get_2330_info("2330")
        hist = get_2330_hist("2330")

        if info:
            # 2. 呈現即時指標
            c1, c2, c3 = st.columns(3)
            
            # 根據東方財富接口，提取最新價、成交量等
            latest_price = info.get('最新價', '---')
            change_percent = info.get('漲跌幅', '0')
            volume = info.get('成交量', '---')
            
            c1.metric("最新股價", f"{latest_price} TWD", f"{change_percent}%")
            c2.metric("今日成交量", f"{volume} 手")
            c3.metric("昨收價", f"{info.get('昨日收盤', '---')}")

            st.write(f"🕒 **最後更新時間：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 3. 繪製 K 線圖
            if not hist.empty:
                st.subheader("2025 年度走勢圖")
                fig = go.Figure(data=[go.Candlestick(
                    x=hist['日期'],
                    open=hist['開盤'],
                    high=hist['最高'],
                    low=hist['最低'],
                    close=hist['收盤'],
                    increasing_line_color= 'red',  # 台股習慣：漲用紅
                    decreasing_line_color= 'green' # 台股習慣：跌用綠
                )])
                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    height=500,
                    template="plotly_white"
                )
                st.plotly_chart(fig, use_container_width=True)
                
                with st.expander("查看原始數據"):
                    st.dataframe(hist.tail(10))
            else:
                st.warning("歷史數據目前的 API 回應為空，請檢查網路連線。")
        else:
            st.error("目前無法從 AKShare 取得 2330 的資料。")

st.caption("註：若長時間無反應，請至終端機執行 `pip install akshare --upgrade` 更新套件。")
