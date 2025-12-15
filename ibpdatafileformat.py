import streamlit as st
import pandas as pd
import io
from datetime import datetime

st.set_page_config(page_title="IBP Time Series Converter", layout="wide")
st.title("IBP Time Series Converter — Streamlit")
st.write("Upload file, map dimensions, unpivot date columns and export IBP-ready CSV.")

# --- Helpers ---

def read_input(uploaded_file):
    if uploaded_file is None:
        return None
    name = uploaded_file.name.lower()
    if name.endswith('.csv'):
        return pd.read_csv(uploaded_file)
    elif name.endswith(('.xls', '.xlsx')):
        return pd.read_excel(uploaded_file, engine='openpyxl')
    else:
        st.error('Unsupported file type. Upload .csv or .xlsx')
        return None


def try_parse_period(label, freq):
    """Try to parse a column header into a PERIODID depending on freq.
    freq: 'DAY','MONTH','YEAR','WEEK'
    Returns string or original label if parsing fails.
    """
    # If label already looks like a date-like object, try to parse
    try:
        dt = pd.to_datetime(label, dayfirst=False, errors='coerce')
        if pd.isna(dt):
            # try common replacements like Jan-26 -> 01-Jan-26
            # fallback: try parsing with day=1
            try:
                dt = pd.to_datetime(label + ' 01', errors='coerce')
            except:
                dt = pd.NaT
    except Exception:
        dt = pd.NaT

    if freq == 'DAY':
        if pd.isna(dt):
            return label
        return dt.strftime('%Y-%m-%d')

    if freq == 'MONTH':
        if pd.isna(dt):
            # attempt to parse by adding day=1
            try:
                dt = pd.to_datetime(label + ' 1', errors='coerce')
            except:
                dt = pd.NaT
        if pd.isna(dt):
            return label
        period_start = dt.to_period('M').start_time
        return period_start.strftime('%Y-%m-%d')

    if freq == 'YEAR':
        if pd.isna(dt):
            # try to parse year directly
            try:
                year = int(label)
                return f"{year:04d}-01-01"
            except:
                return label
        period_start = dt.to_period('Y').start_time
        return period_start.strftime('%Y-%m-%d')

    if freq == 'WEEK':
        if pd.isna(dt):
            # try to parse pattern like 'W01-2026' or '2026-W01'
            # fallback to returning label
            return label
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    return label


# --- UI ---
uploaded = st.file_uploader("Upload CSV or Excel file", type=['csv', 'xls', 'xlsx'])
if uploaded is None:
    st.info("Upload a file to begin. Example: rows with dimension columns and multiple date columns as headers.")
    st.stop()

# read
try:
    df = read_input(uploaded)
except Exception as e:
    st.error(f"Failed to read file: {e}")
    st.stop()

st.success(f"Loaded file with {df.shape[0]} rows and {df.shape[1]} columns")

# show sample
with st.expander("Preview first 10 rows", expanded=False):
    st.dataframe(df.head(10))

cols = list(df.columns.astype(str))

st.subheader("Map Core Dimensions (optional)")
col1, col2, col3 = st.columns(3)
with col1:
    product_map = st.selectbox('Product (PRODUCTID)', options=['Not used'] + cols, index=0)
with col2:
    location_map = st.selectbox('Location (LOCATIONID)', options=['Not used'] + cols, index=0)
with col3:
    customer_map = st.selectbox('Customer (CUSTOMER)', options=['Not used'] + cols, index=0)

# Custom dimensions
st.subheader('Add Custom Dimensions (optional)')
if 'custom_dims' not in st.session_state:
    st.session_state.custom_dims = []

with st.form('add_custom'):
    cd_name = st.text_input('Custom dimension name (exact as you want in output)', '')
    cd_col = st.selectbox('Map to input column', options=cols)
    add_btn = st.form_submit_button('Add custom dimension')
    if add_btn and cd_name.strip():
        st.session_state.custom_dims.append({'name': cd_name.strip(), 'col': cd_col})

