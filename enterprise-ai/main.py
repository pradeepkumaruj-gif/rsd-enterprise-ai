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
COL_SEGMENT = 'segment'
COL_BD_SEGMENT = 'bd_segment'


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
    'segment': COL_SEGMENT,
    'bd_segment': COL_BD_SEGMENT,
}

QUERY_PARSER_SYSTEM = f"""Tu ek query parser hai RSD liquor sales dataset ke liye.
User ke sawaal ko is JSON format mein todo (SIRF JSON return karo, kuch aur nahi):

{{
  "metric": "sum",
  "group_by": ["dimension1", "dimension2"],
  "filters": {{"dimension": "value to match", "dimension2": "value2"}},
  "share_filter": {{}},
  "top_n": 10,
  "sort_desc": true,
  "count_dimension": null
}}

Available dimensions (sirf yehi use karo): {list(DIMENSIONS.keys())}

IMPORTANT -- "bd_segment" dimension ke real values yeh hain (inhe EXACT ek hi value maano, todo mat):
"Semi Pre Whisky", "Semi Pre Vodka", "Regular Whisky", "Premium Whisky", "Super Pre Whisky",
"Scotch", "Premium Vodka", "Breezer", "Wine", "Single Malt", "Premium Gin", "Super Premium Gin",
"Premium Rum", "Liqueur", "RTD", "Tequila", "Super Pre Rum", "Brandy", "Semi Pre Rum"
Agar user "Semi Pre Whisky" ya "Regular Whisky" jaisa kuch bole, yeh EK filter hai bd_segment pe --
ise liquor_type mein mat daalo aur "Whisky" alag se filter mat karo.

"liquor_type" dimension broader hai (sirf: Whisky, Vodka, Alcopop, Wine, Gin, Rum, Liqueur, Brandy,
Mixed Alcoholic Beverages) -- jab user generic "Whisky" ya "Rum" bole (bina Premium/Regular/Semi
qualifier ke), tab liquor_type use karo.

"metric" teen types ka ho sakta hai:
- "sum" (default) -- sale_qty_in_box ka total. Yeh QUANTITY hai (boxes), currency NAHI hai.
- "count_distinct" -- jab user "kitne total X hai" jaisa pooche (jaise "total kitne shop code hai", "kitne alag brand hain"). Is case mein "count_dimension" field mein woh dimension daalo jiska unique count chahiye, aur group_by/filters normal rahenge.
- "market_share" -- jab user kisi specific brand/product/company ka "market share" ya "% hissa" total sale mein poochta hai (jaise "Dennis ka market share kya hai har shop mein"). Is case mein:
  - "filters" mein overall context filters daalo (jaise month)
  - "share_filter" mein woh specific dimension+value daalo jiska share nikalna hai (jaise {{"brand": "Dennis"}})
  - "group_by" mein woh dimensions daalo jiske hisaab se share dikhana hai (jaise shop-wise ya department-wise share ke liye ["party", "department"]; agar sirf ek overall number chahiye, group_by empty [] rakho)

Rules:
- group_by mein 1-3 dimensions daalo jo user pucha hai (jaise "TSE department wise" -> ["tse", "department"])
- filters mein JITNE BHI dimensions ka specific value user ne mention kiya ho, sab daalo (multiple filters ek saath chal sakte hain -- jaise "April mein DCCWS department ka Whisky" -> {{"month": "Apr", "department": "DCCWS", "liquor_type": "Whisky"}})
- Agar do mahino ka comparison chahiye ("April vs May"), month ko group_by mein daalo, filter mein nahi
- top_n default 10, agar "top 5" jaisa kuch bola hai to wahi number daalo
- Agar sawaal total/overall pucha hai bina kisi grouping ke, group_by ko empty list [] rakho
- "kitne total/alag/unique X hai" jaise sawaalon ke liye metric="count_distinct" use karo, group_by ko empty [] rakho
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

    # "kitne total/alag X hai" style questions -- count actual unique values,
    # not just the top-N shown in a group_by (that was Bug: system was
    # mislabeling "top 10 rows" as "total unique count", which is wrong).
    if spec.get("metric") == "count_distinct":
        count_dim = spec.get("count_dimension")
        col = DIMENSIONS.get(count_dim)
        if col and col in filtered.columns:
            unique_count = filtered[col].nunique()
            return f"Total unique {count_dim}: {unique_count}"
        return "count_dimension valid nahi thi."

    # Market share: what % of total sale (within each group) does a specific
    # brand/product/company/etc make up. E.g. "Dennis ka market share har
    # shop mein" -> for each shop, (Dennis qty / total qty in that shop) * 100
    if spec.get("metric") == "market_share":
        share_filter = spec.get("share_filter") or {}
        subset = filtered
        for dim, value in share_filter.items():
            col = DIMENSIONS.get(dim)
            if col and col in subset.columns:
                subset = subset[subset[col].astype(str).str.contains(str(value), case=False, na=False)]

        group_by = [DIMENSIONS[d] for d in (spec.get("group_by") or []) if d in DIMENSIONS]
        top_n = spec.get("top_n") or 10
        sort_desc = spec.get("sort_desc", True)

        if not group_by:
            total = filtered[COL_QTY].sum()
            subset_total = subset[COL_QTY].sum()
            share = (subset_total / total * 100) if total else 0
            return (f"Subset Qty: {subset_total}, Total Qty: {total}, "
                    f"Market Share: {share:.2f}%")

        total_by_group = filtered.groupby(group_by)[COL_QTY].sum()
        subset_by_group = subset.groupby(group_by)[COL_QTY].sum()
        combined = pd.DataFrame({
            'subset_qty': subset_by_group,
            'total_qty': total_by_group,
        }).fillna(0)
        combined['market_share_pct'] = (
            combined['subset_qty'] / combined['total_qty'].replace(0, pd.NA) * 100
        ).round(2)
        combined = combined.sort_values('market_share_pct', ascending=not sort_desc)
        combined = combined.head(top_n)
        return combined.to_string()

    group_by = [DIMENSIONS[d] for d in (spec.get("group_by") or []) if d in DIMENSIONS]
    top_n = spec.get("top_n") or 10
    sort_desc = spec.get("sort_desc", True)

    if not group_by:
        total = filtered[COL_QTY].sum()
        return f"Total Sale Qty (boxes): {total}"

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
        system=(
            "Tu RSD Sales AI assistant hai. Data 'sale_qty_in_box' hai -- yeh BOXES ki QUANTITY hai, "
            "RUPEES/CURRENCY NAHI hai. Kabhi bhi ₹ ya 'Rs' symbol use mat karna is data ke liye -- "
            "sirf 'units' ya 'boxes' bolna. Data ko markdown table format mein present kar jab multiple "
            "columns hon. | col1 | col2 | format use karo. Emojis use karo. Hinglish mein baat karo. "
            "Agar data mein 'Total unique X: N' jaisa kuch mile, usko as-is present karo -- number mat badalna."
        ),
        messages=[{"role": "user", "content": f"Sawaal: {request.message}\nData: {data}"}]
    )
    return {"reply": response.content[0].text}
