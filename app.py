# app.py

# 1. Import Libraries ที่จำเป็น (ส่วนนี้คือการเรียกเครื่องมือต่างๆ มาเตรียมไว้)
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates # สำหรับการจัดรูปแบบวันที่ในกราฟ
import seaborn as sns # สำหรับกราฟสวยๆ
# from IPython.display import display # Streamlit มี st.dataframe และ st.table แทน ไม่ต้องใช้ตัวนี้
from matplotlib.colors import LinearSegmentedColormap, Normalize # สำหรับ Heatmaps (จะใช้ในอนาคต)
from matplotlib.lines import Line2D # สำหรับ MFE/MAE Scatter plot legends

# ตั้งค่าให้หน้าเว็บแสดงผลเต็มความกว้าง (ทำหรือไม่ทำก็ได้)
st.set_page_config(layout="wide")

# หัวข้อหลักของ Dashboard ของเรา
st.title("🚀 Backtest Analysis Dashboard ของท่านพี่")
st.write("ยินดีต้อนรับสู่ Dashboard วิเคราะห์ผลการเทรด! อัปโหลดไฟล์ Excel แล้วมาดูกันเลยเจ้าค่ะ")
st.markdown("---") # เส้นคั่น

# --- จบส่วนโค้ดเริ่มต้น ---

# 📌 Utility Functions (จากไฟล์ 01.DataPreparation...)
def clean_number(val):
    """Convert string with commas/spaces to float. Return NaN if fails."""
    try:
        return float(str(val).replace(',', '').replace(' ', ''))
    except Exception:
        return np.nan

def validate_stop_loss(stop_loss_pct):
    """
    Ensure stop_loss_pct is a float between 0 and 1 (not inclusive).
    Raise ValueError if not valid.
    """
    try:
        pct = float(stop_loss_pct)
        if not (0 < pct < 1):
            raise ValueError("stop_loss_pct ต้องเป็นตัวเลขทศนิยมที่มากกว่า 0 และน้อยกว่า 1 เช่น 0.002 (สำหรับ 0.2%)")
        return pct
    except Exception:
        raise ValueError("stop_loss_pct ต้องเป็นตัวเลขทศนิยมที่มากกว่า 0 และน้อยกว่า 1 เช่น 0.002 (สำหรับ 0.2%)")

def safe_divide(numerator, denominator):
    """Elementwise safe division: if denom is 0 or NaN, return NaN."""
    with np.errstate(divide='ignore', invalid='ignore'):
        result = np.where((denominator == 0) | pd.isnull(denominator) | (denominator == np.inf) | (denominator == -np.inf),
                          np.nan,
                          numerator / denominator)
    return result

# --- Custom Diverging Normalize for Heatmaps (จากไฟล์ 08, 09) ---
class CustomDivergingNorm(Normalize):
    """
    Normalize that maps vcenter=0 to white in colormap.
    Negative values to red, positive values to blue.
    """
    def __init__(self, vmin=None, vmax=None, vcenter=0, clip=False): # Added default vmin, vmax
        super().__init__(vmin, vmax, clip)
        self.vcenter = vcenter

    def __call__(self, value, clip=None):
        vmin, vcenter, vmax = self.vmin, self.vcenter, self.vmax
        
        # Handle cases where vmin, vcenter, or vmax might be the same
        if vmin is None or vmax is None or vmin == vmax: # if all data is same or no data
            return np.ma.masked_array(np.full_like(value, 0.5, dtype=float)) # Return mid-point (white)

        value = np.ma.masked_array(value, np.isnan(value)) # Mask NaNs

        result = np.ma.masked_array(np.zeros_like(value, dtype=float), value.mask)
        
        # Negative part: [0, 0.5)
        neg_mask = value < vcenter
        if vcenter > vmin: # Avoid division by zero if vcenter == vmin
            result[neg_mask] = 0.5 * (value[neg_mask] - vmin) / (vcenter - vmin)
        elif vmin == vcenter: # All values >= vcenter or all values are vcenter
             result[neg_mask] = 0.0 # Map to the very start of the colormap if it's exactly vmin=vcenter

        # Positive part: [0.5, 1.0]
        pos_mask = value >= vcenter
        if vmax > vcenter: # Avoid division by zero if vmax == vcenter
            result[pos_mask] = 0.5 + 0.5 * (value[pos_mask] - vcenter) / (vmax - vcenter)
        elif vmax == vcenter: # All values <= vcenter or all values are vcenter
            result[pos_mask] = 0.5 # Map to the center if it's exactly vmax=vcenter (and also >= vcenter)
            if vmin == vmax: # If all values are the same (vmin=vcenter=vmax)
                 result[pos_mask] = 0.5 # map to center (white)

        # Clip result to [0, 1] to handle potential floating point inaccuracies or extreme values if clip is True
        if self.clip:
            result = np.ma.clip(result, 0, 1)
            
        return result


# 📌 Core Function: Calculate R-Multiple and Risk (จากไฟล์ 01.DataPreparation...)
def calc_r_multiple_and_risk(xls_path, stop_loss_pct):
    # st.info(f"เริ่มการคำนวณ R-Multiple และ Risk ด้วย Stop Loss: {stop_loss_pct*100:.2f}% จากไฟล์: {xls_path}") # Reduced verbosity
    stop_loss_pct = validate_stop_loss(stop_loss_pct)

    # --- Load Data
    try:
        df_trades = pd.read_excel(xls_path, sheet_name='List of trades')
        df_props  = pd.read_excel(xls_path, sheet_name='Properties')
    except Exception as e:
        raise RuntimeError(f"โหลดไฟล์ Excel ผิดพลาด: {e}. กรุณาตรวจสอบว่าไฟล์ถูกต้องและมีชีทชื่อ 'List of trades' และ 'Properties'")

    # --- Extract Point Value
    try:
        point_value_row = df_props[df_props.iloc[:, 0].astype(str).str.contains("point value", case=False, na=False)]
        if point_value_row.empty:
            raise ValueError("ไม่พบคำว่า 'point value' ในคอลัมน์แรกของชีท 'Properties'")
        point_value = clean_number(point_value_row.iloc[0, 1])
        if np.isnan(point_value) or point_value <= 0:
            raise ValueError(f"Point Value ที่พบ ({point_value_row.iloc[0, 1]}) ไม่ถูกต้อง (เป็น NaN หรือน้อยกว่าหรือเท่ากับ 0)")
    except Exception as e:
         raise ValueError(f"ข้อผิดพลาดในการดึง Point Value จากชีท 'Properties': {e}")

    # --- Prepare Entry & Exit DataFrames
    try:
        df_entry_orig = df_trades[df_trades['Type'].astype(str).str.contains("Entry", case=False, na=False)].copy()
        df_exit_orig  = df_trades[df_trades['Type'].astype(str).str.contains("Exit", case=False, na=False)].copy()
        if df_entry_orig.empty:
             st.warning("⚠️ ไม่พบรายการ Entry trades ในไฟล์ Excel.")
        if df_exit_orig.empty:
             st.warning("⚠️ ไม่พบรายการ Exit trades ในไฟล์ Excel. จะไม่สามารถคำนวณผลลัพธ์ส่วนใหญ่ได้")
             expected_cols_final = [
                'Trade #', 'Entry Day', 'Entry HH:MM', 'Entry Time', 'Entry Signal',
                'Exit Time', 'Exit Type',
                'P&L USD', 'Run-up USD', 'Drawdown USD',
                'Risk USD', 'Profit(R)', 'MFE(R)', 'MAE(R)'
             ]
             empty_df = pd.DataFrame(columns=expected_cols_final)
             for col in ['Entry Time', 'Exit Time']:
                 if col in empty_df.columns: empty_df[col] = pd.to_datetime(empty_df[col])
             return empty_df
    except KeyError:
        raise KeyError("ไม่พบคอลัมน์ 'Type' ในชีท 'List of trades'.")
    except Exception as e:
        raise RuntimeError(f"ข้อผิดพลาดในการกรอง Entry/Exit trades จากคอลัมน์ 'Type': {e}")

    try:
        df_entry = df_entry_orig.copy()
        df_exit = df_exit_orig.copy()
        if not df_entry.empty: df_entry['Date/Time'] = pd.to_datetime(df_entry['Date/Time'], errors='coerce') # Coerce errors
        if not df_exit.empty: df_exit['Date/Time'] = pd.to_datetime(df_exit['Date/Time'], errors='coerce') # Coerce errors
    except KeyError: raise KeyError("ไม่พบคอลัมน์ 'Date/Time' ในชีท 'List of trades'.")
    # except Exception as e: raise ValueError(f"รูปแบบข้อมูลในคอลัมน์ 'Date/Time' ไม่ถูกต้อง: {e}") # Coerce handles this

    for col in ['Price USD', 'Quantity']:
        if not df_entry.empty:
            if col not in df_entry.columns: raise KeyError(f"ไม่พบคอลัมน์ '{col}' ในข้อมูล Entry trades.")
            df_entry[col] = df_entry[col].map(clean_number)
        if not df_exit.empty and col in df_exit.columns:
            df_exit[col] = df_exit[col].map(clean_number)

    if not df_entry.empty:
        df_entry['Risk USD'] = (df_entry['Price USD'] * stop_loss_pct * df_entry['Quantity'] * point_value)
        if df_entry['Risk USD'].isnull().any():
            st.warning("⚠️ มีบางรายการ Entry trades ที่ไม่สามารถคำนวณ 'Risk USD' ได้.")
    else: df_entry['Risk USD'] = np.nan

    if 'Trade #' not in df_trades.columns: raise KeyError("ไม่พบคอลัมน์ 'Trade #' ในชีท 'List of trades'.")
    if not df_entry.empty and df_entry['Trade #'].duplicated().any(): st.warning("⚠️ พบหมายเลข Trade # ซ้ำซ้อนในข้อมูล Entry trades.")
    if not df_exit.empty and df_exit['Trade #'].duplicated().any(): st.warning("⚠️ พบหมายเลข Trade # ซ้ำซ้อนในข้อมูล Exit trades.")

    n_missing_risk = 0
    if not df_exit.empty:
        if not df_entry.empty:
            # Ensure 'Trade #' in df_entry is suitable as index (no NaNs, unique)
            df_entry_for_map = df_entry.dropna(subset=['Trade #']).drop_duplicates(subset=['Trade #'], keep='first')
            risk_map = df_entry_for_map.set_index('Trade #')['Risk USD']
            df_exit['Risk USD'] = df_exit['Trade #'].map(risk_map)
            n_missing_risk = df_exit['Risk USD'].isnull().sum()
            if n_missing_risk > 0: st.warning(f"⚠️ พบ Exit trades จำนวน {n_missing_risk} รายการ ที่ไม่สามารถหา 'Risk USD' ที่สอดคล้องกันได้.")
        else:
            st.warning("⚠️ ไม่มีข้อมูล Entry trades จึงไม่สามารถ map 'Risk USD' ไปยัง Exit trades ได้.")
            df_exit['Risk USD'] = np.nan
    elif 'Risk USD' not in df_exit.columns: df_exit['Risk USD'] = pd.Series(dtype=float) if not df_exit.empty else np.nan

    calc_fields = [('Profit(R)', 'P&L USD'), ('MFE(R)', 'Run-up USD'), ('MAE(R)', 'Drawdown USD')]
    if not df_exit.empty:
        for r_col, src_col in calc_fields:
            if src_col not in df_exit.columns: raise KeyError(f"ไม่พบคอลัมน์ '{src_col}' ในข้อมูล Exit trades ซึ่งจำเป็นสำหรับคำนวณ '{r_col}'.")
            df_exit[src_col] = df_exit[src_col].map(clean_number)
            if 'Risk USD' not in df_exit.columns: df_exit['Risk USD'] = np.nan
            df_exit[r_col] = safe_divide(df_exit[src_col], df_exit['Risk USD'])
            if df_exit[r_col].isnull().sum() > n_missing_risk and n_missing_risk < len(df_exit):
                st.warning(f"⚠️ มีค่า NaN เพิ่มเติมในคอลัมน์ '{r_col}' มากกว่าที่คาดไว้.")
        for col in ['Profit(R)', 'MFE(R)', 'MAE(R)']:
            if col in df_exit.columns and not df_exit[col].isnull().all():
                if (df_exit[col].abs() > 20).any(): st.warning(f"⚠️ พบค่า outlier ในคอลัมน์ '{col}' (ค่าสัมบูรณ์ > 20R) จำนวน {(df_exit[col].abs() > 20).sum()} trade.")
            elif col in df_exit.columns: st.info(f"ℹ️ คอลัมน์ '{col}' สำหรับ Outlier Check ว่างเปล่าหรือมีแต่ NaN.")
    else:
        for r_col, _ in calc_fields: df_exit[r_col] = pd.Series(dtype=float)

    df_result = df_exit.copy()
    if not df_result.empty:
        if not df_entry.empty:
            df_entry_for_map = df_entry.dropna(subset=['Trade #', 'Date/Time']).drop_duplicates(subset=['Trade #'], keep='first')
            entry_time_map = df_entry_for_map.set_index('Trade #')['Date/Time']
            df_result['Entry Time'] = df_result['Trade #'].map(entry_time_map)

            if 'Signal' in df_entry.columns:
                # Assuming Signal is also in df_entry_for_map if it exists in df_entry
                if 'Signal' in df_entry_for_map.columns :
                    entry_signal_map = df_entry_for_map.set_index('Trade #')['Signal']
                    df_result['Entry Signal'] = df_result['Trade #'].map(entry_signal_map)
                else: # Signal in df_entry but not df_entry_for_map (e.g. all NaNs in Signal for rows with Trade# and Date/Time)
                    df_result['Entry Signal'] = np.nan
            else:
                st.info("ℹ️ ไม่พบคอลัมน์ 'Signal' ในข้อมูล Entry trades. 'Entry Signal' จะเป็นค่าว่าง.")
                df_result['Entry Signal'] = np.nan
        else:
            st.warning("⚠️ ไม่มีข้อมูล Entry trades. 'Entry Time' และ 'Entry Signal' จะเป็นค่าว่าง.")
            df_result['Entry Time'] = pd.NaT
            df_result['Entry Signal'] = np.nan

        # Ensure 'Entry Time' is datetime before attempting .dt accessor
        df_result['Entry Time'] = pd.to_datetime(df_result['Entry Time'], errors='coerce')
        df_result['Entry Day'] = df_result['Entry Time'].dt.day_name()
        df_result['Entry HH:MM'] = df_result['Entry Time'].dt.strftime('%H:%M')
        # Handle cases where strftime might fail if Entry Time is NaT
        df_result.loc[df_result['Entry Time'].isnull(), ['Entry Day', 'Entry HH:MM']] = np.nan


        rename_cols_exit = {'Date/Time': 'Exit Time'}
        if 'Signal' in df_result.columns: rename_cols_exit['Signal'] = 'Exit Type'
        else:
            st.info("ℹ️ ไม่พบคอลัมน์ 'Signal' ในข้อมูล Exit trades. 'Exit Type' จะถูกสร้างเป็นค่าว่าง.")
            df_result['Exit Type'] = np.nan
        df_result.rename(columns=rename_cols_exit, inplace=True)
        if 'Exit Type' not in df_result.columns: df_result['Exit Type'] = np.nan
    else:
        expected_cols_final = ['Trade #', 'Entry Day', 'Entry HH:MM', 'Entry Time', 'Entry Signal', 'Exit Time', 'Exit Type', 'P&L USD', 'Run-up USD', 'Drawdown USD', 'Risk USD', 'Profit(R)', 'MFE(R)', 'MAE(R)']
        df_result = pd.DataFrame(columns=expected_cols_final)
        for col in ['Entry Time', 'Exit Time']:
            if col in df_result.columns: df_result[col] = pd.to_datetime(df_result[col])
    desired_columns = ['Trade #', 'Entry Day', 'Entry HH:MM', 'Entry Time', 'Entry Signal', 'Exit Time', 'Exit Type', 'P&L USD', 'Run-up USD', 'Drawdown USD', 'Risk USD', 'Profit(R)', 'MFE(R)', 'MAE(R)']
    for col in desired_columns:
        if col not in df_result.columns:
            df_result[col] = pd.NaT if 'Time' in col else np.nan
    df_result = df_result[desired_columns]
    return df_result

