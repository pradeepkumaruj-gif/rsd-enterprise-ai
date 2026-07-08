from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import os
import threading
import pandas as pd
from supabase import create_client

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# --- Supabase connection (reads from env vars, set these in Railway) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # secret key, not publishable key
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_all_rows(table_name: str) -> pd.DataFrame:
    """Supabase returns max 1000 rows per call, so page through until done."""
    all_rows = []
    page_size = 1000
    start = 0
    while True:
        response = supabase.table(table_name).select("*").range(start, start + page_size - 1).execute()
        batch = response.data
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return pd.DataFrame(all_rows)


# df starts empty -- the server responds to requests immediately (so Railway's
# health check passes right away), while the real data loads in a background
# thread. Loading 300K+ rows via paginated API calls takes a couple of
# minutes; doing this at import time blocked the whole server from
# responding, which is why Railway reported "Application failed to respond".
df = pd.DataFrame()
data_loading_status = "loading"  # loading -> ready | failed


def load_data_in_background():
    global df, data_loading_status
    try:
        print("Loading delhi_industry data from Supabase...")
        df = fetch_all_rows("delhi_industry")
        data_loading_status = "ready"
        print(f"Loaded {len(df)} rows.")
    except Exception as e:
        data_loading_status = "failed"
        print(f"Failed to load data: {e}")


threading.Thread(target=load_data_in_background, daemon=True).start()

# Column name shortcuts (delhi_industry schema uses snake_case)
COL_TSE = 'salesman_tse'
COL_DEPT = 'department'
COL_MONTH = 'month'
COL_PARTY = 'shop_name_as_per_company_data'   # business's own shop naming
COL_BRAND = 'brand_name_as_per_company_data'
COL_PRODUCT = 'item_name_as_per_industry_data'
COL_QTY = 'sale_qty_in_box'
COL_LIQUOR_TYPE = 'liquor_type'
COL_SHOP_CODE = 'shop_code'
COL_CATEGORY = 'category'
COL_COMPANY = 'company_name'


class ChatRequest(BaseModel):
    message: str


@app.get("/")
def home():
    return {
        "message": "RSD Enterprise AI Ready! 🚀",
        "data_status": data_loading_status,
        "rows_loaded": len(df),
    }


@app.post("/refresh")
def refresh_data():
    """Re-pull the latest data from Supabase without restarting the server.
    Call this after loading a new month's CSV via load_to_delhi_industry.py"""
    threading.Thread(target=load_data_in_background, daemon=True).start()
    return {"message": "Refresh started in background"}


import json

# Maps friendly dimension names (what Claude will use in its query spec) to
# actual dataframe column names. Keeping this mapping means we never trust
# raw column names coming back from Claude -- only these known-safe keys.
DIMENSIONS = {
    'month': COL_MONTH,
    'department': COL_DEPT,
    'tse': COL_TSE,
    'party': COL_PARTY,
    'brand': COL_BRAND,
    'product': COL_PRODUCT,
    'liquor_type': COL_LIQUOR_TYPE,
    'shop_code': COL_SHOP_CODE,
    'category': COL_CATEGORY,
    'company': COL_COMPANY,
}

QUERY_PARSER_SYSTEM = f"""Tu ek query parser hai RSD liquor sales dataset ke liye.
User ke sawaal ko is JSON format mein todo (SIRF JSON return karo, kuch aur nahi):

{{
  "group_by": ["dimension1", "dimension2"],
  "filters": {{"dimension": "value to match", "dimension2": "value2"}},
  "top_n": 10,
  "sort_desc": true
}}

Available dimensions (sirf yehi use karo): {list(DIMENSIONS.keys())}
Metric hamesha "sale_qty_in_box" ka sum hota hai -- ismein koi choice nahi.

Rules:
- group_by mein 1-3 dimensions daalo jo user pucha hai (jaise "TSE department wise" -> ["tse", "department"])
- filters mein JITNE BHI dimensions ka specific value user ne mention kiya ho, sab daalo (multiple filters ek saath chal sakte hain -- jaise "April mein DCCWS department ka Whisky" -> {{"month": "Apr", "department": "DCCWS", "liquor_type": "Whisky"}})
- Agar do mahino ka comparison chahiye ("April vs May"), month ko group_by mein daalo, filter mein nahi
- top_n default 10, agar "top 5" jaisa kuch bola hai to wahi number daalo
- Agar sawaal total/overall pucha hai bina kisi grouping ke, group_by ko empty list [] rakho
"""


def parse_query_with_claude(question: str) -> dict:
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        system=QUERY_PARSER_SYSTEM,
        messages=[{"role": "user", "content": question}],
    )
    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def run_query(spec: dict) -> str:
    filtered = df

    # Apply filters (partial, case-insensitive match -- so "dccws" or "DCCWS" both work)
    for dim, value in (spec.get("filters") or {}).items():
        col = DIMENSIONS.get(dim)
        if col and col in filtered.columns:
            filtered = filtered[filtered[col].astype(str).str.contains(str(value), case=False, na=False)]

    if filtered.empty:
        return "Is filter ke liye koi data nahi mila."

    group_by = [DIMENSIONS[d] for d in (spec.get("group_by") or []) if d in DIMENSIONS]
    top_n = spec.get("top_n") or 10
    sort_desc = spec.get("sort_desc", True)

    if not group_by:
        total = filtered[COL_QTY].sum()
        return f"Total Sale Qty: {total}"

    result = filtered.groupby(group_by)[COL_QTY].sum()
    result = result.sort_values(ascending=not sort_desc)
    result = result.head(top_n)
    return result.to_string()


@app.post("/chat")
def chat(request: ChatRequest):
    if data_loading_status == "loading":
        return {"reply": "⏳ Data abhi Supabase se load ho raha hai, thodi der mein try karo (1-2 minute)."}
    if data_loading_status == "failed" or df.empty:
        return {"reply": "⚠️ Data load nahi ho paya. Backend logs check karo."}

    try:
        spec = parse_query_with_claude(request.message)
        data = run_query(spec)
    except Exception as e:
        print(f"Query parse/run failed: {e}")
        data = ("Sawaal samajh nahi aaya. Try karo: 'Top TSE April mein', "
                "'DCCWS department ka top brand', 'May vs April total', etc.")

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=600,
        system="Tu RSD Sales AI assistant hai. Data ko markdown table format mein present kar jab multiple columns hon. | col1 | col2 | format use karo. Emojis use karo. Hinglish mein baat karo.",
        messages=[{"role": "user", "content": f"Sawaal: {request.message}\nData: {data}"}]
    )
    return {"reply": response.content[0].text}