if st.session_state.custom_dims:
    st.write('Current custom dimensions:')
    for i, cd in enumerate(st.session_state.custom_dims):
        st.write(f"{i+1}. {cd['name']} -> {cd['col']}")
    if st.button('Clear custom dimensions'):
        st.session_state.custom_dims = []

# Determine id_vars (mapped columns)
mapped_cols = []
if product_map != 'Not used':
    mapped_cols.append(("PRODUCTID", product_map))
if location_map != 'Not used':
    mapped_cols.append(("LOCATIONID", location_map))
if customer_map != 'Not used':
    mapped_cols.append(("CUSTOMER", customer_map))

for cd in st.session_state.custom_dims:
    mapped_cols.append((cd['name'], cd['col']))

mapped_input_cols = [m[1] for m in mapped_cols]
mapped_output_names = [m[0] for m in mapped_cols]

# Date frequency option
st.subheader('Date Frequency for PERIODID')
freq = st.selectbox('Choose how to interpret date-like column headers', options=['DAY', 'MONTH', 'YEAR', 'WEEK'], index=1)

# Identify candidate date columns
candidate_date_cols = [c for c in cols if c not in mapped_input_cols]

st.write(f"Detected {len(candidate_date_cols)} candidate date columns (columns not mapped as dimensions)")
with st.expander('Show candidate date columns and sample parsing'):
    # show a few samples and parsed periodids
    sample = candidate_date_cols[:50]
    parsed = [{
        'original': c,
        'parsed_period': try_parse_period(c, freq)
    } for c in sample]
    st.write(pd.DataFrame(parsed))

# Option: allow user to override which columns to treat as date columns
use_all = st.checkbox('Use all candidate columns as date columns (unpivot all remaining)', value=True)
if not use_all:
    date_cols = st.multiselect('Select which columns are date/value columns', options=candidate_date_cols, default=candidate_date_cols[:5])
else:
    date_cols = candidate_date_cols

if len(date_cols) == 0:
    st.error('No date columns selected. Please map at least one date column.')
    st.stop()

# Keyfigure name input
st.subheader('Keyfigure')
keyfigure = st.text_input('KEYFIGURE (will be the same for all rows)', value='KF')

# Button to generate
if st.button('Generate IBP CSV'):
    with st.spinner('Generating...'):
        try:
            id_vars_input = mapped_input_cols
            # For melt, id_vars must be columns present in df. If empty, create a placeholder
            if len(id_vars_input) == 0:
                # create a placeholder constant column so melt works and then drop it
                df['_CONST_ROWID'] = 1
                id_vars_input = ['_CONST_ROWID']

            melted = df.melt(id_vars=id_vars_input, value_vars=date_cols, var_name='ORIG_PERIOD', value_name='VALUE')

            # Map id var names to output names
            out_df = pd.DataFrame()
            for out_name, in_col in mapped_cols:
                out_df[out_name] = melted[in_col]

            # If we had the placeholder, remove it
            if '_CONST_ROWID' in melted.columns:
                # no dimension columns were present
                pass

            # Convert PERIODID
            out_df['PERIODID'] = melted['ORIG_PERIOD'].apply(lambda x: try_parse_period(x, freq))

            # Add KEYFIGURE column
            out_df.insert(0, 'KEYFIGURE', keyfigure)

            # Add VALUE
            out_df['VALUE'] = melted['VALUE']

            # Final column order: KEYFIGURE, mapped dims (in order), PERIODID, VALUE
            final_cols = ['KEYFIGURE'] + [c[0] for c in mapped_cols] + ['PERIODID', 'VALUE']
            final = out_df[final_cols]

            # Clean up index
            final = final.reset_index(drop=True)

            st.success('IBP file generated — preview below')
            st.dataframe(final.head(200))

            # Provide download
            towrite = io.StringIO()
            final.to_csv(towrite, index=False)
            st.download_button('Download IBP CSV', data=towrite.getvalue(), file_name='ibp_timeseries_upload.csv', mime='text/csv')

        except Exception as e:
            st.error(f'Failed to generate IBP file: {e}')

st.write('---')
st.caption('Notes: This tool attempts to parse column headers into PERIODID values. If some headers are ambiguous, inspect the preview and adjust which columns are treated as date columns or rename headers in the source file.')