def summarize_r_multiple_stats(df_result_input):
    if df_result_input is None or df_result_input.empty:
        st.warning("⚠️ ไม่สามารถคำนวณสถิติได้ เนื่องจากไม่มีข้อมูลเทรดที่ประมวลผลแล้ว (DataFrame ว่างเปล่า)")
        return {"Profit Factor": np.nan, "Net Profit (R)": 0, "Maximum Equity DD (R)": 0, "Net Profit to Max Drawdown Ratio": np.nan, "Drawdown Period (Days)": 0, "Total Trades": 0, "Winning Trades": 0, "Losing Trades": 0, "Breakeven Trades": 0, "Win %": np.nan, "BE %": np.nan, "Win+BE %": np.nan}
    df = df_result_input.copy()
    for col_name in ['Exit Time', 'Profit(R)']:
        if col_name not in df.columns:
            st.error(f"❌ ไม่พบคอลัมน์ '{col_name}' ใน DataFrame สำหรับการสรุปสถิติ.")
            return {stat: np.nan for stat in ["Profit Factor", "Net Profit (R)", "Maximum Equity DD (R)", "Net Profit to Max Drawdown Ratio", "Drawdown Period (Days)", "Total Trades", "Winning Trades", "Losing Trades", "Breakeven Trades", "Win %", "BE %", "Win+BE %"]}
    try: df['Exit Time'] = pd.to_datetime(df['Exit Time'], errors='coerce')
    except Exception as e: # Should be caught by errors='coerce' but as a fallback
        st.error(f"❌ ไม่สามารถแปลง 'Exit Time' เป็น datetime ได้: {e}")
        return {stat: np.nan for stat in ["Profit Factor", "Net Profit (R)", "Maximum Equity DD (R)", "Net Profit to Max Drawdown Ratio", "Drawdown Period (Days)", "Total Trades", "Winning Trades", "Losing Trades", "Breakeven Trades", "Win %", "BE %", "Win+BE %"]}
    
    df_valid = df.dropna(subset=['Profit(R)', 'Exit Time']).copy() # Also drop if Exit Time became NaT
    n_total = len(df_valid)
    if n_total == 0:
        st.info("ℹ️ ไม่มีเทรดที่มี Profit(R) และ Exit Time ที่ถูกต้องหลังจากกรอง NaN จึงไม่สามารถคำนวณสถิติ R-Multiple ได้")
        return {"Profit Factor": np.nan, "Net Profit (R)": 0, "Maximum Equity DD (R)": 0, "Net Profit to Max Drawdown Ratio": np.nan, "Drawdown Period (Days)": 0, "Total Trades": 0, "Winning Trades": 0, "Losing Trades": 0, "Breakeven Trades": 0, "Win %": 0, "BE %": 0, "Win+BE %": 0}
    n_win, n_loss, n_be = (df_valid['Profit(R)'] > 0).sum(), (df_valid['Profit(R)'] < 0).sum(), (np.isclose(df_valid['Profit(R)'], 0)).sum()
    win_sum, loss_sum = df_valid.loc[df_valid['Profit(R)'] > 0, 'Profit(R)'].sum(), df_valid.loc[df_valid['Profit(R)'] < 0, 'Profit(R)'].sum()
    profit_factor, net_profit_r = safe_divide(win_sum, abs(loss_sum)), df_valid['Profit(R)'].sum()
    df_valid = df_valid.sort_values(by='Exit Time').reset_index(drop=True)
    equity_curve, equity_high = df_valid['Profit(R)'].cumsum(), df_valid['Profit(R)'].cumsum().cummax()
    dd_curve, max_drawdown = equity_curve - equity_high, (equity_curve - equity_high).min() if not (equity_curve - equity_high).empty else 0
    np_dd_ratio = safe_divide(net_profit_r, abs(max_drawdown))
    dd_periods_days, current_dd_start_date = [], None
    if not df_valid.empty:
        in_dd_flag = (dd_curve < -1e-9)
        for idx in df_valid.index:
            if in_dd_flag[idx] and current_dd_start_date is None: current_dd_start_date = df_valid.loc[idx, 'Exit Time']
            elif not in_dd_flag[idx] and current_dd_start_date is not None:
                dd_end_date = df_valid.loc[idx-1, 'Exit Time'] if idx > 0 else current_dd_start_date
                days_in_dd = (dd_end_date - current_dd_start_date).days + 1 if pd.notnull(dd_end_date) and pd.notnull(current_dd_start_date) else 0
                dd_periods_days.append(days_in_dd)
                current_dd_start_date = None
        if current_dd_start_date is not None:
            dd_end_date = df_valid.loc[df_valid.index[-1], 'Exit Time']
            days_in_dd = (dd_end_date - current_dd_start_date).days + 1 if pd.notnull(dd_end_date) and pd.notnull(current_dd_start_date) else 0
            dd_periods_days.append(days_in_dd)
    max_dd_period_days = max(dd_periods_days) if dd_periods_days else 0
    win_pct, be_pct, winbe_pct = 100*safe_divide(n_win,n_total), 100*safe_divide(n_be,n_total), 100*safe_divide((n_win+n_be),n_total)
    return {"Profit Factor": profit_factor, "Net Profit (R)": net_profit_r, "Maximum Equity DD (R)": max_drawdown, "Net Profit to Max Drawdown Ratio": np_dd_ratio, "Drawdown Period (Days)": max_dd_period_days, "Total Trades": n_total, "Winning Trades": n_win, "Losing Trades": n_loss, "Breakeven Trades": n_be, "Win %": win_pct, "BE %": be_pct, "Win+BE %": winbe_pct}

# --- ส่วน UI หลักของ Streamlit ---
st.header("1. 📂 Data Preparation and Initial Analysis")
uploaded_file = st.file_uploader("กรุณาอัปโหลดไฟล์ Excel รายการเทรดของท่านพี่ (.xlsx)", type=["xlsx"], help="ไฟล์ควรมีชีทชื่อ 'List of trades' และ 'Properties' ตามรูปแบบที่กำหนดนะเจ้าคะ")
desired_stop_loss = st.number_input("ระบุ Stop Loss Percentage (เช่น 0.2% ให้ใส่ 0.002)", min_value=0.000001, max_value=0.999999, value=0.002, step=0.0001, format="%.6f", help="ค่า SL ต้องเป็นเลขทศนิยมที่มากกว่า 0 และน้อยกว่า 1")

if st.button("เริ่มการวิเคราะห์ชุดข้อมูลนี้ 🚀", help="กดปุ่มนี้หลังจากอัปโหลดไฟล์และตั้งค่า SL เรียบร้อยแล้ว"):
    if uploaded_file is not None:
        try:
            with open("temp_uploaded_trade_list.xlsx", "wb") as f: f.write(uploaded_file.getbuffer())
            excel_file_path_temp = "temp_uploaded_trade_list.xlsx"
            with st.spinner("กำลังประมวลผลข้อมูลการเทรดของท่านพี่... กรุณารอสักครู่เจ้าค่ะ... ⏳"):
                trade_results_df = calc_r_multiple_and_risk(excel_file_path_temp, desired_stop_loss)
            st.session_state['trade_results_df'] = trade_results_df
            st.success("ประมวลผลข้อมูลสำเร็จแล้วเจ้าค่ะ! 🎉")
            st.subheader("ตารางผลลัพธ์การเทรดเบื้องต้น (5 แถวแรก):")
            if trade_results_df is not None and not trade_results_df.empty:
                st.dataframe(trade_results_df.head())
                st.subheader("สรุปสถิติ R-Multiples โดยรวม:")
                summary_stats = summarize_r_multiple_stats(trade_results_df)
                if summary_stats:
                    col1, col2, col3 = st.columns(3)
                    stats_keys = list(summary_stats.keys())
                    def display_metric_safe(column, label, value):
                        display_val = "N/A" if pd.isna(value) else f"{value:.2f}" if isinstance(value, float) else str(value)
                        column.metric(label=label, value=display_val)
                    metrics_per_col = (len(stats_keys) + 2) // 3
                    current_col_idx, cols_ui = 0, [col1, col2, col3]
                    for i, key in enumerate(stats_keys):
                        display_metric_safe(cols_ui[current_col_idx], key, summary_stats[key])
                        if (i + 1) % metrics_per_col == 0 and current_col_idx < 2: current_col_idx += 1
                else: st.info("ℹ️ ไม่สามารถคำนวณสถิติสรุปได้.")
            elif trade_results_df is None: st.error("❌ เกิดข้อผิดพลาด: ฟังก์ชัน `calc_r_multiple_and_risk` ไม่ได้คืนค่า DataFrame.")
            else: st.info("ℹ️ ฟังก์ชัน `calc_r_multiple_and_risk` คืนค่าเป็น DataFrame ที่ว่างเปล่า.")
        except ValueError as ve: st.error(f"❌ ข้อมูล Input ไม่ถูกต้อง หรือมีปัญหาในการประมวลผลข้อมูล: {ve}")
        except RuntimeError as re: st.error(f"❌ เกิดข้อผิดพลาดขณะโหลดหรือประมวลผลไฟล์: {re}")
        except KeyError as ke: st.error(f"❌ ไม่พบคอลัมน์ที่สำคัญในไฟล์ Excel: {ke}.")
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}")
            st.exception(e)
            st.error("กรุณาตรวจสอบรูปแบบไฟล์ Excel และลองใหม่อีกครั้งนะเจ้าคะ หรือติดต่อผู้พัฒนาหากปัญหายังคงอยู่")
    else: st.warning("⚠️ กรุณาอัปโหลดไฟล์ Excel ก่อนกดปุ่มเริ่มการวิเคราะห์นะเจ้าคะ")

st.markdown("---")
st.caption("ℹ️ *หากท่านพี่อัปโหลดไฟล์ใหม่หรือเปลี่ยนค่า Stop Loss กรุณากดปุ่ม 'เริ่มการวิเคราะห์ฯ' อีกครั้งเพื่ออัปเดตผลลัพธ์ทั้งหมดนะเจ้าคะ*")

