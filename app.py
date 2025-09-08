import os
import time
import datetime as dt
from typing import Dict, Optional

import pandas as pd
import requests
import streamlit as st

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="US Macro Dashboard", layout="wide")
st.title("🇺🇸 U.S. Macro Dashboard — Real-Time")

# Auto-refresh (milliseconds). Active on weekdays 8:00–17:30 ET.
# NOTE: This uses a simple ET offset. If deploying on a server, consider using pytz/zoneinfo.
ET_OFFSET = -4  # Adjust for DST if needed
now = dt.datetime.now(dt.timezone(dt.timedelta(hours=ET_OFFSET)))
is_weekday = now.weekday() <= 4
is_market_hours = (now.hour > 7) and (now.hour < 17 or (now.hour == 17 and now.minute <= 30))
refresh_ms = 60_000 if (is_weekday and is_market_hours) else 0
if refresh_ms:
    st.caption("🔄 Auto-refresh is ON (1 min) during market hours.")
    # Streamlit auto-rerun via query param trick to avoid aggressive caching
    st.query_params.update(_=int(time.time()))

# Secrets / env
FRED_API_KEY = os.getenv("FRED_API_KEY", st.secrets.get("FRED_API_KEY", ""))
TE_API_KEY = os.getenv("TE_API_KEY", st.secrets.get("TE_API_KEY", ""))  # optional TradingEconomics key
# ----------------------------
# Diagnostics (keys, cache, connectivity)
# ----------------------------
with st.expander("🔧 Diagnostics", expanded=False):
    st.write("**FRED key present:**", bool(FRED_API_KEY))
    st.write("**TradingEconomics key present:**", bool(TE_API_KEY))
    colA, colB = st.columns([1,1])
    if colA.button("Force refresh (clear cache)"):
        st.cache_data.clear()
        st.success("Cache cleared. The app will refetch data on next requests.")
    if colB.button("Test FRED connectivity"):
        try:
            test_params = {
                "series_id": "UNRATE",
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "frequency": "m",
                "observation_start": "2015-01-01",
            }
            resp = requests.get("https://api.stlouisfed.org/fred/series/observations", params=test_params, timeout=15)
            st.write("HTTP status:", resp.status_code)
            if resp.status_code != 200:
                st.error(f"FRED error (status {resp.status_code}): {resp.text[:500]}")
            else:
                payload = resp.json()
                st.success("FRED request OK. Sample:")
                st.json({k: payload.get(k) for k in ["realtime_start","realtime_end","seriess","observations"] if k in payload})
        except Exception as e:
            st.exception(e)


# ----------------------------
# Helpers
# ----------------------------
@st.cache_data(ttl=60)
def fred_get_series(series_id: str, freq: str = "m") -> Optional[pd.DataFrame]:
    """
    Fetch a FRED series. freq: 'd','w','m','q' (downsampling done by FRED).
    Returns df with columns: date,value (float), last_updated (meta)
    """
    base = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "frequency": freq,
        "observation_start": "2000-01-01",
    }
    r = requests.get(base, params=params, timeout=15)
    if r.status_code != 200:
        st.error(f"FRED request failed: {r.status_code} — {r.text[:200]}")
        return None
    data = r.json()
    obs = pd.DataFrame(data.get("observations", []))
    if obs.empty:
        return None
    obs["date"] = pd.to_datetime(obs["date"])
    obs["value"] = pd.to_numeric(obs["value"], errors="coerce")
    obs = obs.dropna(subset=["value"])
    last_updated = data.get("realtime_end", "")
    obs["last_updated"] = last_updated
    return obs[["date", "value", "last_updated"]]


def pct_change_latest(df: pd.DataFrame, periods: int = 1) -> Optional[float]:
    if df is None or df.empty or len(df) <= periods:
        return None
    vals = df["value"].tail(periods + 1).to_list()
    return (vals[-1] / vals[-periods - 1] - 1.0) * 100.0


def latest_value(df: pd.DataFrame):
    if df is None or df.empty:
        return None, None
    row = df.iloc[-1]
    return row["value"], row["date"].date()


def format_val(x, decimals=1):
    if x is None:
        return "—"
    return f"{x:.{decimals}f}"


# ----------------------------
# Indicator map (FRED IDs)
# ----------------------------
INDICATORS: Dict[str, Dict] = {
    # Prices
    "CPI (YoY, %)": {"id": "CPIAUCSL", "freq": "m", "transform": "yoy"},
    "Core CPI (YoY, %)": {"id": "CPILFESL", "freq": "m", "transform": "yoy"},
    "PCE (YoY, %)": {"id": "PCEPI", "freq": "m", "transform": "yoy"},
    "Core PCE (YoY, %)": {"id": "PCEPILFE", "freq": "m", "transform": "yoy"},
    "PPI All Commodities (YoY, %)": {"id": "PPIACO", "freq": "m", "transform": "yoy"},

    # Labor
    "Nonfarm Payrolls (k, m/m)": {"id": "PAYEMS", "freq": "m", "transform": "mom_level_k"},
    "Unemployment Rate (%)": {"id": "UNRATE", "freq": "m", "transform": "level"},
    "Avg Hourly Earnings (YoY, %)": {"id": "CES0500000003", "freq": "m", "transform": "yoy"},
    "Initial Jobless Claims (thous)": {"id": "ICSA", "freq": "w", "transform": "level_thous"},
    "Job Openings, JOLTS (millions)": {"id": "JTSJOL", "freq": "m", "transform": "level_millions"},

    # Activity
    "Retail Sales (YoY, %)": {"id": "RSAFS", "freq": "m", "transform": "yoy"},
    "ISM Manufacturing PMI": {"id": "NAPM", "freq": "m", "transform": "level"},
    "ISM Services PMI": {"id": "NMFBS", "freq": "m", "transform": "level"},  # Non-Mfg Business Activity
    "Real GDP (QoQ SAAR, %)": {"id": "A191RL1Q225SBEA", "freq": "q", "transform": "level"},
}

