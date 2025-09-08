# U.S. Macro Dashboard (Streamlit)

A lightweight dashboard that shows headline U.S. macro indicators from FRED and (optionally) a live economic calendar via Trading Economics.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

## API keys
Create `.streamlit/secrets.toml` (or set env vars):

```toml
FRED_API_KEY = "your_fred_api_key_here"
TE_API_KEY = "your_trading_economics_key_here"  # optional
```

- Get a free FRED key: https://fredaccount.stlouisfed.org/apikeys
- Get a Trading Economics key: https://tradingeconomics.com/ (free tier available)

## Notes
- The app auto-refreshes every minute during U.S. market hours.
- You can customize the indicators in the `INDICATORS` map in `app.py`.