# --- ส่วนที่ 2: Equity Curve Analysis (All Trades) ---
if 'trade_results_df' in st.session_state and st.session_state['trade_results_df'] is not None and not st.session_state['trade_results_df'].empty:
    st.header("2. 📈 Overall Equity Curve Analysis")
    st.markdown("กราฟนี้แสดงผลกำไร/ขาดทุนสะสม (Cumulative R-Multiple) ของพอร์ตโดยรวมเมื่อเวลาผ่านไป พร้อมไฮไลท์ช่วงที่เกิด Drawdown ที่ยาวนานที่สุด 3 อันดับแรก")
    df_equity_all = st.session_state['trade_results_df'].copy()
    if 'Entry Time' not in df_equity_all.columns or 'Profit(R)' not in df_equity_all.columns:
        st.error("❌ ไม่พบคอลัมน์ 'Entry Time' หรือ 'Profit(R)' ที่จำเป็นสำหรับ Equity Curve.")
    
    try:
        df_equity_all['Entry Time'] = pd.to_datetime(df_equity_all['Entry Time'], errors='coerce')
    except Exception: 
        df_equity_all['Entry Time'] = pd.NaT
        
    df_equity_all.dropna(subset=['Entry Time', 'Profit(R)'], inplace=True)


    if not df_equity_all.empty:
        try:
            df_equity_all = df_equity_all.sort_values('Entry Time').reset_index(drop=True)
            df_equity_all['Entry Date'] = df_equity_all['Entry Time'].dt.normalize()
            df_equity_all['Profit(R)'] = df_equity_all['Profit(R)'].astype(float)
            df_equity_all['Cumulative R'] = df_equity_all['Profit(R)'].cumsum()
            equity_curve, high_water, drawdown = df_equity_all['Cumulative R'], df_equity_all['Cumulative R'].cummax(), df_equity_all['Cumulative R'] - df_equity_all['Cumulative R'].cummax()
            drawdown_periods_info, period_start_idx = [], None
            for i in df_equity_all.index:
                if drawdown.loc[i] < -1e-9 and period_start_idx is None: period_start_idx = i
                elif drawdown.loc[i] >= -1e-9 and period_start_idx is not None:
                    period_end_idx = i - 1 if i > 0 else 0
                    if period_start_idx <= period_end_idx:
                        start_date, end_date = df_equity_all.loc[period_start_idx, 'Entry Date'], df_equity_all.loc[period_end_idx, 'Entry Date']
                        if pd.notnull(start_date) and pd.notnull(end_date):
                            duration = (end_date - start_date).days + 1
                            period_dd_slice = drawdown.loc[period_start_idx : period_end_idx]
                            valley_r_value, valley_idx_in_df = period_dd_slice.min(), period_dd_slice.idxmin()
                            drawdown_periods_info.append({'start_idx': period_start_idx, 'end_idx': period_end_idx, 'start_date': start_date, 'end_date': end_date, 'duration': duration, 'valley_r': valley_r_value, 'valley_idx_in_df': valley_idx_in_df})
                    period_start_idx = None
            if period_start_idx is not None:
                period_end_idx = df_equity_all.index[-1]
                if period_start_idx <= period_end_idx:
                    start_date, end_date = df_equity_all.loc[period_start_idx, 'Entry Date'], df_equity_all.loc[period_end_idx, 'Entry Date']
                    if pd.notnull(start_date) and pd.notnull(end_date):
                        duration = (end_date - start_date).days + 1
                        period_dd_slice = drawdown.loc[period_start_idx : period_end_idx]
                        valley_r_value, valley_idx_in_df = period_dd_slice.min(), period_dd_slice.idxmin()
                        drawdown_periods_info.append({'start_idx': period_start_idx, 'end_idx': period_end_idx, 'start_date': start_date, 'end_date': end_date, 'duration': duration, 'valley_r': valley_r_value, 'valley_idx_in_df': valley_idx_in_df})
            drawdown_periods_info = sorted(drawdown_periods_info, key=lambda x: x['duration'], reverse=True)
            top_3_longest_dd = drawdown_periods_info[:min(3, len(drawdown_periods_info))]
            fig_eq_all, ax_eq_all = plt.subplots(figsize=(14, 7))
            ax_eq_all.plot(df_equity_all['Entry Date'], df_equity_all['Cumulative R'], label='Overall Equity Curve', color='dodgerblue', linewidth=2)
            dd_colors = ['salmon', 'lightgreen', 'lightskyblue']
            for i, dd_info in enumerate(top_3_longest_dd):
                if pd.notnull(dd_info['start_date']) and pd.notnull(dd_info['end_date']):
                    ax_eq_all.axvspan(dd_info['start_date'], dd_info['end_date'], color=dd_colors[i % len(dd_colors)], alpha=0.3, label=f"DD Period {i+1} ({dd_info['duration']} days)")
                    valley_date, valley_equity_r = df_equity_all.loc[dd_info['valley_idx_in_df'], 'Entry Date'], df_equity_all.loc[dd_info['valley_idx_in_df'], 'Cumulative R']
                    annotation_text = f"{dd_info['duration']}d, {dd_info['valley_r']:.2f}R"
                    ax_eq_all.annotate(annotation_text, xy=(valley_date, valley_equity_r), xytext=(0, -25 if valley_equity_r > 0 else 25), textcoords='offset points', ha='center', va='top' if valley_equity_r > 0 else 'bottom', fontsize=9, fontweight='bold', color='black', bbox=dict(boxstyle='round,pad=0.3', fc='ivory', alpha=0.75, ec='gray'))
            ax_eq_all.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=12))
            ax_eq_all.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.setp(ax_eq_all.get_xticklabels(), rotation=30, ha="right")
            ax_eq_all.set_xlabel('Entry Date'); ax_eq_all.set_ylabel('Cumulative Profit (R-Multiple)'); ax_eq_all.set_title('Overall Equity Curve with Longest Drawdown Periods Highlighted', fontsize=15)
            ax_eq_all.grid(True, linestyle=':', alpha=0.6); ax_eq_all.legend(fontsize='small'); ax_eq_all.axhline(0, color='grey', linestyle='--', linewidth=0.8)
            st.pyplot(fig_eq_all)
            if top_3_longest_dd:
                st.subheader("รายละเอียดช่วง Drawdown ที่ยาวนานที่สุด (Top 3):")
                dd_display_data = [{"อันดับ":i+1, "วันที่เริ่ม DD":dd['start_date'].strftime('%Y-%m-%d') if pd.notnull(dd['start_date']) else "N/A", "วันที่สิ้นสุด DD":dd['end_date'].strftime('%Y-%m-%d') if pd.notnull(dd['end_date']) else "N/A", "ระยะเวลา (วัน)":dd['duration'], "Drawdown สูงสุด (R)":f"{dd['valley_r']:.2f}"} for i, dd in enumerate(top_3_longest_dd)]
                st.table(pd.DataFrame(dd_display_data))
            else: st.info("✅ ยอดเยี่ยมมาก! ไม่พบช่วง Drawdown ที่มีนัยสำคัญในข้อมูลนี้เลยเจ้าค่ะ")
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาดในการสร้างกราฟ Equity Curve: {e}")
            st.exception(e)
    else: st.info("ℹ️ ไม่มีข้อมูลเทรดที่ถูกต้อง (หลังจากการกรอง NaN) สำหรับการสร้าง Overall Equity Curve.")

# --- ส่วนที่ 2A: Equity Curve Analysis by Day of the Week ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("2A. 🗓️ Equity Curve Analysis by Day of the Week")
    st.markdown("กราฟนี้แสดงผลกำไร/ขาดทุนสะสม (Cumulative R-Multiple) แยกตามวันที่เข้าเทรด (Entry Day) เพื่อดูประสิทธิภาพในแต่ละวันของสัปดาห์ พร้อมไฮไลท์ช่วง Drawdown ที่ยาวนานที่สุด 3 อันดับแรกของแต่ละวัน")

    df_equity_by_day_base = st.session_state['trade_results_df'].copy()
    df_equity_by_day_source = pd.DataFrame() 

    if 'Entry Time' not in df_equity_by_day_base.columns or 'Profit(R)' not in df_equity_by_day_base.columns:
        st.error("❌ ไม่พบคอลัมน์ 'Entry Time' หรือ 'Profit(R)' ที่จำเป็นสำหรับ Equity Curve by Day.")
    else:
        try:
            df_equity_by_day_base['Entry Time'] = pd.to_datetime(df_equity_by_day_base['Entry Time'], errors='coerce')
        except Exception as e: 
            st.error(f"เกิดข้อผิดพลาดในการแปลง 'Entry Time' เป็น datetime: {e}")
            df_equity_by_day_base['Entry Time'] = pd.NaT 

        original_rows = len(df_equity_by_day_base)
        df_equity_by_day_source = df_equity_by_day_base.dropna(subset=['Entry Time', 'Profit(R)']).copy()
        dropped_rows = original_rows - len(df_equity_by_day_source)
        if dropped_rows > 0:
            st.warning(f"⚠️ ได้ลบ {dropped_rows} แถว เนื่องจาก 'Entry Time' หรือ 'Profit(R)' เป็นค่าว่าง/ไม่ถูกต้อง ก่อนการวิเคราะห์รายวัน.")

    if df_equity_by_day_source.empty:
        st.info("ℹ️ ไม่มีข้อมูลเทรดที่สมบูรณ์ (หลังจากการกรองแถวที่มี 'Entry Time' หรือ 'Profit(R)' เป็นค่าว่าง) สำหรับการสร้าง Equity Curve by Day.")
    else:
        try:
            # Ensure 'Entry Day' and 'Entry Date' are correctly derived from valid 'Entry Time'
            df_equity_by_day_source['Entry Day'] = df_equity_by_day_source['Entry Time'].dt.day_name()
            df_equity_by_day_source['Entry Date'] = df_equity_by_day_source['Entry Time'].dt.normalize()
            df_equity_by_day_source.sort_values('Entry Time', inplace=True) # Sort once before looping

            day_order = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            unique_entry_days_in_data = df_equity_by_day_source['Entry Day'].dropna().unique()
            valid_days_for_plot = [day for day in day_order if day in unique_entry_days_in_data]
            
            if not valid_days_for_plot:
                st.info("ℹ️ ไม่มีวันที่มีการเทรดที่ถูกต้อง (หลังจากกรอง NaN และตรวจสอบวัน) สำหรับการสร้าง Equity Curve by Day.")
            else:
                num_days_to_plot = len(valid_days_for_plot)
                ncols_day = 2 
                nrows_day = (num_days_to_plot + ncols_day - 1) // ncols_day

                fig_eq_by_day, axes_eq_by_day = plt.subplots(nrows=nrows_day, ncols=ncols_day, figsize=(15, 6 * nrows_day), squeeze=False)
                axes_flat_day = axes_eq_by_day.flatten()
                plot_idx = 0
                trade_counts_by_day_list = []
                dd_colors_daily = ['#FFB6C1', '#ADD8E6', '#90EE90', '#FFDAB9', '#E6E6FA', '#F0E68C'] # Added more colors

                for day_name in valid_days_for_plot: 
                    df_day = df_equity_by_day_source[df_equity_by_day_source['Entry Day'] == day_name].copy()
                    
                    if df_day.empty: continue 

                    df_day = df_day.sort_values('Entry Time').reset_index(drop=True) 
                    df_day['Cumulative R'] = df_day['Profit(R)'].cumsum()
                    trade_counts_by_day_list.append({'Entry Day': day_name, '# of Trades': len(df_day)})

                    ax = axes_flat_day[plot_idx]
                    ax.plot(df_day['Entry Date'], df_day['Cumulative R'], label=f'{day_name} Equity', linewidth=1.5, color=sns.color_palette("husl", num_days_to_plot)[plot_idx])
                    
                    # --- Drawdown Calculation and Highlighting for each day ---
                    if not df_day.empty and len(df_day) > 1: # Need at least 2 trades for a meaningful DD period
                        equity_day_curve = df_day['Cumulative R']
                        high_water_day = equity_day_curve.cummax()
                        drawdown_day_values = equity_day_curve - high_water_day
                        
                        dd_periods_info_day = []
                        period_start_idx_day = None
                        for k_idx in df_day.index:
                            if drawdown_day_values.loc[k_idx] < -1e-9 and period_start_idx_day is None:
                                period_start_idx_day = k_idx
                            elif drawdown_day_values.loc[k_idx] >= -1e-9 and period_start_idx_day is not None:
                                period_end_idx_day = k_idx - 1 if k_idx > 0 else 0
                                if period_start_idx_day <= period_end_idx_day:
                                    start_d, end_d = df_day.loc[period_start_idx_day, 'Entry Date'], df_day.loc[period_end_idx_day, 'Entry Date']
                                    if pd.notnull(start_d) and pd.notnull(end_d):
                                        dur = (end_d - start_d).days + 1
                                        p_dd_slice = drawdown_day_values.loc[period_start_idx_day : period_end_idx_day]
                                        if not p_dd_slice.empty: # Ensure slice is not empty before min/idxmin
                                            val_r, val_idx = p_dd_slice.min(), p_dd_slice.idxmin()
                                            dd_periods_info_day.append({'start_date': start_d, 'end_date': end_d, 'duration': dur, 'valley_r': val_r, 'valley_idx_in_df': val_idx})
                                period_start_idx_day = None
                        if period_start_idx_day is not None: # Ongoing DD
                            period_end_idx_day = df_day.index[-1]
                            if period_start_idx_day <= period_end_idx_day:
                                start_d, end_d = df_day.loc[period_start_idx_day, 'Entry Date'], df_day.loc[period_end_idx_day, 'Entry Date']
                                if pd.notnull(start_d) and pd.notnull(end_d):
                                    dur = (end_d - start_d).days + 1
                                    p_dd_slice = drawdown_day_values.loc[period_start_idx_day : period_end_idx_day]
                                    if not p_dd_slice.empty:
                                        val_r, val_idx = p_dd_slice.min(), p_dd_slice.idxmin()
                                        dd_periods_info_day.append({'start_date': start_d, 'end_date': end_d, 'duration': dur, 'valley_r': val_r, 'valley_idx_in_df': val_idx})
                        
                        dd_periods_info_day = sorted(dd_periods_info_day, key=lambda x: x['duration'], reverse=True)
                        top_3_dd_day = dd_periods_info_day[:min(3, len(dd_periods_info_day))]

                        for dd_idx, dd_info_d in enumerate(top_3_dd_day):
                            if pd.notnull(dd_info_d['start_date']) and pd.notnull(dd_info_d['end_date']) and 'valley_idx_in_df' in dd_info_d:
                                ax.axvspan(dd_info_d['start_date'], dd_info_d['end_date'], color=dd_colors_daily[dd_idx % len(dd_colors_daily)], alpha=0.25)
                                valley_d, valley_eq_r_d = df_day.loc[dd_info_d['valley_idx_in_df'], 'Entry Date'], df_day.loc[dd_info_d['valley_idx_in_df'], 'Cumulative R']
                                ann_text_d = f"{dd_info_d['duration']}d, {dd_info_d['valley_r']:.2f}R"
                                ax.annotate(ann_text_d, xy=(valley_d, valley_eq_r_d), 
                                            xytext=(0, -20 if valley_eq_r_d > drawdown_day_values.min() else 20), 
                                            textcoords='offset points', ha='center', 
                                            va='top' if valley_eq_r_d > drawdown_day_values.min() else 'bottom', 
                                            fontsize=7, color='dimgray',
                                            bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.6, ec='lightgray'))
                    # --- End Drawdown for each day ---

                    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7)) 
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%y-%m-%d')) 
                    plt.setp(ax.get_xticklabels(which="major"), rotation=30, ha="right", fontsize=8)
                    
                    ax.set_title(f'{day_name}', fontsize=11) 
                    ax.set_xlabel('Date', fontsize=9)
                    ax.set_ylabel('Cum. R', fontsize=9)
                    ax.tick_params(axis='y', labelsize=8)
                    ax.grid(True, linestyle=':', alpha=0.4)
                    ax.axhline(0, color='grey', linestyle='--', linewidth=0.6)
                    ax.legend(fontsize='xx-small', loc='upper left')
                    plot_idx += 1

                for i in range(plot_idx, len(axes_flat_day)):
                    fig_eq_by_day.delaxes(axes_flat_day[i])

                fig_eq_by_day.tight_layout(pad=2.0, h_pad=3.0) 
                st.pyplot(fig_eq_by_day)

                if trade_counts_by_day_list:
                    st.subheader("สรุปจำนวนเทรดในแต่ละวัน (Entry Day):")
                    df_counts_display = pd.DataFrame(trade_counts_by_day_list)
                    df_counts_display['Entry Day'] = pd.Categorical(df_counts_display['Entry Day'], categories=day_order, ordered=True)
                    df_counts_display.sort_values('Entry Day', inplace=True)
                    st.table(df_counts_display.set_index('Entry Day'))
        
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาดในการสร้างกราฟ Equity Curve by Day: {e}")
            st.exception(e)
            
# else:
#     if 'button_pressed_flag' in st.session_state and st.session_state['button_pressed_flag']:
#        st.info("กรุณารอผลการประมวลผลข้อมูลจากขั้นตอนที่ 1 ก่อนนะเจ้าคะ หรือกดปุ่ม 'เริ่มการวิเคราะห์ฯ' หากยังไม่ได้ทำ")

