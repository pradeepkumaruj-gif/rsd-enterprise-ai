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


@app.post("/chat")
def chat(request: ChatRequest):
    if data_loading_status == "loading":
        return {"reply": "⏳ Data abhi Supabase se load ho raha hai, thodi der mein try karo (1-2 minute)."}
    if data_loading_status == "failed" or df.empty:
        return {"reply": "⚠️ Data load nahi ho paya. Backend logs check karo."}

    question = request.message.lower()

    if 'top tse' in question or 'best tse' in question:
        result = df.groupby(COL_TSE)[COL_QTY].sum().sort_values(ascending=False).head(3)
        data = f"Top 3 TSE:\n{result.to_string()}"
    elif 'tse' in question and ('month' in question or 'mahina' in question):
        result = df.pivot_table(index=COL_TSE, columns=COL_MONTH, values=COL_QTY, aggfunc='sum', fill_value=0)
        result['Total'] = result.sum(axis=1)
        result = result.sort_values('Total', ascending=False)
        result.columns.name = None
        data = f"TSE Month wise Sales:\n{result.to_string()}"
    elif 'tse' in question and ('dept' in question or 'department' in question):
        result = df.groupby([COL_TSE, COL_DEPT])[COL_QTY].sum().reset_index()
        result = result.sort_values(COL_QTY, ascending=False)
        data = f"TSE Department wise Sales:\n{result.to_string(index=False)}"
    elif 'tse' in question or 'sab tse' in question or 'all tse' in question or 'sales man' in question:
        result = df.groupby(COL_TSE)[COL_QTY].sum().sort_values(ascending=False)
        data = f"All TSE Performance:\n{result.to_string()}"
    elif ('dept' in question or 'department' in question or 'vibhag' in question) and ('month' in question or 'mahina' in question):
        result = df.pivot_table(index=COL_DEPT, columns=COL_MONTH, values=COL_QTY, aggfunc='sum', fill_value=0)
        result['Total'] = result.sum(axis=1)
        result = result.sort_values('Total', ascending=False)
        result.columns.name = None
        data = f"Department Month wise Sales:\n{result.to_string()}"
    elif 'dept' in question or 'department' in question or 'vibhag' in question:
        result = df.groupby(COL_DEPT)[COL_QTY].sum().sort_values(ascending=False)
        data = f"Department Sales:\n{result.to_string()}"
    elif 'party' in question and ('month' in question or 'mahina' in question):
        result = df.pivot_table(index=COL_PARTY, columns=COL_MONTH, values=COL_QTY, aggfunc='sum', fill_value=0)
        result['Total'] = result.sum(axis=1)
        result = result.sort_values('Total', ascending=False).head(10)
        result.columns.name = None
        data = f"Party Month wise Sales:\n{result.to_string()}"
    elif 'top party' in question or 'best party' in question:
        result = df.groupby(COL_PARTY)[COL_QTY].sum().sort_values(ascending=False).head(5)
        data = f"Top 5 Parties:\n{result.to_string()}"
    elif 'party' in question:
        result = df.groupby(COL_PARTY)[COL_QTY].sum().sort_values(ascending=False).head(10)
        data = f"Top 10 Parties:\n{result.to_string()}"
    elif 'brand' in question and ('month' in question or 'mahina' in question):
        result = df.pivot_table(index=COL_BRAND, columns=COL_MONTH, values=COL_QTY, aggfunc='sum', fill_value=0)
        result['Total'] = result.sum(axis=1)
        result = result.sort_values('Total', ascending=False).head(10)
        result.columns.name = None
        data = f"Brand wise Month wise Sales:\n{result.to_string()}"
    elif 'brand' in question and ('dept' in question or 'department' in question):
        result = df.groupby([COL_DEPT, COL_BRAND])[COL_QTY].sum().reset_index()
        result = result.sort_values(COL_QTY, ascending=False).head(15)
        data = f"Brand wise Department wise Sales:\n{result.to_string(index=False)}"
    elif 'brand' in question:
        result = df.groupby(COL_BRAND)[COL_QTY].sum().sort_values(ascending=False).head(10)
        data = f"Top Brands:\n{result.to_string()}"
    elif 'month' in question or 'mahina' in question or 'monthly' in question:
        result = df.groupby(COL_MONTH)[COL_QTY].sum().sort_values(ascending=False)
        data = f"Monthly Sales:\n{result.to_string()}"
    elif 'liquor' in question or 'type' in question:
        result = df.groupby(COL_LIQUOR_TYPE)[COL_QTY].sum().sort_values(ascending=False)
        data = f"Liquor Type wise Sales:\n{result.to_string()}"
    elif 'product' in question or 'item' in question:
        result = df.groupby(COL_PRODUCT)[COL_QTY].sum().sort_values(ascending=False).head(15)
        data = f"Top Products:\n{result.to_string()}"
    elif 'total' in question or 'kul' in question:
        total = df[COL_QTY].sum()
        data = f"Total Sales Qty (all boxes): {total}"
    elif 'shop code' in question or 'shop' in question:
        result = df.groupby(COL_SHOP_CODE)[COL_QTY].sum().sort_values(ascending=False).head(10)
        data = f"Top Shops by Sale Qty:\n{result.to_string()}"
    else:
        data = ("RSD Sales Data available (Delhi Industry, April + May 2026). Puchho: "
                "Top TSE, TSE Month wise, Department, Party Month wise, Brand Month wise, "
                "Liquor Type, Product, Shop Code, Total")

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=600,
        system="Tu RSD Sales AI assistant hai. Data ko markdown table format mein present kar jab multiple columns hon. | col1 | col2 | format use karo. Emojis use karo. Hinglish mein baat karo.",
        messages=[{"role": "user", "content": f"Sawaal: {request.message}\nData: {data}"}]
    )
    return {"reply": response.content[0].text}
