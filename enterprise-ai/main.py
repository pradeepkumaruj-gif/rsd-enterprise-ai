from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import os
import threading
import pandas as pd
from supabase import create_client
from smart_query_engine import SmartQueryEngine

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
COL_QTY = 'sale_qty_in_box'
COL_LIQUOR_TYPE = 'liquor_type'
COL_SHOP_CODE = 'shop_code'
COL_CATEGORY = 'category'
COL_COMPANY = 'company_name'
COL_SEGMENT = 'segment'
COL_BD_SEGMENT = 'bd_segment'
COL_PACK_SIZE = 'product_itemsize_name'


def get_current_and_previous_month_df():
    """Returns (df_current_month, df_previous_month, current_label, previous_label).
    Uses actual chronological order of the 'month' column (e.g. 'Apr-26', 'May-26'),
    NOT alphabetical file_source order -- alphabetical sorting breaks once months
    like Jun/Jul/Aug are added (e.g. 'Aug' < 'Jun' alphabetically but not in time).
    Returns (None, None, None, None) if fewer than 2 distinct months are loaded."""
    if df.empty:
        return None, None, None, None
    unique_months = df[COL_MONTH].unique().tolist()
    if len(unique_months) < 2:
        return None, None, None, None
    parsed = sorted(unique_months, key=lambda m: pd.to_datetime(m, format='%b-%y', errors='coerce'))
    previous_label, current_label = parsed[-2], parsed[-1]
    df_current = df[df[COL_MONTH] == current_label]
    df_previous = df[df[COL_MONTH] == previous_label]
    return df_current, df_previous, current_label, previous_label


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
    'liquor_type': COL_LIQUOR_TYPE,
    'shop_code': COL_SHOP_CODE,
    'category': COL_CATEGORY,
    'company': COL_COMPANY,
    'segment': COL_SEGMENT,
    'bd_segment': COL_BD_SEGMENT,
    'pack_size': COL_PACK_SIZE,
}

