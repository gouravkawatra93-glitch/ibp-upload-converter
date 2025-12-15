import streamlit as st
import pandas as pd
import io
import re
from datetime import datetime

st.set_page_config(page_title="IBP Time Series Converter", layout="wide")
st.title("IBP Time Series Converter — Web App")
st.write("Upload a CSV or Excel file, select dimensions, and convert any date format in headers (including week formats) to YYYY-MM-DD.")

# --- Upload file ---
uploaded_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xls", "xlsx"])
if uploaded_file is None:
    st.stop()

# --- Read file ---
try:
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
except Exception as e:
    st.error(f"Failed to read file: {e}")
    st.stop()

st.success(f"Loaded file with {df.shape[0]} rows and {df.shape[1]} columns")
st.dataframe(df.head(10))

# --- Select dimensions ---
st.subheader("Select Core Dimensions (optional)")
dimension_cols = st.multiselect("Product/Location/Customer", options=list(df.columns))

st.subheader("Select Custom Dimensions (optional)")
custom_dims = st.multiselect("Custom Dimensions", options=[c for c in df.columns if c not in dimension_cols])

all_dims = dimension_cols + custom_dims

# --- Identify date columns ---
date_cols = [c for c in df.columns if c not in all_dims]
st.subheader("Detected date/value columns")
st.write(date_cols)

# --- Function to convert any header to YYYY-MM-DD ---
def parse_to_ibp_date(header):
    header_str = str(header).strip()

    # 1️⃣ Try normal date (Excel / ISO / text date)
    try:
        dt = pd.to_datetime(header_str, errors="raise")
        return dt.strftime("%Y-%m-%d")
    except:
        pass

    # 2️⃣ ISO week formats: WK02 2025, wk2_2026, Week-12-2024
    wk_match = re.search(
        r"(wk|week)?\s*[-_ ]?\s*(\d{1,2})\s*[-_ ]?\s*(20\d{2})",
        header_str,
        re.IGNORECASE
    )

    if wk_match:
        week = int(wk_match.group(2))
        year = int(wk_match.group(3))

        # ISO week → Monday
        dt = pd.to_datetime(f"{year}-W{week}-1", format="%G-W%V-%u")
        return dt.strftime("%Y-%m-%d")

    # 3️⃣ Fallback: return original (non-period column)
    return header_str



# --- Convert date headers to YYYY-MM-DD ---
new_date_cols = [parse_to_ibp_date(col) for col in date_cols]
rename_mapping = dict(zip(date_cols, new_date_cols))
df.rename(columns=rename_mapping, inplace=True)
date_cols = new_date_cols

# --- Keyfigure ---
st.subheader("Keyfigure")
keyfigure_name = st.text_input("KEYFIGURE", value="FCST")

# --- Generate IBP CSV ---
if st.button("Generate IBP CSV"):
    try:
        df_melt = df.melt(
            id_vars=all_dims,
            value_vars=date_cols,
            var_name="PERIODID",
            value_name=keyfigure_name   # 👈 KEY CHANGE
        )

        final_cols = all_dims + ["PERIODID", keyfigure_name]
        df_final = df_melt[final_cols]

        st.success("IBP-ready file generated — preview below")
        st.dataframe(df_final.head(200))

        towrite = io.StringIO()
        df_final.to_csv(towrite, index=False)
        st.download_button(
            "Download IBP CSV",
            data=towrite.getvalue(),
            file_name="ibp_output.csv",
            mime="text/csv"
        )
    except Exception as e:
        st.error(f"Failed to generate IBP CSV: {e}")