@st.cache_data(ttl=60)
def compute_transform(df: pd.DataFrame, transform: str) -> Optional[pd.DataFrame]:
    if df is None:
        return None
    s = df.copy()
    s = s.sort_values("date")
    if transform == "yoy":
        s["value"] = s["value"].pct_change(12) * 100
    elif transform == "mom_level_k":
        s["value"] = s["value"].diff(1) / 1000.0  # thousands of jobs
    elif transform == "level_thous":
        s["value"] = s["value"] / 1000.0
    elif transform == "level_millions":
        s["value"] = s["value"] / 1_000_000.0
    elif transform == "level":
        pass
    else:
        pass
    s = s.dropna(subset=["value"])
    return s

# ----------------------------
# Sidebar — API Keys & Date range
# ----------------------------
with st.sidebar:
    st.header("Settings")
    st.write("Add your API keys in **.streamlit/secrets.toml** or env vars.")
    fred_ok = bool(FRED_API_KEY)
    te_ok = bool(TE_API_KEY)
    st.markdown(f"**FRED API:** {'✅ Set' if fred_ok else '❌ Missing'}")
    st.markdown(f"**TradingEconomics API (optional):** {'✅ Set' if te_ok else '❌ Missing'}")
    lookback_years = st.slider("Chart lookback (years)", 2, 25, 5)
    st.caption("Tip: Get a FRED key free: https://fredaccount.stlouisfed.org/apikeys")

# ----------------------------
# Cards (latest prints)
# ----------------------------
col_cards = st.container()
grid_cols = st.columns(3)

def card(metric_name: str, col):
    meta = INDICATORS[metric_name]
    raw = fred_get_series(meta["id"], meta["freq"])
    series = compute_transform(raw, meta["transform"])
    latest, d = latest_value(series)
    chg_1 = pct_change_latest(series, 1) if meta["transform"] in ("level",) else None

    with col:
        st.subheader(metric_name)
        if latest is None:
            st.error("No data or API key missing.")
            return
        st.metric(
            label=f"Latest (as of {d})",
            value=format_val(latest, 2),
            delta=(f"{format_val(chg_1,2)}% vs prior" if chg_1 is not None else None),
        )

# Render cards
for i, name in enumerate(INDICATORS.keys()):
    card(name, grid_cols[i % 3])

st.markdown("---")

# ----------------------------
# Charts
# ----------------------------
st.header("Time Series")
sel = st.multiselect(
    "Pick indicators to chart",
    options=list(INDICATORS.keys()),
    default=["CPI (YoY, %)", "Core PCE (YoY, %)", "Unemployment Rate (%)"],
)

for name in sel:
    meta = INDICATORS[name]
    raw = fred_get_series(meta["id"], meta["freq"])
    series = compute_transform(raw, meta["transform"])
    if series is None or series.empty:
        st.warning(f"No data for {name}.")
        continue
    cutoff = series["date"] >= (pd.Timestamp.today() - pd.DateOffset(years=lookback_years))
    series = series.loc[cutoff]
    st.line_chart(series.set_index("date")["value"], height=260, use_container_width=True)
    latest, d = latest_value(series)
    st.caption(f"Latest {name}: **{format_val(latest,2)}** (as of {d})")

st.markdown("---")

# ----------------------------
# Economic Calendar (optional via TradingEconomics)
# ----------------------------
st.header("Upcoming U.S. Releases (Live Calendar)")
if not TE_API_KEY:
    st.info("Add a Trading Economics API key to show the real-time calendar. Free keys available at tradingeconomics.com.")
else:
    @st.cache_data(ttl=30)
    def te_calendar(start: dt.date, end: dt.date) -> pd.DataFrame:
        # Docs: https://docs.tradingeconomics.com/?python#calendar
        url = "https://api.tradingeconomics.com/calendar/country/united%20states"
        params = {
            "d1": start.isoformat(),
            "d2": end.isoformat(),
            "c": TE_API_KEY,
            "format": "json",
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        items = r.json()
        if not items:
            return pd.DataFrame()
        df = pd.DataFrame(items)
        keep = [
            "Date", "Country", "Category", "Event", "Reference", "Actual", "Previous",
            "Forecast", "Importance"
        ]
        df = df[[k for k in keep if k in df.columns]]
        df["Date"] = pd.to_datetime(df["Date"]).dt.tz_convert("US/Eastern")
        df = df.sort_values("Date")
        return df

    today = dt.date.today()
    d1 = today - dt.timedelta(days=1)
    d2 = today + dt.timedelta(days=7)
    cal = te_calendar(d1, d2)

    if cal.empty:
        st.warning("No events returned.")
    else:
        # Highlight next events
        now_et = pd.Timestamp.now(tz="US/Eastern")
        upcoming_mask = cal["Date"] >= now_et - pd.Timedelta(minutes=5)
        upcoming = cal.loc[upcoming_mask].head(15)

        st.subheader("Next Up (ET)")
        st.dataframe(
            upcoming.assign(
                Date=upcoming["Date"].dt.strftime("%a %b %d, %I:%M %p"),
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("This Week — Details")
        st.dataframe(
            cal.assign(Date=cal["Date"].dt.strftime("%a %b %d, %I:%M %p")),
            use_container_width=True,
            hide_index=True,
        )

st.markdown("---")

st.caption(
    "Sources: FRED (St. Louis Fed) for time series; Trading Economics for live calendar. "
    "This dashboard auto-refreshes during market hours. Values are for informational purposes only."
)