# --- ส่วนที่ 3: Losing Streak Analysis ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("3. 📉 Losing Streak Analysis")
    st.markdown("การวิเคราะห์ช่วงที่ขาดทุนติดต่อกัน (Losing Streaks) เพื่อทำความเข้าใจความถี่และความยาวนานของช่วงเวลาที่ผลการเทรดไม่เป็นใจ")

    df_streak_source = st.session_state['trade_results_df'].copy()

    if 'Entry Time' not in df_streak_source.columns or 'Profit(R)' not in df_streak_source.columns:
        st.error("❌ ไม่พบคอลัมน์ 'Entry Time' หรือ 'Profit(R)' ที่จำเป็นสำหรับการวิเคราะห์ Losing Streak.")
    else:
        try:
            df_streak_source['Entry Time'] = pd.to_datetime(df_streak_source['Entry Time'], errors='coerce')
            df_streak_source.dropna(subset=['Entry Time', 'Profit(R)'], inplace=True) # Ensure valid data for streak calculation

            if df_streak_source.empty:
                st.info("ℹ️ ไม่มีข้อมูลเทรดที่สมบูรณ์สำหรับการวิเคราะห์ Losing Streak.")
            else:
                df_streak_source = df_streak_source.sort_values('Entry Time').reset_index(drop=True)
                
                # Ensure 'Entry Day' exists for streak table, derive if not
                if 'Entry Day' not in df_streak_source.columns:
                     df_streak_source['Entry Day'] = df_streak_source['Entry Time'].dt.day_name()


                df_streak_source['Is_Loss'] = df_streak_source['Profit(R)'] < 0
                
                # Shift with fill_value=False for boolean series
                df_streak_source['Streak_Start'] = df_streak_source['Is_Loss'] & (~df_streak_source['Is_Loss'].shift(1, fill_value=False))
                df_streak_source['Streak_End_Signal'] = ~df_streak_source['Is_Loss'] & (df_streak_source['Is_Loss'].shift(1, fill_value=False))

                losing_streaks_list = []
                current_streak_start_idx = None

                for index, row in df_streak_source.iterrows():
                    if row['Streak_Start']:
                        current_streak_start_idx = index
                    elif row['Streak_End_Signal'] and current_streak_start_idx is not None:
                        streak_end_idx = index - 1 
                        if streak_end_idx >= current_streak_start_idx : # Ensure valid range
                            streak_df_slice = df_streak_source.loc[current_streak_start_idx : streak_end_idx]
                            if not streak_df_slice.empty and streak_df_slice['Is_Loss'].all():
                                losing_streaks_list.append({
                                    'Start Date': streak_df_slice.iloc[0]['Entry Time'].date(),
                                    'End Date': streak_df_slice.iloc[-1]['Entry Time'].date(),
                                    'Length': len(streak_df_slice),
                                    'Entry Day of Week': streak_df_slice.iloc[0]['Entry Day'] 
                                })
                        current_streak_start_idx = None 
                
                if current_streak_start_idx is not None: # Handle ongoing streak at the end
                    streak_df_slice = df_streak_source.loc[current_streak_start_idx : ]
                    if not streak_df_slice.empty and streak_df_slice['Is_Loss'].all():
                        losing_streaks_list.append({
                            'Start Date': streak_df_slice.iloc[0]['Entry Time'].date(),
                            'End Date': streak_df_slice.iloc[-1]['Entry Time'].date(),
                            'Length': len(streak_df_slice),
                            'Entry Day of Week': streak_df_slice.iloc[0]['Entry Day']
                        })
                
                streaks_df = pd.DataFrame(losing_streaks_list)

                # --- 1. Losing Streaks Table ---
                st.subheader("ตารางสรุปช่วงเวลาที่ขาดทุนติดต่อกัน (Losing Streaks)")
                if streaks_df.empty:
                    st.info("🎉 ยอดเยี่ยม! ไม่พบช่วงเวลาการขาดทุนติดต่อกันในข้อมูลนี้")
                else:
                    day_order_table_streak = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
                    # Filter for display (e.g., Sun-Fri) - adjust if needed
                    streaks_df_display = streaks_df[streaks_df['Entry Day of Week'].isin(day_order_table_streak)].copy() 
                    if streaks_df_display.empty:
                        st.info("ℹ️ ไม่พบช่วงเวลาการขาดทุนที่เริ่มต้นในวันที่กำหนด (อาทิตย์-เสาร์) หรือข้อมูล 'Entry Day of Week' อาจมีปัญหา")
                    else:
                        streaks_df_display['Entry Day of Week'] = pd.Categorical(streaks_df_display['Entry Day of Week'], categories=day_order_table_streak, ordered=True)
                        streaks_df_display = streaks_df_display.sort_values(['Start Date', 'Entry Day of Week']).reset_index(drop=True)
                        st.dataframe(streaks_df_display)

                # --- 2. Histogram of Streak Lengths ---
                st.subheader("กราฟ Histogram แสดงความถี่ของความยาวช่วงที่ขาดทุนติดต่อกัน")
                if streaks_df.empty or 'Length' not in streaks_df.columns or streaks_df['Length'].empty:
                    st.info("ℹ️ ไม่มีข้อมูลความยาวของช่วงขาดทุนสำหรับสร้าง Histogram")
                else:
                    fig_streak_hist, ax_streak_hist = plt.subplots(figsize=(10, 6))
                    max_len_streak = streaks_df['Length'].max() if not streaks_df['Length'].empty else 1
                    # Ensure bins cover the range and are integer-centered
                    if max_len_streak > 0 :
                        bins_streak = np.arange(0.5, streaks_df['Length'].max() + 1.5, 1)
                    else: # Handle case with no streaks or max_len_streak is 0 or less
                        bins_streak = np.arange(0.5, 1.5, 1)


                    sns.histplot(data=streaks_df, x='Length', bins=bins_streak, color='#F08080', edgecolor='white', alpha=0.8, ax=ax_streak_hist)
                    
                    # Annotation for counts on bars
                    # Iterate over the patches (bars) of the histogram
                    for p in ax_streak_hist.patches:
                        height = p.get_height()
                        if height > 0: # Only annotate bars with count > 0
                            ax_streak_hist.annotate(f'{int(height)}', 
                                            (p.get_x() + p.get_width() / 2., height), 
                                            ha = 'center', va = 'center', 
                                            xytext = (0, 5), 
                                            textcoords = 'offset points',
                                            fontsize=8, color='black')

                    ax_streak_hist.set_xticks(np.arange(1, max_len_streak + 1))
                    ax_streak_hist.set_xlabel('ความยาวของช่วงขาดทุนติดต่อกัน (จำนวนเทรด)')
                    ax_streak_hist.set_ylabel('ความถี่')
                    ax_streak_hist.set_title('Histogram of Losing Streak Lengths')
                    ax_streak_hist.grid(axis='y', linestyle='--', alpha=0.5)
                    st.pyplot(fig_streak_hist)

                # --- 3. Timeline Scatter Plot ---
                st.subheader("กราฟ Scatter แสดงความยาวของช่วงขาดทุนตามช่วงเวลาที่เริ่มเกิด")
                if streaks_df.empty or 'Start Date' not in streaks_df.columns or 'Length' not in streaks_df.columns:
                    st.info("ℹ️ ไม่มีข้อมูลสำหรับสร้าง Scatter Plot ของช่วงขาดทุน")
                else:
                    # Ensure 'Start Date' is datetime for plotting
                    streaks_df_plot_scatter = streaks_df.copy()
                    streaks_df_plot_scatter['Start Date'] = pd.to_datetime(streaks_df_plot_scatter['Start Date'])

                    fig_streak_scatter, ax_streak_scatter = plt.subplots(figsize=(12, 6))
                    ax_streak_scatter.scatter(streaks_df_plot_scatter['Start Date'], streaks_df_plot_scatter['Length'], color='#4682B4', alpha=0.7, s=50)
                    
                    ax_streak_scatter.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                    plt.setp(ax_streak_scatter.get_xticklabels(), rotation=30, ha="right")
                    ax_streak_scatter.set_xlabel('วันที่เริ่มช่วงขาดทุน')
                    ax_streak_scatter.set_ylabel('ความยาวของช่วงขาดทุน')
                    ax_streak_scatter.set_title('Losing Streak Lengths Over Time')
                    ax_streak_scatter.grid(True, linestyle=':', alpha=0.6)
                    # Improve y-axis ticks
                    if not streaks_df_plot_scatter['Length'].empty:
                         max_len_scatter = streaks_df_plot_scatter['Length'].max()
                         ax_streak_scatter.set_yticks(np.arange(0, max_len_scatter + 2, 1 if max_len_scatter < 10 else (max_len_scatter // 10) or 1))


                    st.pyplot(fig_streak_scatter)
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาดในการวิเคราะห์ Losing Streak: {e}")
            st.exception(e)
# else:
#     if 'button_pressed_flag' in st.session_state and st.session_state['button_pressed_flag']:
#        st.info("กรุณารอผลการประมวลผลข้อมูลจากขั้นตอนที่ 1 ก่อนนะเจ้าคะ หรือกดปุ่ม 'เริ่มการวิเคราะห์ฯ' หากยังไม่ได้ทำ")

# --- ส่วนที่ 4: Profit(R) Distribution - All Trades (จากไฟล์ 04.ProfitHistogram_Allday.py) ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("4. 📊 Profit(R) Distribution - All Trades")
    st.markdown("Histogram นี้แสดงการกระจายตัวของผลกำไร/ขาดทุน (R-Multiple) จากทุกเทรด")

    df_profit_hist_all_source = st.session_state['trade_results_df'].copy()

    if 'Profit(R)' not in df_profit_hist_all_source.columns:
        st.error("❌ ไม่พบคอลัมน์ 'Profit(R)' ที่จำเป็นสำหรับการสร้าง Profit Histogram.")
    else:
        # Drop rows where Profit(R) is NaN, as they cannot be plotted or used in calculations
        df_profit_hist_all_valid = df_profit_hist_all_source.dropna(subset=['Profit(R)']).copy()

        if df_profit_hist_all_valid.empty:
            st.info("ℹ️ ไม่มีข้อมูลเทรดที่มี Profit(R) ที่ถูกต้อง (หลังจากการกรอง NaN) สำหรับการสร้าง Profit Histogram.")
        else:
            try:
                r_values_all = df_profit_hist_all_valid['Profit(R)'].astype(float) # Ensure float for calculations

                # Calculate Metrics for all trades
                expectancy_all = r_values_all.mean()
                win_mask_all = r_values_all > 0
                loss_mask_all = r_values_all < 0
                n_win_all = win_mask_all.sum()
                n_loss_all = loss_mask_all.sum()
                total_trades_all = len(r_values_all)
                win_rate_all = 100 * safe_divide(n_win_all, total_trades_all)
                
                r_values_win_all = r_values_all[win_mask_all]
                r_values_loss_all = r_values_all[loss_mask_all]
                avg_win_all = r_values_win_all.mean() if not r_values_win_all.empty else np.nan
                avg_loss_all = r_values_loss_all.mean() if not r_values_loss_all.empty else np.nan # Will be negative

                # Plot Histogram
                fig_profit_hist, ax_profit_hist = plt.subplots(figsize=(12, 6))
                
                # Determine bins - simple heuristic or fixed number
                num_bins_all = min(50, max(10, int(np.sqrt(total_trades_all) * 2))) if total_trades_all > 0 else 10
                
                ax_profit_hist.hist(r_values_win_all, bins=num_bins_all, color='deepskyblue', alpha=0.7, label=f'Wins (n={n_win_all})', edgecolor='white')
                ax_profit_hist.hist(r_values_loss_all, bins=num_bins_all, color='salmon', alpha=0.7, label=f'Losses (n={n_loss_all})', edgecolor='white')

                if pd.notnull(expectancy_all):
                    ax_profit_hist.axvline(expectancy_all, color='purple', linestyle='dashed', linewidth=1.5, label=f'Expectancy ({expectancy_all:.2f} R)')

                ax_profit_hist.set_title('Distribution of Trade R-Multiples (All Trades)', fontsize=14)
                ax_profit_hist.set_xlabel('Profit(R)', fontsize=12)
                ax_profit_hist.set_ylabel('Frequency', fontsize=12)
                ax_profit_hist.legend(fontsize='small')
                ax_profit_hist.grid(axis='y', linestyle=':', alpha=0.6)
                st.pyplot(fig_profit_hist)

                # Display Summary Statistics Table for All Trades
                st.subheader("สรุปสถิติ R-Multiple Performance (All Trades):")
                summary_stats_all = {
                    "Expectancy (R)": expectancy_all,
                    "Win Rate (%)": win_rate_all,
                    "Avg Win (R)": avg_win_all,
                    "Avg Loss (R)": avg_loss_all, # This will be negative
                    "Number of Wins": n_win_all,
                    "Number of Losses": n_loss_all,
                    "Total Trades": total_trades_all
                }
                # For better display, can use st.columns or st.table
                summary_df_all = pd.DataFrame([summary_stats_all])
                # Format for display
                for col in ["Expectancy (R)", "Win Rate (%)", "Avg Win (R)", "Avg Loss (R)"]:
                    if col in summary_df_all.columns:
                         summary_df_all[col] = summary_df_all[col].map(lambda x: f"{x:.2f}" if pd.notnull(x) else "N/A")
                st.table(summary_df_all)

            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาดในการสร้าง Profit Histogram (All Trades): {e}")
                st.exception(e)

# --- ส่วนที่ 4A: Profit(R) Distribution by Entry Day (จากไฟล์ 04A.ProfitHistogram_byDay.py) ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("4A. 📅 Profit(R) Distribution by Entry Day")
    st.markdown("Histograms นี้แสดงการกระจายตัวของผลกำไร/ขาดทุน (R-Multiple) แยกตามวันที่เข้าเทรด")

    df_profit_hist_day_base = st.session_state['trade_results_df'].copy()

    if 'Entry Time' not in df_profit_hist_day_base.columns or \
       'Profit(R)' not in df_profit_hist_day_base.columns :
        st.error("❌ ไม่พบคอลัมน์ 'Entry Time' หรือ 'Profit(R)' ที่จำเป็นสำหรับการสร้าง Profit Histogram by Day.")
    else:
        try:
            df_profit_hist_day_base['Entry Time'] = pd.to_datetime(df_profit_hist_day_base['Entry Time'], errors='coerce')
            df_profit_hist_day_base.dropna(subset=['Entry Time', 'Profit(R)'], inplace=True) # Drop essential NaNs

            if df_profit_hist_day_base.empty:
                st.info("ℹ️ ไม่มีข้อมูลเทรดที่สมบูรณ์สำหรับการสร้าง Profit Histogram by Day.")
            else:
                # Ensure 'Entry Day' exists or derive it
                if 'Entry Day' not in df_profit_hist_day_base.columns:
                    df_profit_hist_day_base['Entry Day'] = df_profit_hist_day_base['Entry Time'].dt.day_name()
                
                # Drop rows where 'Entry Day' is NaN after derivation (if 'Entry Time' was NaT)
                df_profit_hist_day_base.dropna(subset=['Entry Day'], inplace=True)


                day_order_profit_hist = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
                unique_days_profit_hist = df_profit_hist_day_base['Entry Day'].unique()
                valid_days_for_profit_hist_plot = [day for day in day_order_profit_hist if day in unique_days_profit_hist]

                if not valid_days_for_profit_hist_plot:
                    st.info("ℹ️ ไม่มีวันที่มีการเทรดที่ถูกต้องสำหรับการสร้าง Profit Histogram by Day.")
                else:
                    num_days_ph = len(valid_days_for_profit_hist_plot)
                    ncols_ph = 2
                    nrows_ph = (num_days_ph + ncols_ph - 1) // ncols_ph

                    fig_ph_by_day, axes_ph_by_day = plt.subplots(nrows=nrows_ph, ncols=ncols_ph, figsize=(15, 5 * nrows_ph), squeeze=False)
                    axes_flat_ph = axes_ph_by_day.flatten()
                    plot_idx_ph = 0
                    daily_summary_stats_list_ph = []

                    for day_name_ph in valid_days_for_profit_hist_plot:
                        df_day_ph = df_profit_hist_day_base[df_profit_hist_day_base['Entry Day'] == day_name_ph].copy()
                        
                        if df_day_ph.empty or df_day_ph['Profit(R)'].isnull().all(): continue

                        r_values_day_ph = df_day_ph['Profit(R)'].astype(float)
                        
                        # Calculate metrics for this day
                        n_win_day_ph = (r_values_day_ph > 0).sum()
                        n_loss_day_ph = (r_values_day_ph < 0).sum()
                        total_trades_day_ph = len(r_values_day_ph)
                        expectancy_day_ph = r_values_day_ph.mean() if total_trades_day_ph > 0 else np.nan
                        win_rate_day_ph = 100 * safe_divide(n_win_day_ph, total_trades_day_ph)
                        
                        r_win_day_ph = r_values_day_ph[r_values_day_ph > 0]
                        r_loss_day_ph = r_values_day_ph[r_values_day_ph < 0]
                        avg_win_day_ph = r_win_day_ph.mean() if not r_win_day_ph.empty else np.nan
                        avg_loss_day_ph = r_loss_day_ph.mean() if not r_loss_day_ph.empty else np.nan

                        daily_summary_stats_list_ph.append({
                            "Entry Day": day_name_ph,
                            "Expectancy (R)": expectancy_day_ph,
                            "Win Rate (%)": win_rate_day_ph,
                            "Avg Win (R)": avg_win_day_ph,
                            "Avg Loss (R)": avg_loss_day_ph,
                            "Number of Wins": n_win_day_ph,
                            "Number of Losses": n_loss_day_ph,
                            "Total Trades": total_trades_day_ph
                        })

                        ax_ph = axes_flat_ph[plot_idx_ph]
                        num_bins_day_ph = min(30, max(5, int(np.sqrt(total_trades_day_ph)))) if total_trades_day_ph > 0 else 5
                        
                        ax_ph.hist(r_win_day_ph, bins=num_bins_day_ph, color='deepskyblue', alpha=0.7, label=f'Wins (n={n_win_day_ph})', edgecolor='white')
                        ax_ph.hist(r_loss_day_ph, bins=num_bins_day_ph, color='salmon', alpha=0.7, label=f'Losses (n={n_loss_day_ph})', edgecolor='white')

                        if pd.notnull(expectancy_day_ph):
                            ax_ph.axvline(expectancy_day_ph, color='purple', linestyle='dashed', linewidth=1.2, label=f'Exp. ({expectancy_day_ph:.2f}R)')
                        
                        ax_ph.set_title(f'{day_name_ph} R-Multiple Distribution', fontsize=11)
                        ax_ph.set_xlabel('Profit(R)', fontsize=9)
                        ax_ph.set_ylabel('Frequency', fontsize=9)
                        ax_ph.tick_params(axis='both', which='major', labelsize=8)
                        ax_ph.legend(fontsize='xx-small')
                        ax_ph.grid(axis='y', linestyle=':', alpha=0.5)
                        plot_idx_ph += 1

                    for i in range(plot_idx_ph, len(axes_flat_ph)):
                        fig_ph_by_day.delaxes(axes_flat_ph[i])
                    
                    fig_ph_by_day.tight_layout(pad=2.0, h_pad=3.0)
                    st.pyplot(fig_ph_by_day)

                    if daily_summary_stats_list_ph:
                        st.subheader("สรุปสถิติ R-Multiple Performance รายวัน:")
                        daily_stats_df_ph = pd.DataFrame(daily_summary_stats_list_ph)
                        daily_stats_df_ph['Entry Day'] = pd.Categorical(daily_stats_df_ph['Entry Day'], categories=day_order_profit_hist, ordered=True)
                        daily_stats_df_ph = daily_stats_df_ph.sort_values('Entry Day').set_index("Entry Day")
                        
                        # Formatting for display
                        format_dict = {
                            "Expectancy (R)": "{:.2f}", "Win Rate (%)": "{:.2f}%",
                            "Avg Win (R)": "{:.2f}", "Avg Loss (R)": "{:.2f}"
                        }
                        st.table(daily_stats_df_ph.style.format(format_dict, na_rep="N/A"))
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาดในการสร้าง Profit Histogram by Day: {e}")
            st.exception(e)

# --- ส่วนที่ 5: Trade Count by Entry Day (จากไฟล์ 05.TradeCount_byEntryDay.py) ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("5. 🗓️ Trade Count by Entry Day")
    st.markdown("กราฟแท่งและตารางนี้แสดงจำนวนเทรด (Win, Loss, Breakeven) และเปอร์เซ็นต์เทียบกับจำนวนเทรดทั้งหมดในแต่ละวัน โดยพิจารณาจากวันเข้าเทรด (Entry Day) เฉพาะวันอาทิตย์ถึงวันศุกร์")

    df_tc_entry_day_base = st.session_state['trade_results_df'].copy()

    if 'Entry Time' not in df_tc_entry_day_base.columns or 'Profit(R)' not in df_tc_entry_day_base.columns:
        st.error("❌ ไม่พบคอลัมน์ 'Entry Time' หรือ 'Profit(R)' ที่จำเป็นสำหรับการวิเคราะห์ Trade Count by Entry Day.")
    else:
        try:
            df_tc_entry_day_base['Entry Time'] = pd.to_datetime(df_tc_entry_day_base['Entry Time'], errors='coerce')
            df_tc_entry_day_base.dropna(subset=['Entry Time', 'Profit(R)'], inplace=True)

            if df_tc_entry_day_base.empty:
                st.info("ℹ️ ไม่มีข้อมูลเทรดที่สมบูรณ์สำหรับการวิเคราะห์ Trade Count by Entry Day.")
            else:
                if 'Entry Day' not in df_tc_entry_day_base.columns: # Ensure 'Entry Day' exists
                    df_tc_entry_day_base['Entry Day'] = df_tc_entry_day_base['Entry Time'].dt.day_name()
                df_tc_entry_day_base.dropna(subset=['Entry Day'], inplace=True) # Drop if Entry Day is NaN

                # Categorize trades by result
                df_tc_entry_day_base['Result Type'] = 'Breakeven' # Default
                df_tc_entry_day_base.loc[df_tc_entry_day_base['Profit(R)'] > 0, 'Result Type'] = 'Win'
                df_tc_entry_day_base.loc[df_tc_entry_day_base['Profit(R)'] < 0, 'Result Type'] = 'Loss'

                day_order_tc = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] # Sun-Fri
                result_order_tc = ['Win', 'Loss', 'Breakeven']
                
                # Filter for relevant days before grouping
                df_tc_entry_day_filtered = df_tc_entry_day_base[df_tc_entry_day_base['Entry Day'].isin(day_order_tc)].copy()

                if df_tc_entry_day_filtered.empty:
                    st.info(f"ℹ️ ไม่พบข้อมูลเทรดที่เข้าเงื่อนไขวัน (อาทิตย์-ศุกร์) สำหรับ Trade Count by Entry Day.")
                else:
                    trade_counts_entry_day = df_tc_entry_day_filtered.groupby(['Entry Day', 'Result Type'], observed=False).size().unstack(fill_value=0) # Use observed=False for older pandas
                    
                    # Ensure all desired days and result types are present
                    for day in day_order_tc:
                        if day not in trade_counts_entry_day.index:
                            trade_counts_entry_day.loc[day] = 0
                    for res in result_order_tc:
                        if res not in trade_counts_entry_day.columns:
                            trade_counts_entry_day[res] = 0
                    
                    trade_counts_entry_day = trade_counts_entry_day.reindex(day_order_tc) # Order rows
                    trade_counts_entry_day = trade_counts_entry_day[result_order_tc] # Order columns
                    trade_counts_entry_day['Total'] = trade_counts_entry_day.sum(axis=1)

                    # --- Plotting ---
                    fig_tc_day, ax_tc_day = plt.subplots(figsize=(12, 7))
                    bar_width = 0.25
                    x_tc_day = np.arange(len(day_order_tc))
                    
                    colors_tc = {'Win': 'deepskyblue', 'Loss': 'salmon', 'Breakeven': '#b0b0b0'}

                    rects1_tc = ax_tc_day.bar(x_tc_day - bar_width, trade_counts_entry_day['Win'], bar_width, label='Win', color=colors_tc['Win'])
                    rects2_tc = ax_tc_day.bar(x_tc_day, trade_counts_entry_day['Loss'], bar_width, label='Loss', color=colors_tc['Loss'])
                    rects3_tc = ax_tc_day.bar(x_tc_day + bar_width, trade_counts_entry_day['Breakeven'], bar_width, label='Breakeven', color=colors_tc['Breakeven'])

                    def add_labels_trade_count(rects, result_type_name, counts_df, ax_plot):
                        for i, rect in enumerate(rects):
                            height = rect.get_height()
                            total_day = counts_df.iloc[i]['Total']
                            if height > 0 or total_day > 0: # Show label even if height is 0 but total exists
                                percentage = (height / total_day) * 100 if total_day > 0 else 0
                                ax_plot.annotate(f'{int(height)}\n({percentage:.1f}%)',
                                                xy=(rect.get_x() + rect.get_width() / 2, height),
                                                xytext=(0, 3), textcoords="offset points",
                                                ha='center', va='bottom', fontsize=8, color=colors_tc[result_type_name])
                    
                    add_labels_trade_count(rects1_tc, 'Win', trade_counts_entry_day, ax_tc_day)
                    add_labels_trade_count(rects2_tc, 'Loss', trade_counts_entry_day, ax_tc_day)
                    add_labels_trade_count(rects3_tc, 'Breakeven', trade_counts_entry_day, ax_tc_day)

                    ax_tc_day.set_xlabel('Entry Day of Week')
                    ax_tc_day.set_ylabel('Number of Trades')
                    ax_tc_day.set_title('Trade Counts by Entry Day and Result Type (Sun-Fri)')
                    ax_tc_day.set_xticks(x_tc_day)
                    ax_tc_day.set_xticklabels(day_order_tc)
                    ax_tc_day.legend(title='Result Type')
                    ax_tc_day.grid(axis='y', linestyle='--', alpha=0.7)
                    ax_tc_day.set_ylim(0, trade_counts_entry_day[result_order_tc].max().max() * 1.25) # Adjust for labels
                    st.pyplot(fig_tc_day)

                    # --- Summary Table ---
                    st.subheader("ตารางสรุป Trade Counts and Percentage by Entry Day (Sun-Fri)")
                    summary_data_tc_day = []
                    for day_code_tc in day_order_tc:
                        if day_code_tc in trade_counts_entry_day.index:
                            day_counts_tc = trade_counts_entry_day.loc[day_code_tc]
                            total_trades_day_tc = day_counts_tc['Total']
                            row_data_tc = {'Entry Day': day_code_tc}
                            for res_type_tc in result_order_tc:
                                count_tc = day_counts_tc[res_type_tc]
                                percentage_tc = (count_tc / total_trades_day_tc) * 100 if total_trades_day_tc > 0 else 0
                                row_data_tc[f'{res_type_tc} Count'] = int(count_tc)
                                row_data_tc[f'{res_type_tc} %'] = f"{percentage_tc:.1f}%"
                            row_data_tc['Total Trades'] = int(total_trades_day_tc)
                            summary_data_tc_day.append(row_data_tc)
                    
                    summary_df_tc_day = pd.DataFrame(summary_data_tc_day)
                    if not summary_df_tc_day.empty:
                        st.table(summary_df_tc_day.set_index('Entry Day'))
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาดในการวิเคราะห์ Trade Count by Entry Day: {e}")
            st.exception(e)


# --- ส่วนที่ 6 & 7: Trade Count by Entry/Exit Time of Day (NeedINPUT_binsize) ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("6 & 7. ⏰ Trade Count by Time of Day (Entry & Exit)")
    st.markdown("วิเคราะห์จำนวนเทรดตามช่วงเวลาของวัน โดยสามารถปรับขนาดของช่วงเวลา (Bin size) ได้ และจะมีการข้ามช่วงเวลา 12:00-19:30 น.")

    # --- Function to create Time of Day plots and tables ---
    def plot_trade_count_by_time_of_day(df_source, time_column_name, plot_title_prefix, bin_size_minutes_input, key_suffix):
        df_plot_time = df_source.copy()

        if time_column_name not in df_plot_time.columns or 'Profit(R)' not in df_plot_time.columns:
            st.error(f"❌ ไม่พบคอลัมน์ '{time_column_name}' หรือ 'Profit(R)' สำหรับ {plot_title_prefix}.")
            return

        df_plot_time[time_column_name] = pd.to_datetime(df_plot_time[time_column_name], errors='coerce')
        df_plot_time.dropna(subset=[time_column_name, 'Profit(R)'], inplace=True)

        if df_plot_time.empty:
            st.info(f"ℹ️ ไม่มีข้อมูลเทรดที่สมบูรณ์สำหรับ {plot_title_prefix} หลังจากกรอง NaN.")
            return
        
        try:
            df_plot_time['Time of Day Seconds'] = (df_plot_time[time_column_name].dt.hour * 3600 +
                                               df_plot_time[time_column_name].dt.minute * 60 +
                                               df_plot_time[time_column_name].dt.second)
            df_plot_time['Result Type'] = 'Breakeven'
            df_plot_time.loc[df_plot_time['Profit(R)'] > 0, 'Result Type'] = 'Win'
            df_plot_time.loc[df_plot_time['Profit(R)'] < 0, 'Result Type'] = 'Loss'

            bin_size_seconds = bin_size_minutes_input * 60
            total_seconds_in_day = 24 * 3600
            time_bins = np.arange(0, total_seconds_in_day + bin_size_seconds, bin_size_seconds)
            time_bin_labels = []
            for i in range(len(time_bins) - 1):
                start_t = pd.to_datetime(time_bins[i], unit='s').strftime('%H:%M')
                end_s = time_bins[i+1] -1 
                end_t = '23:59' if end_s >= total_seconds_in_day else pd.to_datetime(end_s, unit='s').strftime('%H:%M')
                time_bin_labels.append(f"{start_t}-{end_t}")
            
            df_plot_time['Time Bin'] = pd.cut(df_plot_time['Time of Day Seconds'], bins=time_bins, labels=time_bin_labels, right=False, include_lowest=True)
            
            trade_counts_time_all_bins = df_plot_time.groupby(['Time Bin', 'Result Type'], observed=False).size().unstack(fill_value=0) # Use observed=False
            trade_counts_time_all_bins = trade_counts_time_all_bins.reindex(time_bin_labels, fill_value=0)
            result_order_time = ['Win', 'Loss', 'Breakeven']
            for res_t in result_order_time:
                if res_t not in trade_counts_time_all_bins.columns: trade_counts_time_all_bins[res_t] = 0
            trade_counts_time_all_bins = trade_counts_time_all_bins[result_order_time]
            trade_counts_time_all_bins['Total'] = trade_counts_time_all_bins.sum(axis=1)

            # Filter for time range (skip 12:00 - 19:30)
            # This filtering logic for time can be tricky with bins.
            # A simpler approach is to filter the labels that should be displayed.
            filtered_bin_labels_display = []
            for label in time_bin_labels:
                start_hour = int(label.split('-')[0].split(':')[0])
                start_minute = int(label.split('-')[0].split(':')[1])
                # Skip if start_hour is between 12 and 18 (inclusive)
                # Skip if start_hour is 19 and start_minute is less than 30
                if (start_hour >= 12 and start_hour < 19) or (start_hour == 19 and start_minute < 30):
                    continue
                filtered_bin_labels_display.append(label)
            
            trade_counts_time_filtered = trade_counts_time_all_bins.loc[filtered_bin_labels_display].copy()


            if trade_counts_time_filtered.empty:
                st.info(f"ℹ️ ไม่มีข้อมูลเทรดในกรอบเวลาที่แสดง (หลังจากการข้ามช่วง 12:00-19:30) สำหรับ {plot_title_prefix}")
                return

            # Plotting
            st.subheader(f"กราฟ: {plot_title_prefix} ({bin_size_minutes_input}-min bins, 12:00-19:30 Skipped)")
            fig_time, ax_time = plt.subplots(figsize=(18, 8))
            x_time_filt = np.arange(len(trade_counts_time_filtered))
            bar_width_time = 0.25
            colors_tc_time = {'Win': 'deepskyblue', 'Loss': 'salmon', 'Breakeven': '#b0b0b0'}

            ax_time.bar(x_time_filt - bar_width_time, trade_counts_time_filtered['Win'], bar_width_time, label='Win', color=colors_tc_time['Win'])
            ax_time.bar(x_time_filt, trade_counts_time_filtered['Loss'], bar_width_time, label='Loss', color=colors_tc_time['Loss'])
            ax_time.bar(x_time_filt + bar_width_time, trade_counts_time_filtered['Breakeven'], bar_width_time, label='Breakeven', color=colors_tc_time['Breakeven'])

            ax_time.set_xlabel(f'{plot_title_prefix} ({bin_size_minutes_input}-min bins)')
            ax_time.set_ylabel('Number of Trades')
            ax_time.set_title(f'Trade Counts by {plot_title_prefix} ({bin_size_minutes_input}-min bins, 12:00-19:30 Skipped)')
            ax_time.set_xticks(x_time_filt)
            ax_time.set_xticklabels(trade_counts_time_filtered.index, rotation=45, ha='right', fontsize=8)
            ax_time.legend(title='Result Type')
            ax_time.grid(axis='y', linestyle='--', alpha=0.7)
            ax_time.set_ylim(0, trade_counts_time_filtered[result_order_time].max().max() * 1.15)
            st.pyplot(fig_time)

            # Summary Table
            st.subheader(f"ตารางสรุป: {plot_title_prefix} ({bin_size_minutes_input}-min bins, 12:00-19:30 Skipped)")
            summary_data_time_filt_list = []
            for t_bin, row_cts in trade_counts_time_filtered.iterrows():
                total_t_bin = row_cts['Total']
                row_d_t = {'Time Bin': t_bin}
                for res_t_t in result_order_time:
                    ct_t = row_cts[res_t_t]
                    perc_t = (ct_t / total_t_bin) * 100 if total_t_bin > 0 else 0
                    row_d_t[f'{res_t_t} Count'] = int(ct_t)
                    row_d_t[f'{res_t_t} %'] = f"{perc_t:.1f}%"
                row_d_t['Total Trades'] = int(total_t_bin)
                summary_data_time_filt_list.append(row_d_t)
            
            summary_df_time_filt = pd.DataFrame(summary_data_time_filt_list)
            if not summary_df_time_filt.empty:
                st.table(summary_df_time_filt.set_index('Time Bin'))

        except Exception as e_time:
            st.error(f"❌ เกิดข้อผิดพลาดในการวิเคราะห์ {plot_title_prefix}: {e_time}")
            st.exception(e_time)

    # --- UI for Entry Time Analysis (06) ---
    st.markdown("### 6. วิเคราะห์ตามเวลาเข้าเทรด (Entry Time)")
    bin_size_entry_time_input = st.number_input(
        "เลือกขนาด Bin สำหรับเวลาเข้าเทรด (นาที):", 
        min_value=1, max_value=120, value=10, step=1, 
        key="bin_entry_time",
        help="ขนาดของแต่ละช่วงเวลาที่จะใช้ในการจัดกลุ่มข้อมูล เช่น 10 นาที, 30 นาที, 60 นาที"
    )
    plot_trade_count_by_time_of_day(st.session_state['trade_results_df'], 'Entry Time', 'Entry Time of Day', bin_size_entry_time_input, "entry")
    
    st.markdown("---")
    # --- UI for Exit Time Analysis (07) ---
    st.markdown("### 7. วิเคราะห์ตามเวลาออกจากเทรด (Exit Time)")
    bin_size_exit_time_input = st.number_input(
        "เลือกขนาด Bin สำหรับเวลาออกจากเทรด (นาที):", 
        min_value=1, max_value=120, value=60, step=1, 
        key="bin_exit_time",
        help="ขนาดของแต่ละช่วงเวลาที่จะใช้ในการจัดกลุ่มข้อมูล"
    )
    # Ensure 'Exit Time' column exists before calling
    if 'Exit Time' in st.session_state['trade_results_df'].columns:
        plot_trade_count_by_time_of_day(st.session_state['trade_results_df'], 'Exit Time', 'Exit Time of Day', bin_size_exit_time_input, "exit")
    else:
        st.warning("⚠️ ไม่พบคอลัมน์ 'Exit Time' ในข้อมูล. ไม่สามารถทำการวิเคราะห์ตามเวลาออกจากเทรดได้.")

# --- ส่วนที่ 8 & 9: Heatmap Analysis (Profit by Entry/Exit Time and Day) ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("8 & 9. 🔥 Heatmap Analysis: Profit(R) by Time and Day")
    st.markdown("Heatmap แสดงผลรวมของ Profit(R), จำนวนเทรด, และค่าเฉลี่ย Profit(R) โดยแบ่งตามวันในสัปดาห์และช่วงเวลาของวัน (สามารถปรับขนาด Bin ได้) โดยจะข้ามการแสดงผลช่วงเวลา 12:00-19:30 น.")

    # --- Function to create Heatmap plots and tables ---
    def plot_profit_heatmap(df_source, time_column_name, day_column_name, plot_title_prefix, bin_size_minutes_heatmap, key_suffix):
        df_heatmap = df_source.copy()

        # Ensure necessary columns exist
        required_heatmap_cols = [time_column_name, 'Profit(R)']
        if not all(col in df_heatmap.columns for col in required_heatmap_cols):
            st.error(f"❌ ไม่พบคอลัมน์ที่จำเป็น ({', '.join(required_heatmap_cols)}) สำหรับ {plot_title_prefix}.")
            return
        
        # Convert time column to datetime and Profit(R) to float
        df_heatmap[time_column_name] = pd.to_datetime(df_heatmap[time_column_name], errors='coerce')
        df_heatmap['Profit(R)'] = pd.to_numeric(df_heatmap['Profit(R)'], errors='coerce')
        df_heatmap.dropna(subset=[time_column_name, 'Profit(R)'], inplace=True)

        if df_heatmap.empty:
            st.info(f"ℹ️ ไม่มีข้อมูลเทรดที่สมบูรณ์สำหรับ {plot_title_prefix} หลังจากกรอง NaN.")
            return

        try:
            # Derive Day Name and Time of Day (HH:MM string for binning)
            df_heatmap[day_column_name] = df_heatmap[time_column_name].dt.day_name()
            # df_heatmap['Time of Day Obj'] = df_heatmap[time_column_name].dt.time # Keep as time object for map_time_to_bin

            # Helper function to map a time object to a bin string
            def map_time_to_bin(time_obj, resolution_minutes):
                if pd.isnull(time_obj): return np.nan
                # If time_obj is already datetime.time
                if isinstance(time_obj, pd.Timestamp): # If it's a full timestamp, extract time
                    time_obj = time_obj.time()

                total_minutes = time_obj.hour * 60 + time_obj.minute
                bin_minutes_since_midnight = (total_minutes // resolution_minutes) * resolution_minutes
                bin_hour = bin_minutes_since_midnight // 60
                bin_minute = bin_minutes_since_midnight % 60
                return f"{bin_hour:02d}:{bin_minute:02d}"

            df_heatmap['Time Bin'] = df_heatmap[time_column_name].apply(lambda t: map_time_to_bin(t, bin_size_minutes_heatmap))
            
            df_heatmap.dropna(subset=['Time Bin', day_column_name], inplace=True)
            if df_heatmap.empty:
                st.info(f"ℹ️ ไม่มีข้อมูลหลังจากการสร้าง Time Bin หรือ Day Column สำหรับ {plot_title_prefix}.")
                return

            agg_data_heatmap = df_heatmap.groupby([day_column_name, 'Time Bin'], observed=False)['Profit(R)'].agg(['sum', 'count', 'mean']).reset_index() # added observed=False

            # Define times to skip (12:00 PM to 19:30 PM)
            def time_string_to_seconds(time_str_ts):
                h_ts, m_ts = map(int, time_str_ts.split(':'))
                return h_ts * 3600 + m_ts * 60
            
            full_time_bins_list = []
            for h_bin in range(24):
                for m_bin in range(0, 60, bin_size_minutes_heatmap):
                    full_time_bins_list.append(f"{h_bin:02d}:{m_bin:02d}")

            display_time_bins_list = [
                bin_s for bin_s in full_time_bins_list
                if not (time_string_to_seconds(bin_s) >= time_string_to_seconds('12:00') and \
                        time_string_to_seconds(bin_s) < time_string_to_seconds('19:30'))
            ]
            
            agg_data_filtered_heatmap = agg_data_heatmap[agg_data_heatmap['Time Bin'].isin(display_time_bins_list)].copy()

            if agg_data_filtered_heatmap.empty:
                st.info(f"ℹ️ ไม่มีข้อมูลเทรดในกรอบเวลาที่แสดง (หลังจากการข้ามช่วง 12:00-19:30) สำหรับ {plot_title_prefix} Heatmap.")
                return

            heatmap_sum_df = agg_data_filtered_heatmap.pivot(index=day_column_name, columns='Time Bin', values='sum')
            heatmap_count_df = agg_data_filtered_heatmap.pivot(index=day_column_name, columns='Time Bin', values='count')
            heatmap_mean_df = agg_data_filtered_heatmap.pivot(index=day_column_name, columns='Time Bin', values='mean')

            day_order_heatmap = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            # Ensure all days in day_order_heatmap are present in the index before reindexing to avoid adding all-NaN rows if a day has no data at all.
            # Filter day_order_heatmap to only include days that are actually in heatmap_sum_df.index
            present_days_in_data = [day for day in day_order_heatmap if day in heatmap_sum_df.index]


            if not present_days_in_data: # If no relevant days have data
                st.info(f"ℹ️ ไม่มีข้อมูลสำหรับวันในสัปดาห์ที่ระบุ (อาทิตย์-เสาร์) ใน {plot_title_prefix} Heatmap.")
                return

            heatmap_sum_df = heatmap_sum_df.reindex(index=present_days_in_data, columns=display_time_bins_list)
            heatmap_count_df = heatmap_count_df.reindex(index=present_days_in_data, columns=display_time_bins_list)
            heatmap_mean_df = heatmap_mean_df.reindex(index=present_days_in_data, columns=display_time_bins_list)


            if heatmap_sum_df.empty:
                st.info(f"ℹ️ ไม่มีข้อมูลสำหรับสร้าง Heatmap ของ {plot_title_prefix} หลัง reindex และ dropna.")
                return

            annotation_matrix_hm = np.empty(heatmap_sum_df.shape, dtype=object)
            for r_idx in range(heatmap_sum_df.shape[0]):
                for c_idx in range(heatmap_sum_df.shape[1]):
                    sum_val_hm = heatmap_sum_df.iloc[r_idx, c_idx]
                    count_val_hm = heatmap_count_df.iloc[r_idx, c_idx]
                    mean_val_hm = heatmap_mean_df.iloc[r_idx, c_idx]
                    if pd.notna(sum_val_hm):
                        count_str_hm = f"({int(count_val_hm)})" if pd.notna(count_val_hm) else ""
                        annotation_matrix_hm[r_idx, c_idx] = f"{sum_val_hm:.2f}\n{count_str_hm}\n{mean_val_hm:.2f}"
                    else:
                        annotation_matrix_hm[r_idx, c_idx] = ""
            
            colors_list_hm = [(0.9, 0.2, 0.1, 0.8), (0.98, 0.98, 0.98, 0.5), (0.1, 0.5, 0.9, 0.8)] # Red-White-Blue with alpha
            cmap_custom_hm = LinearSegmentedColormap.from_list("custom_heat", colors_list_hm, N=256)
            
            min_val_hm, max_val_hm = np.nanmin(heatmap_sum_df.values), np.nanmax(heatmap_sum_df.values)
            norm_final_hm = None
            if pd.notnull(min_val_hm) and pd.notnull(max_val_hm) and not np.isclose(min_val_hm, max_val_hm): # check for non-equality for floats
                 norm_final_hm = CustomDivergingNorm(vmin=min_val_hm, vcenter=0, vmax=max_val_hm)


            # Plotting
            st.subheader(f"Heatmap: {plot_title_prefix} ({bin_size_minutes_heatmap}-min bins, 12:00-19:30 Skipped)")
            fig_hm, ax_hm = plt.subplots(figsize=(max(15, len(display_time_bins_list) * 0.5), max(6, heatmap_sum_df.shape[0] * 0.8))) # Dynamic figsize
            
            sns.heatmap(heatmap_sum_df, cmap=cmap_custom_hm if norm_final_hm else "coolwarm", norm=norm_final_hm, 
                        annot=annotation_matrix_hm, fmt="", linewidths=.5, linecolor='lightgray', 
                        cbar=True if norm_final_hm else False, ax=ax_hm, annot_kws={"size": 7})

            ax_hm.set_title(f'Sum of Profit(R) by {day_column_name} and {plot_title_prefix} ({bin_size_minutes_heatmap}-min Bins)', fontsize=12)
            ax_hm.set_xlabel(f'{plot_title_prefix} ({bin_size_minutes_heatmap}-min Bins)', fontsize=10)
            ax_hm.set_ylabel(day_column_name, fontsize=10)
            plt.setp(ax_hm.get_xticklabels(), rotation=45, ha="right", fontsize=8)
            plt.setp(ax_hm.get_yticklabels(), fontsize=9)
            
            # Auto-contrast font color (already part of seaborn for basic cases, but can be enhanced)
            for text_item in ax_hm.texts:
                text_item.set_fontsize(7) # Ensure consistent small font for annotations
                # Add more sophisticated contrast logic if needed, seaborn's default is often good

            st.pyplot(fig_hm)

            # Summary Table
            st.subheader(f"ตารางข้อมูล Heatmap: {plot_title_prefix}")
            # Reconstruct agg_data_filtered_heatmap for table display if needed, or use pivoted tables
            # For simplicity, we can show the aggregated data before pivoting if it's more readable
            agg_data_filtered_heatmap_display = agg_data_filtered_heatmap.copy()
            agg_data_filtered_heatmap_display.rename(columns={'sum':'Sum(R)', 'count':'Trades', 'mean':'Avg(R)'}, inplace=True)
            st.dataframe(agg_data_filtered_heatmap_display[[day_column_name, 'Time Bin', 'Sum(R)', 'Trades', 'Avg(R)']].style.format({'Sum(R)': "{:.2f}", 'Avg(R)': "{:.2f}"}))

        except Exception as e_hm:
            st.error(f"❌ เกิดข้อผิดพลาดในการสร้าง Heatmap สำหรับ {plot_title_prefix}: {e_hm}")
            st.exception(e_hm)


    # --- UI for Entry Time Heatmap (08) ---
    st.markdown("### 8. Heatmap ตามเวลาเข้าเทรด (Entry Time)")
    bin_size_heatmap_entry_input = st.number_input(
        "เลือกขนาด Bin สำหรับ Heatmap เวลาเข้าเทรด (นาที):", 
        min_value=1, max_value=120, value=20, step=1, 
        key="bin_heatmap_entry",
        help="ขนาดของแต่ละช่วงเวลาที่จะใช้ในการจัดกลุ่มข้อมูลสำหรับ Heatmap"
    )
    plot_profit_heatmap(st.session_state['trade_results_df'], 'Entry Time', 'Entry Day', 'Entry Time of Day', bin_size_heatmap_entry_input, "heatmap_entry")

    st.markdown("---")
    # --- UI for Exit Time Heatmap (09) ---
    st.markdown("### 9. Heatmap ตามเวลาออกจากเทรด (Exit Time)")
    bin_size_heatmap_exit_input = st.number_input(
        "เลือกขนาด Bin สำหรับ Heatmap เวลาออกจากเทรด (นาที):", 
        min_value=1, max_value=120, value=20, step=1, 
        key="bin_heatmap_exit",
        help="ขนาดของแต่ละช่วงเวลาที่จะใช้ในการจัดกลุ่มข้อมูลสำหรับ Heatmap"
    )
    if 'Exit Time' in st.session_state['trade_results_df'].columns:
         # For Exit Time heatmap, the day column should be 'Exit Day'
         # We need to ensure 'Exit Day' is created if not already present
        df_for_exit_heatmap = st.session_state['trade_results_df'].copy()
        
        # Ensure 'Exit Time' is datetime before deriving 'Exit Day'
        df_for_exit_heatmap['Exit Time'] = pd.to_datetime(df_for_exit_heatmap['Exit Time'], errors='coerce')
        df_for_exit_heatmap.dropna(subset=['Exit Time'], inplace=True) # Drop rows where Exit Time is NaT

        if 'Exit Day' not in df_for_exit_heatmap.columns and not df_for_exit_heatmap.empty:
            df_for_exit_heatmap['Exit Day'] = df_for_exit_heatmap['Exit Time'].dt.day_name()
            df_for_exit_heatmap.dropna(subset=['Exit Day'], inplace=True) # Drop if Exit Day became NaN (e.g. from NaT Exit Time)
        
        if not df_for_exit_heatmap.empty:
            plot_profit_heatmap(df_for_exit_heatmap, 'Exit Time', 'Exit Day', 'Exit Time of Day', bin_size_heatmap_exit_input, "heatmap_exit")
        else:
            st.info("ℹ️ ไม่มีข้อมูลที่สมบูรณ์ (หลังจากการจัดการ 'Exit Time') สำหรับสร้าง Heatmap ตามเวลาออกจากเทรด")
    else:
        st.warning("⚠️ ไม่พบคอลัมน์ 'Exit Time' ในข้อมูล. ไม่สามารถสร้าง Heatmap ตามเวลาออกจากเทรดได้.")

# --- ส่วนที่ 10: MFE/MAE Scatter Plots (จากไฟล์ 10A, 10B, 10C) ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("10.  Scatter Plots: MFE, MAE, and Profit(R)")
    st.markdown("กราฟ Scatter เหล่านี้ช่วยให้เห็นความสัมพันธ์ระหว่าง MFE (Maximum Favorable Excursion), MAE (Maximum Adverse Excursion), และ Profit(R) ของแต่ละเทรด โดยแบ่งสีตามผลลัพธ์ของเทรด (Win, Loss, Breakeven)")

    df_scatter_base = st.session_state['trade_results_df'].copy()

    # Function to create scatter plots
    def create_scatter_plot(df_data, x_col, y_col, title):
        # Ensure required columns exist and drop NaNs for these specific columns
        required_cols_scatter = [x_col, y_col, 'Profit(R)']
        if not all(col in df_data.columns for col in required_cols_scatter):
            missing_cols_scatter = [col for col in required_cols_scatter if col not in df_data.columns]
            st.error(f"❌ ไม่พบคอลัมน์ที่จำเป็น ({', '.join(missing_cols_scatter)}) สำหรับ Scatter Plot: {title}")
            return None # Return None if plot cannot be made

        df_plot_scatter = df_data.dropna(subset=required_cols_scatter).copy()

        if df_plot_scatter.empty:
            st.info(f"ℹ️ ไม่มีข้อมูลที่สมบูรณ์ (หลังจากการกรอง NaN สำหรับ {x_col}, {y_col}, Profit(R)) สำหรับ Scatter Plot: {title}")
            return None

        try:
            # Define colors based on Profit(R)
            # Ensure Profit(R) is numeric for comparison
            df_plot_scatter['Profit(R)'] = pd.to_numeric(df_plot_scatter['Profit(R)'], errors='coerce')
            df_plot_scatter.dropna(subset=['Profit(R)'], inplace=True) # Drop if Profit(R) became NaN

            if df_plot_scatter.empty: # Check again after coercing Profit(R)
                st.info(f"ℹ️ ไม่มีข้อมูลที่สมบูรณ์หลังจากการแปลง Profit(R) สำหรับ Scatter Plot: {title}")
                return None

            colors = np.where(df_plot_scatter['Profit(R)'] > 0, 'blue',
                               np.where(df_plot_scatter['Profit(R)'] < 0, 'red', 'gray'))

            fig, ax = plt.subplots(figsize=(10, 7))
            ax.scatter(df_plot_scatter[x_col], df_plot_scatter[y_col], c=colors, alpha=0.6, s=20)
            ax.set_xlabel(f'{x_col}')
            ax.set_ylabel(f'{y_col}')
            ax.set_title(title)
            ax.grid(True, linestyle='--', alpha=0.5)

            # Custom legend
            legend_elements = [
                Line2D([0], [0], marker='o', color='w', label='Winning Trades', markerfacecolor='blue', markersize=10),
                Line2D([0], [0], marker='o', color='w', label='Losing Trades', markerfacecolor='red', markersize=10),
                Line2D([0], [0], marker='o', color='w', label='Breakeven Trades', markerfacecolor='gray', markersize=10)
            ]
            ax.legend(handles=legend_elements, loc='best')
            return fig
        except Exception as e_scatter:
            st.error(f"❌ เกิดข้อผิดพลาดในการสร้าง Scatter Plot '{title}': {e_scatter}")
            st.exception(e_scatter)
            return None

    # --- 10A: MFE vs MAE ---
    st.subheader("10A. MFE(R) vs MAE(R)")
    fig_10a = create_scatter_plot(df_scatter_base, 'MFE(R)', 'MAE(R)', 'MFE(R) vs MAE(R) by Trade Outcome')
    if fig_10a:
        st.pyplot(fig_10a)

    # --- 10B: MFE vs Profit ---
    st.subheader("10B. MFE(R) vs Profit(R)")
    fig_10b = create_scatter_plot(df_scatter_base, 'MFE(R)', 'Profit(R)', 'MFE(R) vs Profit(R) by Trade Outcome')
    if fig_10b:
        st.pyplot(fig_10b)

    # --- 10C: MAE vs Profit ---
    st.subheader("10C. MAE(R) vs Profit(R)")
    fig_10c = create_scatter_plot(df_scatter_base, 'MAE(R)', 'Profit(R)', 'MAE(R) vs Profit(R) by Trade Outcome')
    if fig_10c:
        st.pyplot(fig_10c)


# --- ส่วนที่ 11: MFE Histograms (All, Losing, Breakeven - Overall and By Day) ---
if 'trade_results_df' in st.session_state and \
   st.session_state['trade_results_df'] is not None and \
   not st.session_state['trade_results_df'].empty:

    st.header("11. 🌊 MFE (Maximum Favorable Excursion) Histograms")
    st.markdown("Histograms เหล่านี้แสดงการกระจายตัวของ MFE(R) ซึ่งคือจุดที่ราคาเคลื่อนไปในทิศทางที่เป็นกำไรสูงสุดระหว่างที่เปิดเทรดอยู่ ช่วยให้เห็นศักยภาพของเทรดแต่ละประเภท")

    df_mfe_base = st.session_state['trade_results_df'].copy()

    # --- Function to categorize trade outcome ---
    def categorize_trade_outcome(profit_r_value):
        if pd.isna(profit_r_value): return 'Unknown' # Handle NaN Profit(R)
        if profit_r_value > 1e-9: return 'Winning'    # Use tolerance for float comparison
        if profit_r_value < -1e-9: return 'Losing'
        return 'Breakeven'

    # Ensure 'Profit(R)' is numeric before applying categorize_trade_outcome
    if 'Profit(R)' in df_mfe_base.columns:
        df_mfe_base['Profit(R)'] = pd.to_numeric(df_mfe_base['Profit(R)'], errors='coerce')
        df_mfe_base['Trade_Outcome'] = df_mfe_base['Profit(R)'].apply(categorize_trade_outcome)
    else:
        st.error("❌ ไม่พบคอลัมน์ 'Profit(R)' สำหรับการแบ่งประเภทเทรดในส่วน MFE Histograms.")
        # Set a default 'Trade_Outcome' to avoid further errors, or handle more gracefully
        df_mfe_base['Trade_Outcome'] = 'Unknown'


    # --- 11A1: MFE Histogram - All Trades (Segmented) ---
    st.subheader("11A1. MFE Distribution - All Trades (Segmented by Outcome)")
    if 'MFE(R)' not in df_mfe_base.columns:
        st.error("❌ ไม่พบคอลัมน์ 'MFE(R)' สำหรับ MFE Histogram (All Trades).")
    else:
        df_plot_11a1 = df_mfe_base.dropna(subset=['MFE(R)', 'Profit(R)']).copy() # Ensure Profit(R) is also not NaN for outcome
        if df_plot_11a1.empty:
            st.info("ℹ️ ไม่มีข้อมูล MFE(R) และ Profit(R) ที่ถูกต้องสำหรับ MFE Histogram (All Trades).")
        else:
            try:
                fig_11a1, ax_11a1 = plt.subplots(figsize=(12, 7))
                outcome_colors_11a1 = {'Winning': 'blue', 'Losing': 'red', 'Breakeven': 'gray', 'Unknown': 'purple'}
                outcome_order_11a1 = ['Winning', 'Losing', 'Breakeven', 'Unknown']
                
                # Filter out 'Unknown' if it's not meaningful or if all Profit(R) were valid
                df_plot_11a1_filtered = df_plot_11a1[df_plot_11a1['Trade_Outcome'] != 'Unknown']
                if df_plot_11a1_filtered.empty and not df_plot_11a1.empty : # If filtering removed everything but there was data
                     st.warning("ℹ️ ข้อมูล MFE ทั้งหมดมีผลลัพธ์ Profit(R) ที่ไม่สามารถระบุได้ (Unknown).")
                     df_plot_11a1_filtered = df_plot_11a1 # Plot unknown if that's all there is
                elif df_plot_11a1_filtered.empty: # No data at all
                     st.info("ℹ️ ไม่มีข้อมูลสำหรับ MFE Histogram (All Trades) หลังจากการกรอง 'Unknown' outcomes.")


                if not df_plot_11a1_filtered.empty:
                    sns.histplot(data=df_plot_11a1_filtered, x='MFE(R)', hue='Trade_Outcome',
                                 palette={k: v for k, v in outcome_colors_11a1.items() if k in df_plot_11a1_filtered['Trade_Outcome'].unique()}, # Use only relevant colors
                                 hue_order=[o for o in outcome_order_11a1 if o in df_plot_11a1_filtered['Trade_Outcome'].unique()],
                                 kde=False, edgecolor='white', alpha=0.8, bins=50, ax=ax_11a1, multiple="stack")
                    ax_11a1.set_xlabel('MFE (R-Multiple)')
                    ax_11a1.set_ylabel('Count')
                    ax_11a1.set_title('Distribution of MFE by Trade Outcome')
                    ax_11a1.grid(axis='y', linestyle='--', alpha=0.7)
                    ax_11a1.legend(title='Trade Outcome')
                    st.pyplot(fig_11a1)
            except Exception as e_11a1:
                st.error(f"❌ เกิดข้อผิดพลาดในการสร้าง MFE Histogram (All Trades): {e_11a1}")
                st.exception(e_11a1)
    
    # --- Helper function for MFE Histograms by Day ---
    def plot_mfe_hist_by_day(df_source, filter_condition_col=None, filter_condition_val=None, title_suffix="", plot_all_outcomes=False):
        if 'Entry Time' not in df_source.columns or 'MFE(R)' not in df_source.columns or 'Profit(R)' not in df_source.columns:
            st.error(f"❌ ไม่พบคอลัมน์ที่จำเป็น ('Entry Time', 'MFE(R)', 'Profit(R)') สำหรับ MFE Histogram by Day {title_suffix}.")
            return

        df_day_base = df_source.copy()
        df_day_base['Entry Time'] = pd.to_datetime(df_day_base['Entry Time'], errors='coerce')
        df_day_base.dropna(subset=['Entry Time', 'MFE(R)', 'Profit(R)'], inplace=True)

        if 'Entry Day' not in df_day_base.columns:
            df_day_base['Entry Day'] = df_day_base['Entry Time'].dt.day_name()
        df_day_base.dropna(subset=['Entry Day'], inplace=True)


        if df_day_base.empty:
            st.info(f"ℹ️ ไม่มีข้อมูลที่สมบูรณ์สำหรับ MFE Histogram by Day {title_suffix}.")
            return

        df_to_plot_day = df_day_base
        if filter_condition_col and filter_condition_val is not None:
            if filter_condition_val == "Breakeven": # Special handling for breakeven due to float precision
                df_to_plot_day = df_day_base[np.isclose(df_day_base[filter_condition_col], 0, atol=1e-9)].copy()
            else: # For Winning (>0) or Losing (<0)
                if filter_condition_val == "Winning":
                    df_to_plot_day = df_day_base[df_day_base[filter_condition_col] > 1e-9].copy()
                elif filter_condition_val == "Losing":
                    df_to_plot_day = df_day_base[df_day_base[filter_condition_col] < -1e-9].copy()
        
        df_to_plot_day.dropna(subset=['MFE(R)'], inplace=True) # Ensure MFE is not NaN for plotting

        if df_to_plot_day.empty:
            st.info(f"ℹ️ ไม่มีข้อมูลเทรดที่ตรงตามเงื่อนไข ({title_suffix}) สำหรับ MFE Histogram by Day.")
            return
        
        try:
            day_order_mfe = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] # Typically Sun-Fri
            days_present_mfe = [day for day in day_order_mfe if day in df_to_plot_day['Entry Day'].unique()]

            if not days_present_mfe:
                st.info(f"ℹ️ ไม่พบข้อมูลในวันที่ระบุ (อาทิตย์-ศุกร์) สำหรับ MFE Histogram by Day {title_suffix}.")
                return

            num_days_mfe = len(days_present_mfe)
            ncols_mfe = 2
            nrows_mfe = (num_days_mfe + ncols_mfe - 1) // ncols_mfe
            fig_mfe_day, axes_mfe_day = plt.subplots(nrows=nrows_mfe, ncols=ncols_mfe, figsize=(14, 6 * nrows_mfe), squeeze=False)
            axes_mfe_flat = axes_mfe_day.flatten()
            ax_idx_mfe = 0

            for day_mfe in days_present_mfe:
                df_current_day_mfe = df_to_plot_day[df_to_plot_day['Entry Day'] == day_mfe].copy()
                if df_current_day_mfe.empty: continue

                ax_m = axes_mfe_flat[ax_idx_mfe]
                if plot_all_outcomes: # For 11A2
                    outcome_colors_mfe_day = {'Winning': 'blue', 'Losing': 'red', 'Breakeven': 'gray', 'Unknown':'purple'}
                    outcome_order_mfe_day = ['Winning', 'Losing', 'Breakeven', 'Unknown']
                    df_current_day_mfe['Trade_Outcome_Plot'] = df_current_day_mfe['Profit(R)'].apply(categorize_trade_outcome)
                    
                    # Filter out 'Unknown' before plotting if not meaningful
                    df_plot_current_day = df_current_day_mfe[df_current_day_mfe['Trade_Outcome_Plot'] != 'Unknown']
                    if df_plot_current_day.empty and not df_current_day_mfe.empty:
                         df_plot_current_day = df_current_day_mfe # Plot unknown if that's all
                    
                    if not df_plot_current_day.empty:
                        sns.histplot(data=df_plot_current_day, x='MFE(R)', hue='Trade_Outcome_Plot',
                                     palette={k:v for k,v in outcome_colors_mfe_day.items() if k in df_plot_current_day['Trade_Outcome_Plot'].unique()},
                                     hue_order=[o for o in outcome_order_mfe_day if o in df_plot_current_day['Trade_Outcome_Plot'].unique()],
                                     kde=False, edgecolor='white', alpha=0.8, bins=30, ax=ax_m, multiple="stack")
                        ax_m.legend(title='Trade Outcome', fontsize='x-small')
                else: # For 11B2, 11C2 - single color
                    plot_color = 'salmon' if title_suffix == "Losing Trades" else 'gray' if title_suffix == "Breakeven Trades" else 'skyblue'
                    sns.histplot(data=df_current_day_mfe, x='MFE(R)', kde=False, color=plot_color, edgecolor='white', alpha=0.8, bins=20, ax=ax_m)
                    
                    # Add Median and 70th Percentile lines for Losing/Breakeven
                    if title_suffix in ["Losing Trades", "Breakeven Trades"]:
                        mfe_values_day_specific = df_current_day_mfe['MFE(R)']
                        if not mfe_values_day_specific.empty:
                            median_mfe_day = mfe_values_day_specific.median()
                            percentile_70_mfe_day = mfe_values_day_specific.quantile(0.70)
                            if pd.notnull(median_mfe_day):
                                ax_m.axvline(median_mfe_day, color='purple', linestyle='dashed', linewidth=1, label=f'Median ({median_mfe_day:.2f}R)')
                            if pd.notnull(percentile_70_mfe_day):
                                ax_m.axvline(percentile_70_mfe_day, color='green', linestyle='dashed', linewidth=1, label=f'70th Pctl ({percentile_70_mfe_day:.2f}R)')
                            if pd.notnull(median_mfe_day) or pd.notnull(percentile_70_mfe_day):
                                ax_m.legend(fontsize='x-small')
                
                ax_m.set_xlabel('MFE (R-Multiple)')
                ax_m.set_ylabel('Count')
                ax_m.set_title(f'MFE for {title_suffix} on {day_mfe}')
                ax_m.grid(axis='y', linestyle='--', alpha=0.7)
                if title_suffix == "Breakeven Trades": ax_m.set_xlim(left=0.0) # X-axis starts at 0 for Breakeven MFE
                ax_idx_mfe += 1

            for i in range(ax_idx_mfe, len(axes_mfe_flat)): fig_mfe_day.delaxes(axes_mfe_flat[i])
            fig_mfe_day.suptitle(f'MFE Distribution for {title_suffix} by Entry Day', fontsize=16, y=1.00)
            fig_mfe_day.tight_layout(rect=[0, 0, 1, 0.96])
            st.pyplot(fig_mfe_day)

        except Exception as e_mfe_day:
            st.error(f"❌ เกิดข้อผิดพลาดในการสร้าง MFE Histogram by Day {title_suffix}: {e_mfe_day}")
            st.exception(e_mfe_day)

    # --- 11A2: MFE Histogram - All Trades by Day ---
    st.subheader("11A2. MFE Distribution - All Trades by Entry Day (Segmented by Outcome)")
    plot_mfe_hist_by_day(df_mfe_base, plot_all_outcomes=True, title_suffix="All Trades")

    # --- 11B1: MFE Histogram - Losing Trades ---
    st.subheader("11B1. MFE Distribution - Losing Trades")
    if 'MFE(R)' not in df_mfe_base.columns:
        st.error("❌ ไม่พบคอลัมน์ 'MFE(R)' สำหรับ MFE Histogram (Losing Trades).")
    else:
        df_plot_11b1 = df_mfe_base[df_mfe_base['Trade_Outcome'] == 'Losing'].dropna(subset=['MFE(R)']).copy()
        if df_plot_11b1.empty:
            st.info("ℹ️ ไม่มีเทรดที่ขาดทุน หรือไม่มีข้อมูล MFE(R) ที่ถูกต้องสำหรับเทรดที่ขาดทุน.")
        else:
            try:
                fig_11b1, ax_11b1 = plt.subplots(figsize=(12, 7))
                mfe_losses = df_plot_11b1['MFE(R)']
                median_mfe_losses = mfe_losses.median()
                percentile_70_mfe_losses = mfe_losses.quantile(0.70)
                sns.histplot(data=df_plot_11b1, x='MFE(R)', kde=False, color='salmon', edgecolor='white', alpha=0.8, bins=50, ax=ax_11b1)
                if pd.notnull(median_mfe_losses): ax_11b1.axvline(median_mfe_losses, color='purple', linestyle='dashed', linewidth=1.5, label=f'Median ({median_mfe_losses:.2f}R)')
                if pd.notnull(percentile_70_mfe_losses): ax_11b1.axvline(percentile_70_mfe_losses, color='green', linestyle='dashed', linewidth=1.5, label=f'70th Pctl ({percentile_70_mfe_losses:.2f}R)')
                ax_11b1.set_xlabel('MFE (R-Multiple)'); ax_11b1.set_ylabel('Count'); ax_11b1.set_title('Distribution of MFE for Losing Trades')
                ax_11b1.grid(axis='y', linestyle='--', alpha=0.7); ax_11b1.legend()
                st.pyplot(fig_11b1)
            except Exception as e_11b1: st.error(f"❌ เกิดข้อผิดพลาดในการสร้าง MFE Histogram (Losing Trades): {e_11b1}"); st.exception(e_11b1)

    # --- 11B2: MFE Histogram - Losing Trades by Day ---
    st.subheader("11B2. MFE Distribution - Losing Trades by Entry Day")
    plot_mfe_hist_by_day(df_mfe_base, filter_condition_col='Profit(R)', filter_condition_val="Losing", title_suffix="Losing Trades")
    
    # --- 11C1: MFE Histogram - Breakeven Trades ---
    st.subheader("11C1. MFE Distribution - Breakeven Trades")
    if 'MFE(R)' not in df_mfe_base.columns:
        st.error("❌ ไม่พบคอลัมน์ 'MFE(R)' สำหรับ MFE Histogram (Breakeven Trades).")
    else:
        df_plot_11c1 = df_mfe_base[np.isclose(df_mfe_base['Profit(R)'], 0, atol=1e-9)].dropna(subset=['MFE(R)']).copy()
        if df_plot_11c1.empty:
            st.info("ℹ️ ไม่มีเทรดที่เสมอตัว หรือไม่มีข้อมูล MFE(R) ที่ถูกต้องสำหรับเทรดที่เสมอตัว.")
        else:
            try:
                fig_11c1, ax_11c1 = plt.subplots(figsize=(12, 7))
                mfe_be = df_plot_11c1['MFE(R)']
                median_mfe_be = mfe_be.median()
                percentile_70_mfe_be = mfe_be.quantile(0.70)
                
                min_mfe_be = mfe_be.min() if not mfe_be.empty else 0.0
                max_mfe_be = mfe_be.max() if not mfe_be.empty else 1.0
                bin_start_be = max(0.0, min_mfe_be) # Ensure x-axis starts at 0 for BE MFE
                bins_11c1 = np.linspace(bin_start_be, max_mfe_be, 20) if not mfe_be.empty else 20


                sns.histplot(data=df_plot_11c1, x='MFE(R)', kde=False, color='gray', edgecolor='white', alpha=0.8, bins=bins_11c1, ax=ax_11c1)
                if pd.notnull(median_mfe_be): ax_11c1.axvline(median_mfe_be, color='purple', linestyle='dashed', linewidth=1.5, label=f'Median ({median_mfe_be:.2f}R)')
                if pd.notnull(percentile_70_mfe_be): ax_11c1.axvline(percentile_70_mfe_be, color='green', linestyle='dashed', linewidth=1.5, label=f'70th Pctl ({percentile_70_mfe_be:.2f}R)')
                ax_11c1.set_xlabel('MFE (R-Multiple)'); ax_11c1.set_ylabel('Count'); ax_11c1.set_title('Distribution of MFE for Breakeven Trades')
                ax_11c1.grid(axis='y', linestyle='--', alpha=0.7); ax_11c1.legend()
                ax_11c1.set_xlim(left=0.0) # Ensure x-axis starts at 0
                st.pyplot(fig_11c1)
            except Exception as e_11c1: st.error(f"❌ เกิดข้อผิดพลาดในการสร้าง MFE Histogram (Breakeven Trades): {e_11c1}"); st.exception(e_11c1)

    # --- 11C2: MFE Histogram - Breakeven Trades by Day ---
    st.subheader("11C2. MFE Distribution - Breakeven Trades by Entry Day")
    plot_mfe_hist_by_day(df_mfe_base, filter_condition_col='Profit(R)', filter_condition_val="Breakeven", title_suffix="Breakeven Trades")


# else:
#     # This part is for when 'trade_results_df' is not in session_state or is empty
#     # Check if the button was pressed to avoid showing this message initially
#     if 'button_pressed_flag' not in st.session_state: # A simple way to check if it's the first run without button press
#          st.info("กรุณาอัปโหลดไฟล์และกดปุ่ม 'เริ่มการวิเคราะห์ฯ' เพื่อดูผลลัพธ์")
#     elif st.session_state.get('button_pressed_flag', False): # Check if button was pressed
#          st.info("กรุณารอผลการประมวลผลข้อมูลจากขั้นตอนที่ 1 ก่อนนะเจ้าคะ หรือกดปุ่ม 'เริ่มการวิเคราะห์ฯ' หากยังไม่ได้ทำ")