QUERY_PARSER_SYSTEM = f"""Tu ek query parser hai RSD liquor sales dataset ke liye.
User ke sawaal ko is JSON format mein todo (SIRF JSON return karo, kuch aur nahi):

{{
  "intent": "generic",
  "metric": "sum",
  "group_by": ["dimension1", "dimension2"],
  "filters": {{"dimension": "value to match", "dimension2": "value2"}},
  "share_filter": {{}},
  "top_n": 10,
  "sort_desc": true,
  "count_dimension": null,
  "params": {{}}
}}

"intent" batata hai kaunsa engine chalana hai. Available intents:

1. "generic" (default) -- flexible filter/group_by/metric queries jaisa upar diya hai. Ismein
   "metric" "sum" / "count_distinct" / "market_share" ho sakta hai (neeche detail hai).

2. "brand_report" -- ek specific brand ka poora profile (market %, top shops, bd_segment).
   params: {{"brand_name": "..."}}
   Trigger: "Dennis ka poora report do", "DENNIS SPECIAL GOLD WHISKY ke baare mein batao"

3. "smart_query" -- BD Segment ke andar ek specific brand ka position.
   params: {{"bd_segment": "...", "brand_name": "..."}}
   Trigger: "Semi Pre Whisky mein Dennis ka kya haal hai"

4. "market_share_dimension" -- kisi bhi dimension (company/liquor_type/segment/bd_segment/
   department/tse) ka pura market-share ranking.
   params: {{"dimension": "company_name" | "liquor_type" | "segment" | "bd_segment" | "department" | "salesman_tse", "top_n": 10}}
   Trigger: "Company wise market share dikhao", "Department wise market share"

5. "shop_comparison" -- ek brand vs uske top competitors (same segment), shop-by-shop table.
   params: {{"brand_name": "...", "top_n": 10}}
   Trigger: "Dennis vs uske competitors shop wise"

6. "brand_share_filter" -- BD Segment ke andar leading (>=threshold%) ya long-tail (<threshold%) brands.
   params: {{"bd_segment": "...", "threshold": 5.0, "mode": "above" or "below"}}
   Trigger: "Semi Pre Whisky mein 5% se zyada share wale brands", "kaunse brands 5% se kam hain"

7. "compare_brands" -- 2 se 10 brands side-by-side compare.
   params: {{"brands": ["brand1", "brand2", ...]}}
   Trigger: "Dennis vs 8PM vs Royal Ace compare karo"

8. "cross_reference_shops" -- Brand A ke top shops mein Brand B kitna bikta hai (gap analysis).
   params: {{"primary_brand": "...", "secondary_brand": "...", "top_n": 10}}
   Trigger: "Dennis ke top shops mein 8PM ka kya sale hai"

9. "mom_gainers_losers" -- Month-over-month gainers/losers, automatically latest vs pichla mahina
   use karta hai (koi month specify karne ki zaroorat nahi).
   params: {{"group_col": "bd_segment" or "segment", "min_base": 500, "top_n": 10}}
   Trigger: "is mahine ke gainers losers dikhao", "kaunse brands grow kiye"

10. "brand_ranking" -- ek brand ka rank BD Segment, Segment, aur overall market mein.
    params: {{"brand_name": "..."}}
    Trigger: "Dennis ka rank kya hai"

11. "brand_mom_check" -- ek specific brand ka month-over-month change (automatically latest vs pichla mahina).
    params: {{"brand_name": "..."}}
    Trigger: "Dennis pichle mahine se kaisa perform kiya", "Dennis ka growth"

Agar sawaal upar ke kisi specific intent (2-11) se match nahi karta, "generic" use karo.

Available dimensions (generic intent ke liye, sirf yehi use karo): {list(DIMENSIONS.keys())}

IMPORTANT -- "bd_segment" dimension ke real values yeh hain (inhe EXACT ek hi value maano, todo mat):
"Semi Pre Whisky", "Semi Pre Vodka", "Regular Whisky", "Premium Whisky", "Super Pre Whisky",
"Scotch", "Premium Vodka", "Breezer", "Wine", "Single Malt", "Premium Gin", "Super Premium Gin",
"Premium Rum", "Liqueur", "RTD", "Tequila", "Super Pre Rum", "Brandy", "Semi Pre Rum"
Agar user "Semi Pre Whisky" ya "Regular Whisky" jaisa kuch bole, yeh EK filter hai bd_segment pe --
ise liquor_type mein mat daalo aur "Whisky" alag se filter mat karo.

"liquor_type" dimension broader hai (sirf: Whisky, Vodka, Alcopop, Wine, Gin, Rum, Liqueur, Brandy,
Mixed Alcoholic Beverages) -- jab user generic "Whisky" ya "Rum" bole (bina Premium/Regular/Semi
qualifier ke), tab liquor_type use karo.

"pack_size" dimension ke real values yeh hain: "Nip, Quarter", "Bottle", "Half", "Pint",
"Miniature 90 ml", "Miniature 60 ml", "500 ML", "Imported 275 ml", "Imported Bottle 1000 ml",
"Imported Bottle 2000 ml". Jab user "bottle wise" ya "quarter wise" ya "nip wise" sale pooche,
yeh dimension use karo.

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


def resolve_brand_name(partial_name: str) -> str:
    """User often types a short/partial brand name ('Royal Ace') while the
    real database value is longer ('ROYAL ACE RARE BLENDED WHISKY'). Exact
    matching would fail and incorrectly report 'not found'. This resolves
    the partial name to the closest real brand name in the data, so the
    downstream SmartQueryEngine call gets the correct full name.
    Falls back to returning the original input if nothing matches at all
    (the engine's own 'not found' handling takes over from there)."""
    if df.empty or not partial_name:
        return partial_name

    brand_col = df[COL_BRAND].astype(str)

    # 1. Exact match (case-insensitive) -- already correct, nothing to do
    exact = brand_col.str.upper() == partial_name.upper()
    if exact.any():
        return df.loc[exact, COL_BRAND].iloc[0]

    # 2. Partial/contains match -- pick the one with the highest total sales
    #    among matches (most likely the brand the person actually means)
    contains = brand_col.str.contains(partial_name, case=False, na=False, regex=False)
    if contains.any():
        matches = df.loc[contains]
        best = matches.groupby(COL_BRAND)[COL_QTY].sum().sort_values(ascending=False)
        return best.index[0]

    # 3. No match at all -- return as-is, let the engine report "not found"
    return partial_name


def run_special_intent(intent: str, params: dict) -> str:
    """Routes a parsed intent to the matching SmartQueryEngine function.
    Returns a JSON string of the result (or an error message string)."""
    engine = SmartQueryEngine(df)  # cheap wrapper around current df, rebuilt fresh each call

    # Auto-resolve partial brand names to their full canonical database names
    # (e.g. "Royal Ace" -> "ROYAL ACE RARE BLENDED WHISKY") so exact-match
    # lookups in SmartQueryEngine don't incorrectly report "not found".
    if "brand_name" in params:
        params["brand_name"] = resolve_brand_name(params["brand_name"])
    if "primary_brand" in params:
        params["primary_brand"] = resolve_brand_name(params["primary_brand"])
    if "secondary_brand" in params:
        params["secondary_brand"] = resolve_brand_name(params["secondary_brand"])
    if "brands" in params and isinstance(params["brands"], list):
        params["brands"] = [resolve_brand_name(b) for b in params["brands"]]

    try:
        if intent == "brand_report":
            result = engine.brand_report(params["brand_name"], top_shops=params.get("top_shops", 10))

        elif intent == "smart_query":
            result = engine.smart_query(params["bd_segment"], params["brand_name"])

        elif intent == "market_share_dimension":
            result = engine.market_share(params["dimension"], top_n=params.get("top_n", 10))

        elif intent == "shop_comparison":
            result = engine.shop_comparison(params["brand_name"], top_n=params.get("top_n", 10))

        elif intent == "brand_share_filter":
            result = engine.brand_share_filter(
                params["bd_segment"],
                threshold=params.get("threshold", 5.0),
                mode=params.get("mode", "above"),
            )

        elif intent == "compare_brands":
            result = engine.compare_brands(params["brands"])

        elif intent == "cross_reference_shops":
            result = engine.cross_reference_shops(
                params["primary_brand"], params["secondary_brand"], top_n=params.get("top_n", 10)
            )

        elif intent == "mom_gainers_losers":
            df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
            if df_current is None:
                return "MoM comparison ke liye kam se kam 2 mahino ka data chahiye. Abhi sirf 1 mahina loaded hai."
            result = SmartQueryEngine.mom_gainers_losers(
                df_current, df_previous,
                group_col=params.get("group_col", "bd_segment"),
                min_base=params.get("min_base", 500),
                top_n=params.get("top_n", 10),
            )
            result["current_month"] = cur_label
            result["previous_month"] = prev_label

        elif intent == "brand_ranking":
            result = engine.brand_ranking(params["brand_name"])

        elif intent == "brand_mom_check":
            df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
            if df_current is None:
                return "MoM comparison ke liye kam se kam 2 mahino ka data chahiye. Abhi sirf 1 mahina loaded hai."
            result = SmartQueryEngine.brand_mom_check(params["brand_name"], df_current, df_previous)
            result["current_month"] = cur_label
            result["previous_month"] = prev_label

        else:
            return f"Unknown intent: {intent}"

        return json.dumps(result, default=str)

    except KeyError as e:
        return f"Zaroori parameter missing: {e}"
    except Exception as e:
        print(f"run_special_intent failed for {intent}: {e}")
        return f"Query run karne mein error aayi: {e}"


@app.post("/chat")
def chat(request: ChatRequest):
    if data_loading_status == "loading":
        return {"reply": "⏳ Data abhi Supabase se load ho raha hai, thodi der mein try karo (1-2 minute)."}
    if data_loading_status == "failed" or df.empty:
        return {"reply": "⚠️ Data load nahi ho paya. Backend logs check karo."}

    try:
        spec = parse_query_with_claude(request.message)
        intent = spec.get("intent", "generic")
        if intent == "generic":
            data = run_query(spec)
        else:
            data = run_special_intent(intent, spec.get("params") or {})
    except Exception as e:
        print(f"Query parse/run failed: {e}")
        data = ("Sawaal samajh nahi aaya. Try karo: 'Top TSE April mein', "
                "'DCCWS department ka top brand', 'May vs April total', 'Dennis ka rank kya hai', etc.")

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=700,
        system=(
            "Tu RSD Sales AI assistant hai. Data 'sale_qty_in_box' hai -- yeh BOXES ki QUANTITY hai, "
            "RUPEES/CURRENCY NAHI hai. Kabhi bhi ₹ ya 'Rs' symbol use mat karna is data ke liye -- "
            "sirf 'units' ya 'boxes' bolna. Data kabhi plain text ho sakta hai, kabhi JSON (structured "
            "result) -- dono cases mein data ko markdown table format mein present kar jab multiple "
            "columns/fields hon. | col1 | col2 | format use karo. Emojis use karo. Hinglish mein baat karo. "
            "JSON mein agar 'found': false ho, to clearly bolo ki data nahi mila, aur agar 'similar_brands' "
            "jaisa suggestion mile to woh dikhao. Numbers ko JSON se as-is lo, khud se mat calculate karo. "
            "COMPARISON queries (compare_brands, shop_comparison, cross_reference_shops) ke liye: HAMESHA "
            "EK HI TABLE banao jisme har brand/item ek ROW ho aur metrics COLUMNS hon -- alag-alag blocks "
            "ya paragraphs mein mat todo, chahe koi brand na mila ho (uski row mein 'Not Found' likh do, "
            "baaki rows normal dikhao usi table mein)."
        ),
        messages=[{"role": "user", "content": f"Sawaal: {request.message}\nData: {data}"}]
    )
    return {"reply": response.content[0].text}
