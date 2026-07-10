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
    """Supabase returns max 1000 rows per call, so page through until done.

    CRITICAL: .order("id") is required here. Without an explicit stable
    sort, Postgres/PostgREST does NOT guarantee the same row ordering
    across separate .range() calls -- meaning different pages could
    overlap (same row fetched twice) or leave gaps (a row skipped
    entirely), silently corrupting aggregate sums. This was confirmed as
    the root cause of inconsistent/wrong totals appearing on different
    reloads (e.g. Dennis's April qty showing as 27,837 one time and
    26,681 another, when the verified correct value in Supabase is
    31,536). Ordering by the primary key guarantees every row is fetched
    exactly once, in the same order, every single time.
    """
    all_rows = []
    page_size = 1000
    start = 0
    while True:
        response = (
            supabase.table(table_name)
            .select("*")
            .order("id")
            .range(start, start + page_size - 1)
            .execute()
        )
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
    'bd_segment': COL_BD_SEGMENT,
    'pack_size': COL_PACK_SIZE,
}

QUERY_PARSER_SYSTEM = f"""Tu ek query parser hai RSD liquor sales dataset ke liye.
User ke sawaal ko is JSON format mein todo (SIRF JSON return karo, kuch aur nahi):

{{
  "query_understood": true,
  "clarification_needed": null,
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

"query_understood" aur "clarification_needed" SABSE ZAROORI FIELDS HAIN -- inhe seriously lo:
- "query_understood": true -- SIRF tab jab tumhe 100% confidence ho ki user kya poochh raha hai,
  aur available dimensions/intents mein se sahi mapping ban sakti hai.
- "query_understood": false -- agar sawaal ambiguous hai, incomplete hai, contradictory hai, ya
  kisi aisi cheez ke baare mein hai jo available dimensions/intents mein fit nahi hoti, ya agar
  do alag tarike se interpret ho sakta hai aur dono equally likely lagte hain. GUESS MAT KARO --
  agar doubt hai, false maro aur "clarification_needed" mein SPECIFIC bata do ki kya unclear tha
  aur user kya clarify kare (Hinglish mein, 1 line).
- Jab "query_understood": false ho, baaki saare fields (intent, filters, etc.) ignore kar diye
  jayenge -- unko kuch bhi default value de sakte ho, unka use nahi hoga.
- Yeh galat guess se BEHTAR hai ki tum clearly bol do "clear nahi hai" -- ek galat-samjha sawaal
  ka "sahi" number dena, galat sawaal poochne se zyada nuksaandeh hai.

"intent" batata hai kaunsa engine chalana hai. Available intents:

1. "generic" (default) -- flexible filter/group_by/metric queries jaisa upar diya hai. Ismein
   "metric" "sum" / "count_distinct" / "market_share" ho sakta hai (neeche detail hai).

2. "brand_report" -- ek specific brand ka poora profile (market %, top shops, bd_segment).
   params: {{"brand_name": "..."}}
   Trigger: "Dennis ka poora report do", "DENNIS SPECIAL GOLD WHISKY ke baare mein batao"

3. "smart_query" -- BD Segment ke andar ek specific brand ka position.
   params: {{"bd_segment": "...", "brand_name": "..."}}
   Trigger: "Semi Pre Whisky mein Dennis ka kya haal hai"

4. "market_share_dimension" -- kisi bhi dimension (company/liquor_type/bd_segment/
   department/tse) ka pura market-share ranking.
   params: {{"dimension": "company_name" | "liquor_type" | "bd_segment" | "department" | "salesman_tse", "top_n": 10}}
   Trigger: "Company wise market share dikhao", "Department wise market share"

5. "shop_comparison" -- ek brand vs uske top competitors (same segment), shop-by-shop table.
   params: {{"brand_name": "...", "top_n": 10}}
   Trigger: "Dennis vs uske competitors shop wise"

6. "brand_share_filter" -- BD Segment ke andar leading (>=threshold%) ya long-tail (<threshold%) brands.
   params: {{"bd_segment": "...", "threshold": 5.0, "mode": "above" or "below"}}
   Trigger: "Semi Pre Whisky mein 5% se zyada share wale brands", "kaunse brands 5% se kam hain"

7. "compare_brands" -- 2 se 10 brands side-by-side compare.
   params: {{"brands": ["brand1", "brand2", ...]}}
   IMPORTANT: "brands" list ka ORDER wahi rakho jis order mein user ne brands bole -- PEHLA brand
   jo user bole use ANCHOR maana jayega (agar 3+ brands hain, yeh anchor har comparison table mein
   fixed rehta hai, baaki brands 2-2 karke uske saath chunk hote hain).
   Trigger: "Dennis vs 8PM vs Royal Ace compare karo", "Royal Ace ka in sab brands se comparison
   karo: X, Y, Z, W..." (-> brands: ["Royal Ace", "X", "Y", "Z", "W"], Royal Ace anchor hai)

8. "cross_reference_shops" -- Brand A ke top shops mein Brand B kitna bikta hai (gap analysis).
   params: {{"primary_brand": "...", "secondary_brand": "...", "top_n": 10}}
   Trigger: "Dennis ke top shops mein 8PM ka kya sale hai"

9. "mom_gainers_losers" -- Month-over-month gainers/losers/new-entries/dropped-brands, automatically
   latest vs pichla mahina use karta hai (koi month specify karne ki zaroorat nahi).
   params: {{"group_col": "bd_segment", "min_base": 500, "top_n": 10, "bd_segment_filter": null,
   "sections": ["losers"]}}
   - "bd_segment_filter" optional hai -- agar user ek SPECIFIC category naam bole (jaise "Semi Pre
     Whisky segment mein" ya "Regular Whisky mein"), yahan uska naam daalo taaki result sirf usi
     category tak scoped rahe. IMPORTANT: user kabhi-kabhi ek BRAND ka naam deta hai category ki
     jagah (jaise "Royal Ace segment mein top gainer" -- "Royal Ace" ek brand hai, segment nahi) --
     yeh BILKUL VALID hai, system automatically us brand ka bd_segment nikal lega. Aise cases mein
     bhi "query_understood": true rakho aur seedha "Royal Ace" (ya jo bhi brand bola gaya) ko
     bd_segment_filter mein daal do -- yeh clarification maangne wali situation NAHI hai.
   - "sections" IMPORTANT hai -- user ne EXACTLY kya poocha, sirf wahi section(s) daalo is list mein.
     Options: "gainers", "losers", "new_entries", "dropped". Agar sirf "losers" poocha hai, sirf
     ["losers"] daalo -- gainers/new_entries/dropped MAT daalo. Agar sab kuch poocha ("gainers
     losers dono dikhao"), sabhi relevant section daalo. User ne jo NAHI poocha, use include mat karo.
   - IMPORTANT: "loser/gainer/new entry/dropped" jaise words ke saath agar ek category/segment ka
     naam bhi ho (jaise "Regular Whisky segment looser", "Regular Whisky mein kaun gir raha hai"),
     yeh HAMESHA is intent (mom_gainers_losers) ka case hai -- YEH BRAND-SPECIFIC QUERY NAHI HAI,
     "brand_mom_check" mat use karo, aur user se brand naam MAT poocho -- seedha bd_segment_filter
     mein category daal ke poori losers/gainers LIST return karo.
   Trigger: "is mahine ke gainers losers dikhao" (-> sections: ["gainers","losers"]), "kaunse brands
   grow kiye" (-> sections: ["gainers"]), "Semi Pre Whisky segment mein new brand entry" (->
   bd_segment_filter: "Semi Pre Whisky", sections: ["new_entries"]), "kaunse brands band ho gaye"
   (-> sections: ["dropped"]), "Regular Whisky segment looser" (-> intent: mom_gainers_losers,
   bd_segment_filter: "Regular Whisky", sections: ["losers"], NOT brand_mom_check), "Royal Ace
   segment mein top gainer" (-> bd_segment_filter: "Royal Ace" -- a brand name is fine here,
   system resolves it to Royal Ace's actual bd_segment automatically)

10. "brand_ranking" -- ek brand ka rank BD Segment aur overall market mein.
    params: {{"brand_name": "..."}}
    Trigger: "Dennis ka rank kya hai"

11. "brand_mom_check" -- ek specific brand ka month-over-month change (automatically latest vs pichla mahina).
    params: {{"brand_name": "..."}}
    Trigger: "Dennis pichle mahine se kaisa perform kiya", "Dennis ka growth"

12. "brands_in_bd_segment" -- ek brand ke bd_segment (category) ke andar BAAKI SAB brands ki
    ranked list (kaun kaun se aur brands isi category mein bikte hain, kitna sale hai).
    params: {{"brand_name": "...", "top_n": 15}}
    Trigger: "Royal Ace ke segment mein aur kaunse brands hain", "Dennis ki category mein
    competitors kaun hain", "iske segment mein baaki brands"

13. "company_report" -- ek COMPANY (manufacturer) ki poori sale -- uske SAARE brands milaake,
    na ki sirf ek brand ka number. Agar user brand ka naam de ("Dennis brand ki company ka
    total sale"), "brand_name" param mein daalo -- system automatically us brand ki company
    dhoondh ke uska poora company-wide total nikalega. Agar user seedha company ka naam de,
    "company_name" param use karo.
    params: {{"company_name": null, "brand_name": null, "top_brands": 10}}
    Trigger: "Dennis brand ki company ki total sale kya hai", "OMSONS company ka total business
    kitna hai", "[brand] banane wali company ka overall sale"

14. "compare_companies" -- 2 se 10 companies (manufacturers) side-by-side compare karo
    (market share, rank, brands count, top brand, shops, MoM growth, etc.).
    params: {{"companies": ["company1", "company2", ...]}}
    IMPORTANT: "companies" list ka ORDER wahi rakho jis order mein user ne bola -- PEHLI company
    jo user bole use ANCHOR maana jayega (agar 3+ companies hain, yeh anchor har comparison table
    mein fixed rehta hai, baaki companies 2-2 karke uske saath chunk hote hain) -- bilkul
    compare_brands jaisa pattern.
    Trigger: "in companies ka comparison karo: X, Y, Z...", "Rock and Storm vs OMSONS vs ADS
    compare karo"

Agar sawaal upar ke kisi specific intent (2-14) se match nahi karta, "generic" use karo.

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

IMPORTANT: is dataset mein ek plain "segment" naam ka field NAHI hai (hata diya gaya hai, kyunki
uski values confusing/tautological thi jaise "Whisky Segment Royal Ace"). Jab bhi user "segment"
word use kare kisi bhi tarah ("Royal Ace ka segment kya hai", "segment wise breakdown"), uska
matlab HAMESHA "bd_segment" hi hai (Semi Pre Whisky, Regular Whisky, Premium Whisky, etc.) --
isi ko use karo, kabhi "segment" naam ka alag dimension mat banao.

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


FIELD_DISPLAY_LABELS = {
    'brand': '🥃 Brand',
    'company': '🏢 Company',
    'bd_segment': '🏷️ BD Segment',
    'sale_qty': '📦 Sale Qty (Boxes)',
    'pct_within_bd_segment': '📊 % Within Segment',
    'pct_of_market': '🌍 % of Market',
    'shops_selling': '🏪 Shops Selling',
    'overall_rank': '🏆 Overall Rank',
    'total_sale_qty': '📦 Total Sale Qty (Boxes)',
    'overall_market_share_pct': '🌍 Market Share %',
    'total_companies': '🏢 Total Companies',
    'number_of_brands': '🥃 Number of Brands',
    'number_of_bd_segments': '🏷️ BD Segments Present',
    'top_brand': '⭐ Top Brand (Hero SKU)',
    'top_brand_qty': '📦 Top Brand Qty',
    'top_brand_pct_of_company': '📊 Top Brand % of Company',
    'shops_covered': '🏪 Shops Covered',
    'avg_sale_per_shop': '📈 Avg Sale per Shop',
    'top_department': '🏛️ Top Department',
    'top_department_qty': '📦 Top Department Qty',
    'mom_pct_change': '📈 MoM Growth %',
    'mom_change_qty': '📦 MoM Change (Qty)',
}
# For these fields, a HIGHER number is the "winner" (gets 🥇 highlighted)
HIGHER_IS_BETTER_FIELDS = {
    'sale_qty', 'pct_within_bd_segment', 'pct_of_market', 'shops_selling',
    'total_sale_qty', 'overall_market_share_pct', 'number_of_brands',
    'number_of_bd_segments', 'shops_covered', 'avg_sale_per_shop', 'mom_pct_change',
}
# For these fields, a LOWER number is the "winner" (rank #1 beats rank #26)
LOWER_IS_BETTER_FIELDS = {'overall_rank'}


def _build_comparison_row(field: str, chunk: list) -> str:
    """Builds one table row, auto-highlighting whichever entity 'wins' that
    field (bold + 🥇) -- purely numeric comparison in Python, no LLM
    judgment involved, so the highlight is always factually correct."""
    label = FIELD_DISPLAY_LABELS.get(field, "📌 " + field.replace("_", " ").title())
    values = [item.get(field, "") for item in chunk]

    best_idx = None
    if field in HIGHER_IS_BETTER_FIELDS or field in LOWER_IS_BETTER_FIELDS:
        numeric_values = []
        for v in values:
            try:
                numeric_values.append(float(v))
            except (ValueError, TypeError):
                numeric_values.append(None)
        if all(v is not None for v in numeric_values) and len(set(numeric_values)) > 1:
            target = max(numeric_values) if field in HIGHER_IS_BETTER_FIELDS else min(numeric_values)
            best_idx = numeric_values.index(target)

    cells = [f"**{v} 🥇**" if idx == best_idx else str(v) for idx, v in enumerate(values)]
    return f"| {label} | " + " | ".join(cells) + " |"


def _build_comparison_block(chunk: list, entity_key: str, fields: list, table_num: int, total_tables: int) -> str:
    icon_and_label = {"brand": "🥃 Brand", "company": "🏢 Company"}.get(entity_key, "📋 Item")
    title = f"### {icon_and_label} Comparison"
    if total_tables > 1:
        title += f" — Table {table_num}/{total_tables}"
    header = "| 🏷️ Field | " + " | ".join(f"**{r.get(entity_key, '')}**" for r in chunk) + " |"
    sep = "| --- | " + " | ".join("---" for _ in chunk) + " |"
    rows = [_build_comparison_row(f, chunk) for f in fields]
    return "\n".join([title, "", header, sep] + rows)


def render_anchor_comparison_table(records: list, entity_key: str, others_per_table: int = 2) -> str:
    """Keeps records[0] (the FIRST brand the user mentioned -- the anchor)
    fixed in every table, and chunks the remaining records into groups of
    `others_per_table`, each paired with the anchor to form one table.
    E.g. comparing 'Royal Ace' against 6 other brands produces 3 tables,
    each showing Royal Ace + 2 others (3 columns per table, readable on
    screen), rather than one giant table or sequential unrelated chunks."""
    if not records:
        return "_Koi data nahi mila is comparison ke liye._"
    if len(records) == 1:
        return render_comparison_table(records, entity_key, max_per_table=3)

    anchor = records[0]
    others = records[1:]
    fields = [k for k in anchor.keys() if k != entity_key]
    chunks = [[anchor] + others[i:i + others_per_table] for i in range(0, len(others), others_per_table)]

    blocks = [
        _build_comparison_block(chunk, entity_key, fields, idx + 1, len(chunks))
        for idx, chunk in enumerate(chunks)
    ]
    return "\n\n".join(blocks)


def render_comparison_table(records: list, entity_key: str, max_per_table: int = 3) -> str:
    """Renders a brand/company/etc comparison in 'Field as rows, Entity as
    columns' format (a vertical side-by-side profile). When comparing more
    than `max_per_table` entities, splits into multiple separate tables of
    `max_per_table` columns each (a fresh table every 3)."""
    if not records:
        return "_Koi data nahi mila is comparison ke liye._"

    fields = [k for k in records[0].keys() if k != entity_key]
    chunks = [records[i:i + max_per_table] for i in range(0, len(records), max_per_table)]

    blocks = [
        _build_comparison_block(chunk, entity_key, fields, idx + 1, len(chunks))
        for idx, chunk in enumerate(chunks)
    ]
    return "\n\n".join(blocks)

    return "\n\n".join(tables)


def dicts_to_markdown_table(records: list) -> str:
    """Builds a markdown table directly from a list of dicts -- pure Python
    string formatting, zero LLM involvement. This is the ONLY place table
    numbers get written out, guaranteeing they exactly match what's in the
    data (an LLM asked to transcribe a table can occasionally slip a digit,
    which is unacceptable for a business analytics tool)."""
    if not records:
        return "_Koi data nahi mila is query ke liye._"
    columns = list(records[0].keys())
    header = "| " + " | ".join(str(c).replace("_", " ").title() for c in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    rows = []
    for r in records:
        rows.append("| " + " | ".join(str(r.get(c, "")) for c in columns) + " |")
    return "\n".join([header, sep] + rows)


def render_data_deterministically(data) -> str:
    """Converts whatever run_query/run_special_intent returned (string,
    list of records, or a result dict) into final display text -- entirely
    in Python. No LLM ever re-types a number here."""
    if isinstance(data, str):
        return data

    if isinstance(data, list):
        return dicts_to_markdown_table(data)

    if isinstance(data, dict):
        if data.get("found") is False:
            lines = [f"❌ {data.get('message', 'Data nahi mila.')}"]
            for key in ("similar_brands", "similar_companies"):
                if data.get(key):
                    lines.append("Kya aapka matlab in mein se tha: " + ", ".join(data[key]))
            return "\n".join(lines)

        sections = []
        for key, value in data.items():
            if key == "found":
                continue
            label = key.replace("_", " ").title()
            if isinstance(value, list) and value and isinstance(value[0], dict):
                sections.append(f"**{label}:**\n\n{dicts_to_markdown_table(value)}")
            elif isinstance(value, list):
                sections.append(f"**{label}:** {', '.join(str(v) for v in value)}")
            else:
                sections.append(f"**{label}:** {value}")
        return "\n\n".join(sections)

    return str(data)


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


MONTH_NAME_TO_ABBR = {
    'january': 'jan', 'february': 'feb', 'march': 'mar', 'april': 'apr',
    'may': 'may', 'june': 'jun', 'july': 'jul', 'august': 'aug',
    'september': 'sep', 'october': 'oct', 'november': 'nov', 'december': 'dec',
}

RELATIVE_MONTH_CURRENT = {
    'current month', 'this month', 'is mahine', 'is mahina', 'isse mahina',
    'latest month', 'current', 'abhi ka mahina',
}
RELATIVE_MONTH_PREVIOUS = {
    'previous month', 'last month', 'past month', 'pichla mahina',
    'pichle mahine', 'purana mahina', 'gaya mahina',
}


def resolve_month_reference(value: str) -> str:
    """Handles month references the plain fuzzy_resolve_value can't:
    1. Relative terms ("current month", "last month", "pichla mahina") --
       resolved to the actual chronologically latest/previous month label.
    2. Bare month names without a year ("April") -- fuzzy_resolve_value's
       difflib similarity check was too strict for "April" vs "Apr-26"
       (below the 0.6 cutoff due to length difference), so we normalize
       full month names to their 3-letter form first ("April" -> "Apr"),
       which then matches via plain substring containment.
    """
    v = value.strip().lower()

    if v in RELATIVE_MONTH_CURRENT:
        _, _, cur_label, _ = get_current_and_previous_month_df()
        return cur_label or value
    if v in RELATIVE_MONTH_PREVIOUS:
        _, _, _, prev_label = get_current_and_previous_month_df()
        return prev_label or value

    for full_name, abbr in MONTH_NAME_TO_ABBR.items():
        if v == full_name or v.startswith(full_name + ' '):
            return value.lower().replace(full_name, abbr)

    return value


def run_query(spec: dict):
    filtered = df

    # Apply filters -- each value is first fuzzy-resolved to the closest
    # REAL value in that column (exact -> substring -> typo-tolerant match),
    # then applied as a filter. This means every dimension (department,
    # company, liquor_type, etc.) tolerates partial names and small spelling
    # differences, not just brand/bd_segment.
    for dim, value in (spec.get("filters") or {}).items():
        col = DIMENSIONS.get(dim)
        if col and col in filtered.columns:
            if dim == "month":
                value = resolve_month_reference(str(value))
            resolved_value = fuzzy_resolve_value(str(value), col)
            filtered = filtered[filtered[col].astype(str).str.contains(str(resolved_value), case=False, na=False)]

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
                resolved_value = fuzzy_resolve_value(str(value), col)
                subset = subset[subset[col].astype(str).str.contains(str(resolved_value), case=False, na=False)]

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
        return combined.reset_index().to_dict('records')

    group_by = [DIMENSIONS[d] for d in (spec.get("group_by") or []) if d in DIMENSIONS]
    top_n = spec.get("top_n") or 10
    sort_desc = spec.get("sort_desc", True)

    if not group_by:
        total = filtered[COL_QTY].sum()
        return f"Total Sale Qty (boxes): {total}"

    # If "month" is combined with another dimension (e.g. brand + month),
    # PIVOT so each month becomes its own COLUMN -- one row per brand, with
    # "Apr-26"/"May-26" side by side -- instead of repeating a row for every
    # brand-month combination (which was hard to compare/scan).
    if COL_MONTH in group_by and len(group_by) > 1:
        other_dims = [c for c in group_by if c != COL_MONTH]
        pivot = filtered.pivot_table(
            index=other_dims, columns=COL_MONTH, values=COL_QTY, aggfunc='sum', fill_value=0
        )
        pivot['Total'] = pivot.sum(axis=1)
        pivot = pivot.sort_values('Total', ascending=not sort_desc)
        pivot = pivot.head(top_n)
        pivot.columns.name = None
        return pivot.reset_index().to_dict('records')

    result = filtered.groupby(group_by)[COL_QTY].sum()
    result = result.sort_values(ascending=not sort_desc)
    result = result.head(top_n)
    result = result.rename('total_qty')
    return result.reset_index().to_dict('records')


import re
import difflib


def fuzzy_resolve_value(user_value: str, column) -> str:
    """Resolves whatever the user typed to the closest REAL value that
    actually exists in that column -- users rarely type the exact database
    string. Tries 5 levels, in order:

    1. Exact match (case-insensitive) -- user typed it correctly already.
    2. Substring match -- user typed a short/partial version ("Royal Ace"
       -> "ROYAL ACE RARE BLENDED WHISKY"). If multiple values contain the
       text, picks the one with the highest total sale_qty_in_box (most
       likely the one meant).
    3. Normalized substring match -- same as #2 but with spaces/punctuation
       stripped from BOTH sides first. Catches cases like "8PM" not
       matching "8 PM PREMIUM BLACK BLENDED WHISKY" (the real value has a
       space that plain substring matching required but the user omitted).
    4. Fuzzy similarity match (difflib) -- catches typos and word-order/
       spelling variations that aren't a clean substring, e.g. "Semi
       Premium Whisky" -> "Semi Pre Whisky". This compares overall string
       similarity rather than requiring an exact substring.

    Falls back to returning the original input untouched if nothing is
    close enough at any level -- the calling function's own "not found"
    handling takes over from there, rather than silently guessing wrong.
    """
    if df.empty or not user_value or column not in df.columns:
        return user_value

    col_series = df[column].astype(str)
    unique_values = col_series.unique()
    if len(unique_values) == 0:
        return user_value

    upper_to_actual = {}
    for v in unique_values:
        upper_to_actual.setdefault(v.upper(), v)

    # 1. Exact (case-insensitive)
    if user_value.upper() in upper_to_actual:
        return upper_to_actual[user_value.upper()]

    # 2. Substring -- prefer the highest-volume match if several contain it
    contains_mask = col_series.str.contains(user_value, case=False, na=False, regex=False)
    if contains_mask.any():
        matches = df.loc[contains_mask]
        best = matches.groupby(column)[COL_QTY].sum().sort_values(ascending=False)
        return best.index[0]

    # 3. Normalized substring -- strip spaces/punctuation from both sides
    # ("8PM" -> "8PM", "8 PM PREMIUM..." -> "8PMPREMIUM...") so minor
    # spacing/punctuation differences don't block an otherwise-clear match.
    normalized_user = re.sub(r'[^A-Z0-9]', '', user_value.upper())
    if normalized_user:
        normalized_map = {v: re.sub(r'[^A-Z0-9]', '', v) for v in unique_values}
        norm_matches = [v for v, norm_v in normalized_map.items() if normalized_user in norm_v]
        if norm_matches:
            matches = df[df[column].isin(norm_matches)]
            best = matches.groupby(column)[COL_QTY].sum().sort_values(ascending=False)
            return best.index[0]

    # 4. Prefix-based fuzzy match -- comparing a SHORT user input against a
    # much LONGER real name unfairly drags down the similarity score (pure
    # length mismatch), even for an obvious near-match. Fix: compare the
    # user's input against just the first N words of each candidate (N =
    # how many words the user typed), so a typo like "STAGY GREEN" (2
    # words) correctly matches "STAGGY GREEN BLENDED WHISKY" by comparing
    # against just its first 2 words ("STAGGY GREEN") -- ratio jumps from
    # ~0.58 (full string) to ~0.96 (prefix-only), correctly passing.
    user_word_count = len(user_value.split())
    best_prefix_match, best_prefix_ratio = None, 0.0
    for v in unique_values:
        prefix = " ".join(v.split()[:user_word_count])
        ratio = difflib.SequenceMatcher(None, user_value.upper(), prefix.upper()).ratio()
        if ratio > best_prefix_ratio:
            best_prefix_ratio, best_prefix_match = ratio, v
    if best_prefix_match and best_prefix_ratio >= 0.75:
        return best_prefix_match

    # 5. Fuzzy similarity (handles typos / reordered words / partial spelling)
    close = difflib.get_close_matches(user_value.upper(), list(upper_to_actual.keys()), n=1, cutoff=0.6)
    if close:
        return upper_to_actual[close[0]]

    # Nothing close enough -- let the caller's own not-found handling report it
    return user_value


def resolve_brand_name(partial_name: str) -> str:
    return fuzzy_resolve_value(partial_name, COL_BRAND)


def resolve_bd_segment_name(partial_name: str) -> str:
    return fuzzy_resolve_value(partial_name, COL_BD_SEGMENT)


def resolve_segment_reference(value: str) -> str:
    """Handles a common phrasing pattern: 'Royal Ace segment mein...' --
    where the user actually means 'the bd_segment that Royal Ace belongs
    to', not a literal segment named 'Royal Ace'. Tries resolving as a real
    bd_segment value first; if that doesn't match anything real, tries
    resolving as a BRAND name instead and returns THAT brand's bd_segment.
    Falls back to the original bd_segment resolution if neither works."""
    resolved_as_segment = resolve_bd_segment_name(value)
    if resolved_as_segment.upper() in df[COL_BD_SEGMENT].astype(str).str.upper().unique():
        return resolved_as_segment

    resolved_as_brand = resolve_brand_name(value)
    match = df[df[COL_BRAND].str.upper() == resolved_as_brand.upper()]
    if not match.empty:
        return match[COL_BD_SEGMENT].iloc[0]

    return resolved_as_segment


def resolve_company_name(partial_name: str) -> str:
    return fuzzy_resolve_value(partial_name, COL_COMPANY)


def run_special_intent(intent: str, params: dict):
    """Routes a parsed intent to the matching SmartQueryEngine method.
    Returns a JSON string of the result (or an error message string)."""
    engine = SmartQueryEngine(df)  # cheap wrapper around current df, rebuilt fresh each call

    # Auto-resolve partial/loosely-worded names to their exact canonical
    # database values -- every intent below requires EXACT (case-insensitive)
    # matches internally, so any mismatch here would silently produce
    # "not found" even when the data clearly exists. This is the single
    # place all name resolution happens, so every intent benefits at once.
    if "brand_name" in params:
        params["brand_name"] = resolve_brand_name(params["brand_name"])
    if "primary_brand" in params:
        params["primary_brand"] = resolve_brand_name(params["primary_brand"])
    if "secondary_brand" in params:
        params["secondary_brand"] = resolve_brand_name(params["secondary_brand"])
    if "brands" in params and isinstance(params["brands"], list):
        params["brands"] = [resolve_brand_name(b) for b in params["brands"]]
    if "bd_segment" in params:
        params["bd_segment"] = resolve_bd_segment_name(params["bd_segment"])
    if "company_name" in params:
        params["company_name"] = resolve_company_name(params["company_name"])
    if "companies" in params and isinstance(params["companies"], list):
        params["companies"] = [resolve_company_name(c) for c in params["companies"]]

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
            engine_result = engine.compare_brands(params["brands"])
            if not engine_result.get("found") and "details" not in engine_result:
                result = engine_result
            else:
                # Determine the full field set from any found brand, so
                # not-found brands can show "Not Found" in EVERY column
                # (not blank cells).
                field_names = []
                for detail in engine_result["details"].values():
                    if detail.get("found"):
                        field_names = [k for k in detail.keys() if k != "found"]
                        break

                complete_table = []
                for brand_input in params["brands"]:
                    detail = engine_result["details"].get(brand_input, {})
                    if not detail.get("found"):
                        row = {"brand": brand_input}
                        for f in field_names:
                            row[f] = "❌ Not Found"
                        complete_table.append(row)
                        continue
                    row = {"brand": brand_input}
                    for k, v in detail.items():
                        if k == "found":
                            continue
                        row[k] = ", ".join(str(x) for x in v) if isinstance(v, list) else v
                    complete_table.append(row)

                # Order is preserved (NOT sorted by sale_qty) -- the FIRST
                # brand the user mentioned is the "anchor" and stays fixed
                # across every table; the rest are chunked 2-per-table
                # alongside it.
                # early return: already-formatted comparison table,
                # bypassing the generic dict renderer entirely.
                return render_anchor_comparison_table(complete_table, entity_key="brand")

        elif intent == "compare_companies":
            resolved_companies = [resolve_company_name(c) for c in params["companies"]]
            engine_result = engine.compare_companies(resolved_companies)
            if not engine_result.get("found") and "details" not in engine_result:
                result = engine_result
            else:
                field_names = []
                for detail in engine_result["details"].values():
                    if detail.get("found"):
                        field_names = [k for k in detail.keys() if k != "found"]
                        break

                complete_table = []
                for company_input in resolved_companies:
                    detail = engine_result["details"].get(company_input, {})
                    if not detail.get("found"):
                        row = {"company": company_input}
                        for f in field_names:
                            row[f] = "❌ Not Found"
                        complete_table.append(row)
                        continue
                    row = {"company": company_input}
                    for k, v in detail.items():
                        if k == "found":
                            continue
                        row[k] = v
                    complete_table.append(row)

                # Same pattern as compare_brands: FIRST company mentioned
                # is the anchor, fixed across every table; rest chunked
                # 2-per-table alongside it.
                return render_anchor_comparison_table(complete_table, entity_key="company")

        elif intent == "cross_reference_shops":
            result = engine.cross_reference_shops(
                params["primary_brand"], params["secondary_brand"], top_n=params.get("top_n", 10)
            )

        elif intent == "mom_gainers_losers":
            df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
            if df_current is None:
                return "MoM comparison ke liye kam se kam 2 mahino ka data chahiye. Abhi sirf 1 mahina loaded hai."

            bd_seg_filter = params.get("bd_segment_filter")
            if bd_seg_filter:
                bd_seg_filter = resolve_segment_reference(bd_seg_filter)
                df_current = df_current[df_current[COL_BD_SEGMENT].str.upper() == bd_seg_filter.upper()]
                df_previous = df_previous[df_previous[COL_BD_SEGMENT].str.upper() == bd_seg_filter.upper()]

            full_result = SmartQueryEngine.mom_gainers_losers(
                df_current, df_previous,
                group_col=params.get("group_col", "bd_segment"),
                min_base=params.get("min_base", 500),
                top_n=params.get("top_n", 10),
            )

            # Only include the sections the user actually asked for -- e.g.
            # if they asked "top losers", don't also dump gainers/new_entries/
            # dropped_brands into the reply (that was the "poocha kuch,
            # output kuch" bug).
            section_key_map = {
                "gainers": "top_gainers",
                "losers": "top_losers",
                "new_entries": "new_entries",
                "dropped": "dropped_brands",
            }
            requested_sections = params.get("sections") or list(section_key_map.keys())
            result = {
                "current_month": cur_label,
                "previous_month": prev_label,
                "group_col": full_result["group_col"],
                "min_base_used": full_result["min_base_used"],
            }
            if bd_seg_filter:
                result["bd_segment_filter_applied"] = bd_seg_filter
            for section in requested_sections:
                json_key = section_key_map.get(section)
                if json_key:
                    result[json_key] = full_result[json_key]

        elif intent == "brand_ranking":
            result = engine.brand_ranking(params["brand_name"])

        elif intent == "brands_in_bd_segment":
            result = engine.brands_in_bd_segment(params["brand_name"], top_n=params.get("top_n", 15))

        elif intent == "company_report":
            company_name = params.get("company_name")
            if not company_name and params.get("brand_name"):
                # User gave a brand -- find which company makes it, then
                # report on the WHOLE company (all its brands combined),
                # not just the one brand that was named.
                resolved_brand = resolve_brand_name(params["brand_name"])
                match = df[df[COL_BRAND].str.upper() == resolved_brand.upper()]
                if not match.empty:
                    company_name = match[COL_COMPANY].iloc[0]
            if not company_name:
                return "Company ya brand ka naam nahi mila is query ke liye."
            company_name = resolve_company_name(company_name)

            result = engine.company_full_profile(company_name)
            if result.get("found"):
                # Add metric 9 (Month-over-Month growth %) if 2+ months are loaded
                df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
                if df_current is not None:
                    mom = SmartQueryEngine.company_mom_check(company_name, df_current, df_previous)
                    if mom.get("found"):
                        result["mom_current_month"] = cur_label
                        result["mom_previous_month"] = prev_label
                        result["mom_pct_change"] = mom["pct_change"]
                        result["mom_change_qty"] = mom["change_qty"]

        elif intent == "brand_mom_check":
            df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
            if df_current is None:
                return "MoM comparison ke liye kam se kam 2 mahino ka data chahiye. Abhi sirf 1 mahina loaded hai."
            result = SmartQueryEngine.brand_mom_check(params["brand_name"], df_current, df_previous)
            result["current_month"] = cur_label
            result["previous_month"] = prev_label

        else:
            return f"Unknown intent: {intent}"

        return result

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
    except Exception as e:
        print(f"Query parse failed: {e}")
        return {"reply": ("🤔 Sawaal samajh nahi paya. Try karo: 'Top TSE April mein', "
                           "'DCCWS department ka top brand', 'May vs April total', 'Dennis ka rank kya hai', etc.")}

    # Self-reported confidence check -- if Claude itself isn't sure what was
    # asked, we stop right here instead of guessing an intent/filter and
    # confidently returning a "correct-looking" answer to the WRONG question.
    if not spec.get("query_understood", True):
        clarification = spec.get("clarification_needed") or "Sawaal thoda aur specific kar sakte ho?"
        return {"reply": f"🤔 Mujhe yeh sawaal 100% clear nahi hai. {clarification}"}

    try:
        intent = spec.get("intent", "generic")
        if intent == "generic":
            data = run_query(spec)
        else:
            data = run_special_intent(intent, spec.get("params") or {})
    except Exception as e:
        print(f"Query run failed: {e}")
        data = ("Sawaal samajh nahi aaya. Try karo: 'Top TSE April mein', "
                "'DCCWS department ka top brand', 'May vs April total', 'Dennis ka rank kya hai', etc.")

    # CRITICAL: the table/numbers are built here, in pure Python, from the
    # actual data -- never by asking an LLM to "re-type" or "format" them.
    # An LLM transcribing a table can occasionally alter a digit, which is
    # unacceptable for a business analytics tool (verified this happened:
    # a live query showed 27,837/21,121 when the real Supabase numbers were
    # 31,536/20,081 -- the calculation was correct, but the presentation
    # layer had silently changed the numbers while "formatting" them).
    deterministic_text = render_data_deterministically(data)

    # Claude's ONLY job now is a short 1-2 line insight/comment -- it is
    # explicitly told not to repeat any numbers, since those are already
    # rendered exactly, above.
    try:
        insight_response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=150,
            system=(
                "Tu ek chhota insight-generator hai RSD liquor sales data ke liye. Tumhe neeche "
                "diya gaya data ek observation ke liye dikhaya ja raha hai -- ISE DOBARA MAT LIKHO, "
                "koi table ya number repeat mat karo (woh already user ko dikh chuka hai). Sirf EK "
                "CHHOTA 1-2 line ka Hinglish insight/comment do jo is data se related ho (jaise "
                "'yeh brand apne segment ka leader hai' ya 'yeh decline chinta ka vishay hai'). "
                "Emoji use karo. Agar data mein 'not found' / error ho, kuch mat likho, khaali "
                "string return karo."
            ),
            messages=[{
                "role": "user",
                "content": f"Sawaal: {request.message}\n\nData (sirf reference ke liye, dobara mat likhna):\n{deterministic_text[:2000]}"
            }],
        )
        insight = insight_response.content[0].text.strip()
    except Exception as e:
        print(f"Insight generation failed (non-critical): {e}")
        insight = ""

    final_reply = deterministic_text if not insight else f"{deterministic_text}\n\n{insight}"
    return {"reply": final_reply}
