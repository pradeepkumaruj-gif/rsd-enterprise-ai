from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import os
import threading
import time
from collections import defaultdict, deque
import pandas as pd
from supabase import create_client
from smart_query_engine import SmartQueryEngine

app = FastAPI()

# Restrict CORS to ONLY the actual RSD frontend -- previously "*" meant ANY
# website on the internet could call this backend directly (and use up
# Anthropic API credits, pull sales data, etc.). If you ever add a new
# frontend URL (e.g. a custom domain, or local dev), add it to this list.
ALLOWED_FRONTEND_ORIGINS = [
    "https://grateful-mercy-production-dd3c.up.railway.app",
    "http://localhost:5173",   # local Vite dev server
    "http://localhost:3000",   # common local dev port, just in case
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
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
    history: list = []  # optional: [{"role": "user"|"assistant", "content": "..."}, ...]
                         # last 2-3 exchanges from the frontend, used so follow-up
                         # questions ("April ki bhi batao") can inherit context
                         # (brand/company/dimension) from the previous question
                         # instead of needing everything repeated every time.


# Simple in-memory rate limiter (no external library needed) -- protects
# against abuse/spam (which burns Anthropic API credits and Supabase
# bandwidth). Tracks request TIMESTAMPS per client IP in a rolling window.
# NOTE: this resets on server restart and doesn't share state across
# multiple server instances -- fine for a single-instance deployment
# (Railway shows "1 Replica"), but would need a shared store (e.g. Redis)
# if ever scaled to multiple instances.
RATE_LIMIT_MAX_REQUESTS = 20   # max requests...
RATE_LIMIT_WINDOW_SECONDS = 60  # ...per this many seconds, per IP
_rate_limit_tracker = defaultdict(deque)


def _is_rate_limited(client_ip: str) -> bool:
    now = time.time()
    timestamps = _rate_limit_tracker[client_ip]
    while timestamps and now - timestamps[0] > RATE_LIMIT_WINDOW_SECONDS:
        timestamps.popleft()
    if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        return True
    timestamps.append(now)
    return False


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
  "is_multi_step": false,
  "sub_queries": [],
  "intent": "generic",
  "metric": "sum",
  "group_by": ["dimension1", "dimension2"],
  "filters": {{"dimension": "value to match", "dimension2": "value2"}},
  "share_filter": {{}},
  "value_range": null,
  "top_n": 10,
  "sort_desc": true,
  "count_dimension": null,
  "month_filter": null,
  "params": {{}}
}}

⚠️ MULTI-STEP QUERIES -- agar user EK saath MULTIPLE INDEPENDENT questions poochta hai (jaise
"Dennis ki May sale AUR Royal Ace ki May sale dono batao", "X ka total kya hai aur Y ka kitna
hai", "Dennis aur Royal Ace dono ka April profile do"), set karo:
  "is_multi_step": true,
  "sub_queries": ["Dennis ki May sale kya hai", "Royal Ace ki May sale kya hai"]
Har ek sub_query APNE AAP MEIN COMPLETE aur INDEPENDENT honi chahiye (poora question, jaise ek
alag user ne alag se poocha ho) -- taaki har ek ko ALAG SE, poori tarah parse kiya ja sake. Jab
"is_multi_step": true ho, baaki fields (intent, filters, etc.) ignore ho jayenge -- sirf
"sub_queries" use hoga.
Agar sawaal SIRF EK cheez poochta hai (chahe woh complex/detailed cheez ho -- jaise ek brand ka
poora profile ya ek segment ka pivot report), "is_multi_step": false hi rakho aur normal
single-intent JSON do -- MULTI-STEP SIRF tab hai jab genuinely 2+ ALAG, INDEPENDENT sawaal ek
saath poochein gaye hon (usually "aur"/"and" se joined, ya comma se list kiye gaye multiple
distinct entities/questions).
Zyada se zyada 5 sub_queries allowed hain -- agar user isse zyada poochein, sirf pehle 5 lo.

"month_filter" -- UNIVERSAL field jo KISI BHI intent (generic ya specialized) ke saath kaam
karta hai -- kisi bhi specialized function (brand_report, segment_top_brands_with_shop_and_compare,
compare_brands, dimension_breakdown_report, etc.) ko ek SPECIFIC month ya month-RANGE tak scope
karta hai (default sabhi loaded months combined use karte hain agar yeh na diya jaye).
Format: {{"start": "Apr-26", "end": "May-26"}} -- agar sirf EK month chahiye, "end" ko "start"
jaisa hi rakho (ya omit kar do, automatically same maan liya jayega).
Trigger: "April mein Dennis ka poora profile do" (-> month_filter: {{"start":"Apr-26","end":"Apr-26"}}),
"April se May tak Semi Pre Whisky ke top brands" (-> month_filter: {{"start":"Apr-26","end":"May-26"}}),
"is mahine ke liye compare karo" (-> current month use karo)
NOTE: MoM/growth-type intents (mom_gainers_losers, brand_mom_check, dimension_mom_check,
brand_growth_breakdown, compound_ranking) is field ko IGNORE karte hain -- unka apna month-pair
logic already hai (current vs previous automatically), unke saath month_filter mat bhejo.
"query_understood" aur "clarification_needed" SABSE ZAROORI FIELDS HAIN -- inhe seriously lo:
- "query_understood": true -- SIRF tab jab tumhe 100% confidence ho ki user kya poochh raha hai,
  aur available dimensions/intents mein se sahi mapping ban sakti hai.
- "query_understood": false -- agar sawaal ambiguous hai, incomplete hai, contradictory hai, ya
  kisi aisi cheez ke baare mein hai jo available dimensions/intents mein fit nahi hoti, ya agar
  do alag tarike se interpret ho sakta hai aur dono equally likely lagte hain. GUESS MAT KARO --
  agar doubt hai, false maro aur "clarification_needed" mein SPECIFIC bata do ki kya unclear tha
  aur user kya clarify kare (Hinglish mein, 1 line).
  SMART CLARIFICATION -- agar sawaal ka structure BILKUL naya/anjaana hai (jaise koi aisa
  concept jo humare kisi bhi intent se match nahi karta -- "graph flat line", "trend line
  dikhao" jaisa kuch), sirf "samajh nahi aaya" mat bolo -- agar tumhe koi PARTIAL guess ban raha
  hai (jaise "shayad growth/decline poochh rahe ho, ya kisi specific number ke baare mein"),
  woh guess bhi "clarification_needed" mein include karo taaki user sirf haan/nahi bol sake,
  poora sawaal dobara na likhna pade. Jaise: "Yeh 'flat line' se aapka matlab hai ki sale same
  reh gayi (na growth na decline)? Agar haan, brand/period bata do."
- Jab "query_understood": false ho, baaki saare fields (intent, filters, etc.) ignore kar diye
  jayenge -- unko kuch bhi default value de sakte ho, unka use nahi hoga.
- Yeh galat guess se BEHTAR hai ki tum clearly bol do "clear nahi hai" -- ek galat-samjha sawaal
  ka "sahi" number dena, galat sawaal poochne se zyada nuksaandeh hai.

⚠️ CRITICAL -- ENTITY NAMES (brand/company/shop/TSE) KO VERIFY MAT KARO:
Tumhare paas brands ki POORI list NAHI hai (300+ brands hain, sab list mein nahi diye ja sakte --
sirf bd_segment jaisi chhoti lists di gayi hain). Isliye jab user koi brand/company/shop/TSE ka
naam bole jo tumhe "unfamiliar" ya "ajeeb" lage (jaise "White and Blue", "Stagy Green", chhote/
partial naam) -- ISE TURANT VALID BRAND/ENTITY NAME MAAN LO aur "query_understood": true rakho,
filters/params mein daal do jaisa bola gaya. TUMHARA KAAM YEH VERIFY KARNA NAHI HAI KI YEH REAL
HAI YA NAHI -- woh kaam downstream Python fuzzy-matching system karta hai (jo asli data dekh
kar verify/resolve karta hai). Agar naam galat nikla, system khud "not found" bol dega baad mein.
"query_understood": false SIRF tab karo jab SAWAAL KA STRUCTURE/INTENT unclear ho (jaise "vendor"
ka do matlab, ya kaunsa intent/metric chahiye pata na chale) -- kisi entity NAME ke unfamiliar
lagne ki wajah se KABHI false mat karo, yeh galat use hai is field ka.

"intent" batata hai kaunsa engine chalana hai. Available intents:

1. "generic" (default) -- flexible filter/group_by/metric queries jaisa upar diya hai. Ismein
   "metric" "sum" / "count_distinct" / "market_share" ho sakta hai (neeche detail hai).

2. "brand_report" -- ek specific brand ka poora profile: total market share %, bd_segment
   market share %, department-wise sale breakdown (with per-department market share), top
   shops -- SAB EK SAATH. Yeh intent use karo jab bhi user brand ke baare mein multiple
   metrics ek saath poochta hai (jaise "market share" + "department wise" dono ek sawaal mein).
   params: {{"brand_name": "..."}}
   IMPORTANT: agar sawaal mein "department wise sale" ke SAATH "market share" ya "segment
   share" bhi poocha gaya ho, YEH intent use karo (generic MAT karo) -- generic sirf plain
   sum dega, market share % nahi dega. brand_report in dono ko ek saath deta hai.
   Trigger: "Dennis ka poora report do", "DENNIS SPECIAL GOLD WHISKY ke baare mein batao",
   "Dennis ki department wise sale with total market share and segment market share" (-> yeh
   brand_report hai, generic NAHI -- kyunki market share bhi chahiye)

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

6. "brand_share_filter" -- KISI BHI dimension (BD Segment, Company, Department, TSE) ke andar
   leading (>=threshold%) ya long-tail (<threshold%) brands.
   params: {{"category_value": "...", "threshold": 5.0, "mode": "above" or "below",
   "category_type": "bd_segment"}}
   "category_type" ho sakta hai: "bd_segment" (default), "company", "department", ya "tse".
   Trigger: "Semi Pre Whisky mein 5% se zyada share wale brands" (-> category_type: "bd_segment"),
   "kaunse brands 5% se kam hain", "OMSONS company mein 5% se zyada share wale brands" (->
   category_type: "company"), "DCCWS department mein leading brands" (-> category_type: "department")

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

12. "brands_in_bd_segment" -- ek brand ke bd_segment (category) YA COMPANY ke andar BAAKI SAB
    brands ki ranked list (kaun kaun se aur brands isi category/company mein bikte hain, kitna
    sale hai). NOTE: yeh SIRF "bd_segment" aur "company" ke liye kaam karta hai -- department/
    tse/shop ke liye NAHI (kyunki ek brand ek department/TSE tak "belong" nahi karta, woh kai
    departments/TSEs mein bik sakta hai ek saath -- yeh concept sirf segment/company (jo brand
    ki fixed "ownership" attribute hai) ke liye sense banata hai).
    params: {{"brand_name": "...", "top_n": 15, "scope_type": "bd_segment"}}
    "scope_type" ho sakta hai "bd_segment" (default) ya "company".
    Trigger: "Royal Ace ke segment mein aur kaunse brands hain" (-> scope_type: "bd_segment"),
    "Dennis ki category mein competitors kaun hain", "iske segment mein baaki brands", "Dennis
    ki company ke aur kaunse brands hain" (-> scope_type: "company"), "Royal Ace ki company ka
    poora brand portfolio dikhao" (-> scope_type: "company")

13. "company_report" -- ek COMPANY (manufacturer) ki poori sale -- uske SAARE brands milaake,
    na ki sirf ek brand ka number. Agar user brand ka naam de ("Dennis brand ki company ka
    total sale"), "brand_name" param mein daalo -- system automatically us brand ki company
    dhoondh ke uska poora company-wide total nikalega. Agar user seedha company ka naam de,
    "company_name" param use karo.
    params: {{"company_name": null, "brand_name": null, "top_brands": 10}}
    ⚠️ DEFAULT BEHAVIOR -- agar user SIRF "[Company Name] ki sale" jaisa bole (bina yeh bataye ki
    total chahiye, brand-wise chahiye, ya kisi dimension-wise breakdown chahiye), CLARIFICATION
    MAT MAANGO -- seedha "company_report" use karo (company ka POORA overview -- total sale,
    market share, brands, top department, waghera -- ek saath milta hai isse, jo generic "ki
    sale" ka sabse sensible default hai).
    Trigger: "Dennis brand ki company ki total sale kya hai", "OMSONS company ka total business
    kitna hai", "[brand] banane wali company ka overall sale", "Rock and Storm ki sale batao"
    (-> seedha company_report, company_name: "Rock and Storm" -- clarification NAHI maango)

14. "compare_companies" -- 2 se 10 companies (manufacturers) side-by-side compare karo
    (market share, rank, brands count, top brand, shops, MoM growth, etc.).
    params: {{"companies": ["company1", "company2", ...]}}
    IMPORTANT: "companies" list ka ORDER wahi rakho jis order mein user ne bola -- PEHLI company
    jo user bole use ANCHOR maana jayega (agar 3+ companies hain, yeh anchor har comparison table
    mein fixed rehta hai, baaki companies 2-2 karke uske saath chunk hote hain) -- bilkul
    compare_brands jaisa pattern.
    Trigger: "in companies ka comparison karo: X, Y, Z...", "Rock and Storm vs OMSONS vs ADS
    compare karo"

15. "brand_growth_breakdown" -- kisi brand ki month-over-month growth/decline KAHAN SE aayi
    (kaunsa department, shop, ya TSE sabse zyada contribute kar raha hai). NOTE: yeh sirf DATA
    breakdown deta hai (department/shop/TSE), business "reason" (marketing, pricing, competitor)
    NAHI de sakta -- woh data ismein hai hi nahi.
    params: {{"brand_name": "...", "breakdown_by": "department", "top_n": 10, "filters": {{}}}}
    "breakdown_by" ek hi ho sakta hai: "department", "shop_code", ya "tse"
    "filters" OPTIONAL hai -- jab user pehle ek dimension tak SCOPE karna chahta hai, phir uske
    andar doosre dimension se breakdown chahta hai (jaise "DSIIDC ki top shops jaha push aaya" =
    department=DSIIDC tak scope karo, phir shop_code se breakdown do). filters mein woh scoping
    dimension+value daalo (generic dimensions list se), aur breakdown_by mein jis dimension ka
    ranking chahiye woh daalo -- yeh dono ALAG hain, ek doosre ko replace nahi karte.
    Trigger: "Royal Black ki growth kahan se aayi department wise" (-> breakdown_by: "department"),
    "kis shop se sabse zyada growth aayi Dennis ki" (-> breakdown_by: "shop_code"), "Royal Black
    DSIIDC ki top 20 shops jaha strong push aaya" (-> breakdown_by: "shop_code", filters:
    {{"department": "DSIIDC"}})

16. "dimension_mom_check" -- GENERIC month-over-month growth check for ANY dimension value --
    department, shop, ya TSE ka OVERALL growth (saare brands milaake), na ki koi specific brand.
    Yeh brand_mom_check se ALAG hai -- brand_mom_check ek brand ke liye hai, yeh koi bhi
    department/shop/TSE ke liye hai.
    params: {{"dimension": "department", "value": "DCCWS"}}
    "dimension" ek hi ho sakta hai: "department", "shop_code", "party" (shop name), ya "tse"
    "value" us dimension ki specific value hai (jaise "DCCWS", ya TSE ka naam, ya shop naam)
    Trigger: "DCCWS department ka growth kitna hai", "DCCWS ka month over month kaisa raha"
    (-> dimension: "department", value: "DCCWS" -- NO brand filter, overall department growth),
    "TSE Raj Kumar ka growth kya hai", "is shop ka growth batao"

17. "compare_dimension_values" -- 2 se 10 DEPARTMENTS, SHOPS, TSEs, BD SEGMENTS, LIQUOR TYPES,
    ya PACK SIZES (SAME dimension) ko side-by-side compare karo (bilkul compare_brands jaisa
    pattern) -- total sale, rank, brands count, top brand, market share.
    params: {{"dimension": "department", "values": ["DCCWS", "DSIIDC", ...], "scope_filters": {{}}}}
    "dimension" ho sakta hai: "department", "shop_code", "party" (shop name), "tse", "bd_segment",
    "liquor_type", ya "pack_size" -- (brand aur company ke liye "compare_brands"/"compare_companies"
    use karo, yeh unke liye zyada detailed hai).
    "scope_filters" OPTIONAL hai -- ⚠️ BAHUT ZAROORI: agar user comparison ko KISI SPECIFIC
    company/brand/segment ke context tak SEEMIT karna chahta hai (jaise "Rock and Storm ke
    brands ke hisaab se Sunil Sharma vs Ram Gopal"), yahan wahi filter daalo (jaise {{"company":
    "Rock and Storm"}}) -- warna comparison poori territory/market ka hoga (SAB companies ke
    brands milaake), na ki sirf mentioned company ke brands ka. Yeh EXTREMELY common mistake
    hai -- agar sawaal mein KOI BHI company/brand/segment ka naam TSE/shop/department ke saath
    mention ho, USE HAMESHA "scope_filters" mein daalo, ignore MAT karo.
    IMPORTANT: "values" list ka ORDER wahi rakho jis order mein user ne bola -- PEHLA value jo
    user bole use ANCHOR maana jayega (agar 3+ values hain, anchor har table mein fixed rehta
    hai, baaki 2-2 karke chunk hote hain) -- bilkul compare_brands jaisa.
    Trigger: "DCCWS vs DSIIDC compare karo", "in departments ka comparison karo: DCCWS, DSIIDC,
    DTTDC", "TSE Raj vs TSE Amit compare karo", "Semi Pre Whisky vs Regular Whisky compare karo"
    (-> dimension: "bd_segment"), "Whisky vs Vodka compare karo" (-> dimension: "liquor_type"),
    "Bottle vs Quarter compare karo" (-> dimension: "pack_size"), "Rock and Storm Distilleries,
    Sunil Sharma vs Ram Gopal" (-> dimension: "tse", values: ["Sunil Sharma", "Ram Gopal Sharma"],
    scope_filters: {{"company": "Rock and Storm Distilleries"}} -- company naam ko IGNORE mat
    karo, isko scope_filters mein zaroor daalo)

18. "brand_weak_shops_analysis" -- ek brand ke BOTTOM/WEAKEST shops YA TOP/STRONGEST shops
    dhoondo (jaha sabse kam YA sabse zyada bikta hai), phir unhi shops mein dekho konse brands
    zyada chal rahe hain (ya ek SPECIFIC competitor brand ka wahan performance).
    params: {{"brand_name": "...", "bottom_n_shops": 10, "compare_brand": null,
    "top_n_other_brands": 5, "find_bottom": true, "restrict_to_own_segment": false}}
    - "find_bottom": true -- jab user "lowest/weakest/kam bikne wale" shops pooche (default).
    - "find_bottom": false -- jab user "top/best/highest/sabse zyada bikne wale/top 10 mein
      aati hai" shops pooche -- "kis shop mein iski sale TOP 10 mein aati hai" bhi isi ka matlab
      hai (us BRAND ki apni sabse zyada bikne wali 10 shops -- na ki us shop ke top-10 brands
      mein se ek).
    - "compare_brand" OPTIONAL hai -- agar user ek specific doosra brand naam de ("Dennis ke
      weak shops mein Royal Ace ka kya haal hai"), yahan daalo -- sirf uska data un shops mein
      dikhega. Agar user generic "top brands wahan" pooche, "compare_brand" null rakho --
      har shop ke top N brands dikhenge.
    - "restrict_to_own_segment": true -- jab user "iske SEGMENT mein top brands" jaisa bole
      (jaise "Dennis ke segment mein top 5 brands"), tab top brands sirf Dennis ke APNE
      bd_segment (jaise Regular Whisky) ke andar se dhoonde jayenge, sab brands se nahi. Result
      mein har brand ka "market share % (usi shop ke usi segment ke andar)" bhi milta hai, rank
      ki jagah -- yeh zyada useful business metric hai.
    Trigger: "Dennis ke lowest 10 shops kaunse hain aur wahan top 5 brands kaunse chal rahe hain"
    (-> find_bottom: true, compare_brand: null), "Dennis ke top selling shops mein kaunse aur
    brands chal rahe hain" (-> find_bottom: false, compare_brand: null), "Dennis ke weak shops
    mein Royal Ace ki sale kya hai" (-> find_bottom: true, compare_brand: "Royal Ace"), "Dennis
    ki sale konse shop par top 10 mein aati hai aur wahi shop par Royal Ace ki sale kya hai"
    (-> brand_name: "Dennis", find_bottom: false, bottom_n_shops: 10, compare_brand: "Royal Ace"),
    "Dennis ki sabse kam sale wali 10 shops batao, waha Dennis ke SEGMENT mein top 5 selling
    brands aur un shop ka market share" (-> brand_name: "Dennis", find_bottom: true,
    bottom_n_shops: 10, top_n_other_brands: 5, restrict_to_own_segment: true)

19. "dimension_breakdown_report" -- UNIVERSAL "Excel filter" style tool: KISI BHI dimensions
    (EK YA ZYADA ek saath, jaise Excel ka multi-column AutoFilter) ko filter karo (PRIMARY
    FILTERS), phir KOI BHI DOOSRA dimension (BREAKDOWN) ka top-N ranking do -- overall market %
    + filter ke andar % dono ke saath. Yeh EK function har combination cover karta hai:
    Segment→Brand, Department→TSE, Company→Shop, Segment+Department→Brand (do filters ek saath),
    waghera -- koi bhi filters+breakdown combination chalega.
    params: {{"primary_filters": {{"bd_segment": "Premium Whisky"}}, "breakdown_dimension": "brand",
    "top_n": 5}}
    - "primary_filters" EK dict hai -- ismein EK ya ZYADA dimension:value pairs daal sakte ho
      (jaise {{"bd_segment": "Premium Whisky", "department": "DCCWS"}} agar user dono filters
      ek saath bole). Dimensions ho sakte hain: "bd_segment", "department", "company", "party"
      (shop), "tse", "liquor_type", "pack_size", "brand", "month", "category", "shop_code".
    - "breakdown_dimension" ek dimension hai jiska ranking chahiye (koi bhi upar wali list se).
    - USE THIS jab bhi sawaal ho: "[X ka filter] ka overall market share + [Y dimension] ka top N
      breakdown, unka % share ke saath" -- jaise "Premium Whisky ka market share aur is segment
      mein top 5 brands aur unka market share" (-> primary_filters: {{"bd_segment": "Premium
      Whisky"}}, breakdown_dimension: "brand"). IMPORTANT: agar filter value ek segment ka naam
      hai (bd_segment list se), use bd_segment maano, brand naam SAMAJH KE dhoondhne ki koshish
      MAT karo.
    Trigger: "Premium Whisky ka market share aur top 5 brands aur unka share" (-> primary_filters:
    {{"bd_segment": "Premium Whisky"}}, breakdown_dimension: "brand"), "DCCWS department mein top
    5 TSE ka share" (-> primary_filters: {{"department": "DCCWS"}}, breakdown_dimension: "tse"),
    "OMSONS company ke top shops market share ke saath" (-> primary_filters: {{"company":
    "OMSONS"}}, breakdown_dimension: "party"), "Premium Whisky AUR DCCWS department mein top 5
    brands" (-> primary_filters: {{"bd_segment": "Premium Whisky", "department": "DCCWS"}},
    breakdown_dimension: "brand" -- DO filters ek saath)

20. "zero_presence_analysis" -- kisi filter (company/brand/etc) ka koi bhi presence NAHI hai
    jin values mein (poore universe mein, na ki kisi doosre brand ke top shops mein) -- TRUE
    zero-sale gap analysis.
    params: {{"filter_dimension": "company", "filter_value": "Rock and Storm",
    "universe_dimension": "shop_code", "show_hero_brand_in_segment": false}}
    "filter_dimension" wahi hai jiska zero-presence check karna hai (jaise "company", "brand").
    "universe_dimension" wahi hai jiske across check karna hai (default "shop_code" -- saari
    shops mein se kaha bilkul sale nahi).
    "show_hero_brand_in_segment": true -- jab user pooche "wahan iski jagah kaun jeet raha hai/
    hero brand kaun hai (SAME segment mein)" -- sirf tab kaam karta hai jab filter_dimension
    "brand" ho aur universe_dimension "shop_code" ho. Har zero-presence shop ke liye, us brand
    ke APNE bd_segment ke andar wahan ka top-selling brand bhi dikhata hai.
    ⚠️ CRITICAL DISAMBIGUATION -- "show_hero_brand_in_segment" SIRF tab use karo jab user EXACTLY
    EK (1) hero/winner brand maange, KOI NUMBER (N) mention KIYE BINA (jaise "kaun jeet raha hai
    wahan" -- bina "top/bottom/mid N" bole). AGAR user "top N brands", "bottom N brands", "mid
    N brands", "top 3", "bottom 5", "mid performer 10" jaisa KISI BHI number ke saath brands
    maange (TOP ho, BOTTOM ho, ya MID ho -- teeno equally apply hote hain, chahe N=1 hi kyun na
    ho), TOH "zero_presence_analysis" BILKUL USE MAT KARO -- seedha "zero_sale_with_top_segment_
    brands" (intent #27) use karo. Yeh dono ALAG features hain: pehla SIRF 1 hero brand deta hai
    (koi N nahi), doosra N brands wide columns mein deta hai (TOP/BOTTOM/MID 1, 2... N). "with
    top 3 brands", "bottom 5 brands wahan", "mid performer N wahan" -- yeh SAB intent #27 ke
    trigger hain, is intent (#20) ke NAHI -- chahe phrasing mein "zero sale"/"absent" bhi ho,
    aur chahe TOP ho, BOTTOM ho, ya MID ho -- teeno ke liye yehi rule equally lagu hota hai.
    CONCEPT-LEVEL RULE (zyada zaroori hai examples se) -- yeh sirf keyword-matching nahi hai.
    Reasoning yeh karo: "kya user kisi jagah pe TOTAL/COMPLETE ABSENCE (bilkul kuch na hona,
    zero, ghum jaana, koi trace na hona) ke baare mein pooch raha hai, chahe kisi bhi language
    (Hindi/English/Urdu/slang/regional) ya kisi bhi word mein ho?" -- agar HAAN, toh yeh intent
    hai, CHAHE woh exact word neeche ke examples mein na ho. Word-list match mat karo, MEANING
    samjho -- naya/anjaana word (jaise "nadaarad", "vanish", "gum hai") bhi is concept ko refer
    kar sakta hai agar context "total absence" ka hi ho.
    PHRASING SYNONYMS (illustrative examples, EXHAUSTIVE list NAHI hai) -- "sale 0/zero hai
    kaha", "kaha nahi bikta", "absent kaha hai", "missing kaha hai", "koi presence nahi hai",
    "gayab hai kaha" (Hindi slang), "available nahi hai kaha", "penetration zero/kam hai kaha",
    "kin shops mein nahi hai", "kaha sale nahi ho rahi", "kaha bilkul nahi bikta" -- yeh SAB EK
    HI matlab rakhte hain (zero-presence), inhe alag-alag intents mein mat bhejo, sabko isi
    "zero_presence_analysis" mein bhejo.
    Trigger: "Rock and Storm ka koi bhi brand kis shop mein sale nahi hota", "Dennis kis shops
    mein bilkul absent hai", "kaunse shops mein OMSONS ka koi presence nahi hai", "Dennis brand
    ka koi bhi Whisky product kis shop codes mein sale nahi hua, aur wahan same segment mein
    kaun sa brand hero hai" (-> show_hero_brand_in_segment: true), "Dennis ki sale 0 kaha hai",
    "Dennis kaha nahi bikta", "Dennis gayab hai kin shops mein"
    ⚠️ DISTINCTION: "sabse KAM sale kaha hai" (jaise "Dennis ki sabse kam sale kaha hai") EK
    ALAG cheez hai -- yeh "generic" intent hai (sort_desc: false), jo un SHOPS ko dikhata hai
    jaha brand SABSE KAM (par phir bhi kuch) bikta hai. "zero_presence_analysis" un shops ko
    dikhata hai jaha brand BILKUL NAHI bikta (0, poori tarah absent). "Kam" aur "zero/absent/
    nahi bikta/gayab" alag matlab hain -- pehla wala "generic" mein jayega, doosra
    "zero_presence_analysis" mein.
    ⚠️ DATA NOT AVAILABLE -- yeh dataset mein NAHI hain, agar user in cheezon ke baare mein
    pooche, GUESS/MAP mat karo kisi dimension pe -- "query_understood": false karo aur SAAF
    bata do ki yeh data available nahi hai:
    - "city", "state", "district", "region" -- yeh dimensions dataset mein EXIST hi nahi karte
      (poora data sirf Delhi ka hai, ismein city/state/district/region ka breakdown nahi hai).
      Agar user "kis city/state/district mein zero hai" jaisa poochein, bolo: "Yeh data available
      nahi hai -- humare paas sirf shop/department/TSE level ka data hai, city/state ka nahi."
    - "stock", "inventory", "available/availability" (jab STOCK ke context mein bola jaye, jaise
      "stock hai par sale nahi", "kaha available hai lekin bik nahi raha", "dead stock") -- humare
      paas SIRF SALES data hai, stock/inventory data BILKUL NAHI hai. "Sale zero hai" aur "stock
      hai par sale nahi hai" DO ALAG cheezein hain -- pehla hum bata sakte hain, doosra NAHI
      (kyunki hume pata hi nahi ki shop mein stock tha ya nahi, sirf itna pata hai ki sale hui
      ya nahi). Agar user stock/availability ke baare mein poochein, bolo: "Yeh humare paas sirf
      SALES data hai, stock/inventory availability ka data nahi hai -- sirf yeh bata sakta hoon
      ki sale hui ya nahi."

21. "cross_tab_matrix" -- DO dimensions ka grid/pivot table (Excel pivot jaisa) -- ek dimension
    ROWS mein, doosra COLUMNS mein, sale qty cells mein.
    params: {{"row_dimension": "department", "col_dimension": "liquor_type", "top_rows": 10,
    "top_cols": 8}}
    Trigger: "Department vs Liquor Type ka grid dikhao", "BD Segment vs Department ka pura
    matrix", "TSE vs Month ka cross table"

22. "compound_ranking" -- brands ko DO criteria se ek saath rank karo: current VOLUME aur
    GROWTH % dono (automatically latest vs pichla mahina). Woh brands top pe aayenge jo dono
    mein achhe hain (na ki sirf volume mein ya sirf growth mein).
    params: {{"rank_col": "brand", "top_n": 10, "min_base": 100}}
    Trigger: "Top 10 by volume AND growth dono", "kaunse brands overall best hain volume aur
    growth dono ke hisaab se", "balanced performers dikhao"

23. "segment_top_brands_with_shop_and_compare" -- KISI BHI dimension (BD Segment, Company,
    Department, TSE) ke top N brands, HAR brand ki apni #1 (best-selling) shop, us shop pe us
    brand ka % share (usi scope ke andar, usi shop mein), PLUS ek SPECIFIC doosra brand ka
    status usi shop pe (uski qty + % share bhi usi scope ke andar).
    params: {{"primary_dimension": "bd_segment", "primary_value": "Semi Pre Whisky", "top_n": 20,
    "compare_brand": "8 PM PREMIUM BLACK BLENDED WHISKY"}}
    "primary_dimension" ho sakta hai: "bd_segment" (default), "company", "department", ya "tse".
    "compare_brand" OPTIONAL hai -- agar diya, har row mein us brand ka bhi data aayega usi shop
    ke liye. Agar nahi diya, sirf top brands + unki shops + % share aayega.
    Trigger: "Semi Pre Whisky segment mein top 20 brands, kaunsi shop pe, shop ka market share %,
    aur usi shop pe 8PM ki sale/status kya hai market share % ke saath" (-> primary_dimension:
    "bd_segment"), "OMSONS company mein top brands, unki top shop, aur Dennis ka wahan status"
    (-> primary_dimension: "company"), "DCCWS department mein top brands aur shop-wise detail"
    (-> primary_dimension: "department")

24. "brand_transaction_count_analysis" -- kisi brand ki EXACTLY N transactions (orders/rows) wali
    shops dhoondo -- QUANTITY (boxes) NAHI, ORDERS ki GINTI. Jaise "Royal Ace sirf EK baar gaya
    is shop mein, phir kabhi nahi" -- yeh transaction count hai, sale qty nahi.
    params: {{"brand_name": "...", "target_count": 1, "comparison": "equal",
    "show_segment_top_brands": false, "top_n_shops": 10, "top_n_brands": 5}}
    "comparison" ho sakta hai: "equal" (exactly N baar), "less_equal" (N ya usse kam baar),
    "greater_equal" (N ya usse zyada baar). Default "equal", default target_count 1.
    "show_segment_top_brands": true -- jab user un shops mein bhi brand ke APNE bd_segment ke
    top brands (naam + sale qty) chahe -- "un shops mein Royal Ace segment ke top 5 brands
    naam ke saath sale qty batao". "top_n_shops" limit karta hai kitni shops ka detail dikhega
    (kyunki matching shops 100+ ho sakti hain -- top_n_shops sirf DISPLAY ke liye hai,
    matching_shops_count mein hamesha SAARI matching shops ka total count milega).
    ⚠️ Sab numbers (target_count, top_n_shops, top_n_brands) DEFAULT values hain, FIXED nahi --
    user jo bhi number bole, wahi use karo. Default "top_n_shops" 10 hi rakho -- agar user
    "full report"/"sab shops"/"poori list" bole, "top_n_shops": 50 rakho (yeh screen-readable
    max hai). Agar matching shops 50 se zyada hain, result mein total count dikhega, aur user
    Download button se poori list Excel/CSV mein nikaal sakta hai jo bhi screen pe dikhe uska.
    Trigger: "Royal Ace kin shops mein sirf ek hi baar gaya hai, dobara kabhi nahi" (-> target_count:
    1, comparison: "equal"), "Dennis 3 se kam transactions wali shops mein" (-> target_count: 3,
    comparison: "less_equal"), "Royal Ace jin shops mein ek baar gaya, un shop per Royal Ace
    segment ke top 5 selling brands name with sale qty" (-> show_segment_top_brands: true,
    top_n_brands: 5)

25. "brand_transaction_count_pivot_view" -- SAME as brand_transaction_count_analysis (transaction
    count filter par shops dhoondna), lekin output EXCEL-PIVOT jaisa WIDE table hai: EK ROW PER
    SHOP, aur us brand ki apni qty/segment-share, PLUS top-N brands, PLUS "other" brands (jo
    top-N ke baad aate hain, lekin phir bhi shop ke segment ka kam se kam ek minimum % share
    rakhte hain) -- sab ALAG COLUMNS mein, chhota naam + qty/% ek hi cell mein.
    params: {{"brand_name": "...", "target_count": 1, "comparison": "equal", "top_n_shops": 10,
    "top_n_brands": 3, "other_n_brands": 5, "other_min_pct": 1.0, "name_maxlen": 15}}
    "other_min_pct" -- minimum % threshold (default 1.0%) jo "other" brands ko qualify karne ke
    liye chahiye (top-N ke baad wale brands mein se). Agar kam brands qualify karte hain,
    kam hi dikhenge (5 se kam bhi ho sakta hai) -- yeh normal hai.
    ⚠️ Sab numbers (top_n_shops, top_n_brands, other_n_brands, other_min_pct) DEFAULT values
    hain, FIXED nahi -- user jo bhi number bole, wahi use karo.
    ⚠️ FULL REPORT -- agar user "full report", "sab SHOPS", "poori list", "saari matching
    shops", "complete data" jaisa kuch bole (matlab woh sirf top N nahi, MATCHING SAARI shops
    chahta hai), "top_n_shops": 50 rakho (yeh screen-readable max hai -- zyada rows screen pe
    dikhana impractical hoga). Agar matching shops 50 se zyada hain, result mein total
    matching count bhi dikhega. User phir Download button se poori dikhayi gayi list
    Excel/CSV mein nikaal sakta hai review ke liye.
    ⚠️ CRITICAL DISAMBIGUATION -- "sab EK [table/row] mein" (jaise "top brands aur other brands
    SAB EK wide table mein dikhao") ka matlab hai "yeh saari COLUMNS/BRANDS ko ek hi table mein
    combine karo" -- yeh FORMAT instruction hai, "sab shops" wala trigger NAHI hai. Yahan "sab"
    ka target hai brands/columns, shops NAHI. Is case mein "top_n_shops" DEFAULT (10) hi rakho,
    50 mat karo -- sirf tab 50 karo jab user explicitly "sab SHOPS" ya "poori SHOPS ki list"
    jaisa bole (shops ke context mein "sab", na ki table-format ke context mein).
    Trigger: "Royal Ace jin shops mein ek baar gaya, un shop mein top [N] brands aur baaki other
    brands jinka shop segment share >= [X]% hai (max [M]), sab ek wide table mein dikhao" --
    [N], [X], [M] hamesha user ke exact bole hue numbers hain. "...saari matching shops ka full
    report do" (-> top_n_shops: 50)

26. "brand_transaction_count_shopwise_tables" -- SAME logic as brand_transaction_count_pivot_view
    (transaction count filter), lekin output ALAG hai: EK CHHOTA TABLE PER SHOP (na ki ek bada
    combined table). Har shop ke apne top/other brands ke ACTUAL NAAM us table ke COLUMN HEADERS
    mein hote hain (kyunki har shop ke top brands alag hote hain, isliye ek shared table mein
    real naam headers mein dalna possible nahi hai).
    params: {{"brand_name": "...", "target_count": 1, "comparison": "equal", "top_n_shops": 10,
    "top_n_brands": 3, "other_n_brands": 5, "other_min_pct": 1.0, "name_maxlen": 15}}
    ⚠️ IMPORTANT -- SAARE numbers (top_n_shops, top_n_brands, other_n_brands, other_min_pct,
    target_count) FIXED NAHI HAIN -- yeh sirf DEFAULT values hain jab user kuch na bole. Jo
    bhi number user apne sawaal mein bole (jaise "top 5", "sirf 2 baar", "0.5% se zyada",
    "20 shops dikhao"), WAHI EXACT number use karo, defaults ko IGNORE karo. Kabhi bhi khud se
    "3" ya "5" jaisa fixed number mat maan lo -- hamesha user ke bole hue exact number dhoondo.
    ⚠️ FULL REPORT -- har shop ka apna ALAG table banta hai yahan, isliye "full report"/"sab
    shops" ke liye "top_n_shops": 25 hi rakho (zyada se response bahut lamba/impractical ho
    jayega, kyunki 50 shops = 50 alag tables). Agar user genuinely bahut saari shops (jaise
    50+) ka full data chahta hai, use "brand_transaction_count_pivot_view" (intent 25) ki
    taraf guide karo -- woh EK combined table deta hai jo zyada rows ke liye better suited hai.
    USE THIS jab user "har shop ka alag table" ya "brand naam header mein" jaisa kuch bole --
    agar user sirf ek generic combined table chahe (Top 1/Top 2/Brand 1/Brand 2 jaise generic
    column names ke saath), "brand_transaction_count_pivot_view" use karo iske bajaye.
    Trigger: "Royal Ace jin shops mein sirf ek baar gaya, un shops ka shop-wise table dikhao --
    top [N] aur other brands (shop segment >=[X]%) unke actual naam ke saath, har shop ka alag
    table" -- [N] aur [X] hamesha user ke diye hue exact numbers hain, kabhi fixed nahi.

⚠️ NOTE -- INTENTS 24, 25, 26 (transaction-count wale saare) bhi UNIVERSAL "month_filter" field
ke saath kaam karte hain (upar JSON schema mein define kiya gaya hai) -- yeh koi alag cheez nahi
hai, sirf top-level "month_filter" field normally jaisa hi use karo. Agar user "April mein" ya
"sirf May ke liye" jaisa bole in intents ke saath, "month_filter" bhi zaroor bhejo.
Trigger: "April mein Royal Ace jin shops mein sirf ek baar gaya" (-> intent: 24, month_filter:
{{"start":"Apr-26","end":"Apr-26"}}), "May mein Royal Ace ka shop-wise table top 3 brands ke
saath" (-> intent: 26, month_filter: {{"start":"May-26","end":"May-26"}})

27. "zero_sale_with_top_segment_brands" -- ek brand ke zero-sale shops (jaha bilkul nahi bikta)
    dhoondo, aur HAR ek zero-sale shop ke liye, us brand ke APNE bd_segment ke andar wahan ke
    TOP N, BOTTOM N, ya MID N (middle/average performer) brands (columns ke roop mein: TOP 1,
    TOP 2... ya BOTTOM 1... ya MID 1...) dikhao -- har cell format:
    "Brand Name - Qty / Shop Segment %".
    params: {{"brand_name": "Royal Ace", "top_n": <USER KA EXACT NUMBER, NEECHE DEKHO>, "rank_mode": "top"}}
    ⚠️ CRITICAL -- "top_n" HAMESHA user ke sawaal mein jo ACTUAL number bola gaya hai (jaise "top
    3" mein "3", "bottom 7" mein "7", "mid 12" mein "12"), WAHI use karo -- EXACT wahi digit jo
    query mein likha hai, NA KI koi "typical"/"example" number. 20 SIRF tab use karo jab user ne
    SACH MEIN KOI number NAHI bola ho (jaise sirf "top brands batao" bola, "top 3"/"top 5" jaisa
    kuch specify nahi kiya) -- agar bilkul koi number nahi hai sawaal mein, TABHI default 20 lo.
    Agar sawaal mein "3" likha hai, top_n MUST be 3 -- 20 kabhi mat likho jab query mein clearly
    koi aur number diya ho. Yeh mistake pehle ho chuki hai (user ne "top 3" poocha tha, system ne
    galti se 20 de diya) -- is se bachna hai, hamesha query ko dobara padho aur EXACT number
    nikaalo pehle "top_n" set karne se pehle.
    "rank_mode" teen values le sakta hai:
    - "top" (default) -- sabse zyada bikne wale N brands us segment mein us shop pe.
    - "bottom" -- jab user "BOTTOM N", "sabse kam bikne wale", "weakest N brands" poochein.
    - "mid" -- jab user "MID performer", "average/middle N brands", "beech ke performers"
      poochein -- na sabse top, na sabse bottom, ranking ke BEECH se N brands (median ke aas-paas).
    Trigger: "Royal Ace ki sale 0 hai ya kaha nahi ho rahi, aur zero sale wali shops per same
    segment mein kaun kaun se brand sale ho rahe hain, top 20 brands batao" (-> rank_mode:
    "top"), "...bottom 20 brands batao" (-> rank_mode: "bottom"), "...mid performer 20 brands
    batao" (-> rank_mode: "mid"), "Show me shops where Dennis is absent, with top 3 brands"
    (-> rank_mode: "top", top_n: 3), "Show me shops where Dennis is absent, with bottom 5
    brands" (-> rank_mode: "bottom", top_n: 5), "Where Dennis has zero sale, show mid
    performer 10 brands there" (-> rank_mode: "mid", top_n: 10) -- teeno English mein bhi is
    intent ka hai, "zero_presence_analysis"/hero_brand mein NAHI jayega, chahe N=1 bhi ho
    ("top 1 brand" bhi is intent mein hi jayega, hero_brand feature mein nahi -- woh feature
    sirf "kaun jeet raha hai" jaisi phrasing ke liye hai jisme koi number bilkul na ho).
    Agar user sirf "zero sale" poochein (bina "top/bottom/mid N brands wahan" ke, aur koi number
    na ho), use "zero_presence_analysis" hi karo -- yeh naya intent SIRF tab jab dono cheezein
    saath poochi jayein (zero-sale shops + wahan kisi NUMBER ke saath top/bottom/mid brands).

28. "segment_month_brand_breakdown" -- KISI BHI dimension (BD Segment, Company, Department, TSE)
    ke andar brands ka PIVOT-style report -- EK ROW per (primary dimension value, Brand), aur
    HAR MONTH ka sale ek ALAG COLUMN mein (jaise "Apr-26 Sale", "May-26 Sale"), PLUS "Total"
    column (poore period ka sum) aur "Brand % of Total" (us brand ka % poore period ke total
    mein se, per-month nahi). Primary dimension har row mein dikhta hai SIRF tab jab MULTIPLE
    values cover ho rahe hon (agar ek hi value scope hai, ek baar upar summary mein dikhega, row
    mein repeat nahi hoga).
    params: {{"primary_dimension": "bd_segment", "primary_value": "Semi Pre Whisky",
    "top_n_brands": null}}
    "primary_dimension" ho sakta hai: "bd_segment" (default), "company", "department", ya "tse".
    "primary_value" OPTIONAL hai -- agar diya, sirf usi value tak scope hoga. Agar nahi diya
    (null), us dimension ke SAARE values cover honge.
    "top_n_brands" -- OPTIONAL hai. Agar user koi specific number bole (jaise "top 10 brands",
    "top 5"), wahi number daalo. Agar user KOI number NA bole (jaise sirf "brand-wise report do"
    bola, "top N" jaisa kuch nahi bola), "top_n_brands": null rakho -- iska matlab SAARE brands
    us scope ke aayenge (koi limit nahi), NA KI default 10. "10" sirf ek EXAMPLE tha, DEFAULT
    NAHI hai -- default hamesha "saare brands" (null) hai jab tak user khud koi number na bole.
    MONTH FLEXIBILITY -- kitne months COLUMNS mein aayenge, yeh "month_filter" (universal field)
    control karta hai:
    - Agar user "monthly" ya "har mahine ka" bole (bina specific bataye), "month_filter" null
      rakho -- system automatically SAARE loaded months ko alag columns mein dikha dega
      (jaise 2 months load hain to "Apr-26 Sale" aur "May-26 Sale" dono columns aayenge).
    - Agar user ek SPECIFIC month bole (jaise "sirf April 26 ka"), "month_filter": {{"start":
      "Apr-26", "end": "Apr-26"}} daalo -- tab sirf ek month column aayega.
    - Agar user RANGE bole (jaise "April se May tak"), "month_filter": {{"start": "Apr-26",
      "end": "May-26"}} daalo -- range ke saare months apne-apne column mein aayenge, aur
      "Total" us poore range ka sum hoga.
    Trigger: "BD Segment wise, brand wise, month wise (column mein) sale aur total segment % ka
    report do" (-> primary_dimension: "bd_segment", primary_value: null, month_filter: null),
    "Semi Pre Whisky ka brand-wise report, har month alag column mein, total aur % ke saath"
    (-> primary_dimension: "bd_segment", primary_value: "Semi Pre Whisky"), "OMSONS company ke
    brand list, April aur May month-wise, market share ke saath" (-> primary_dimension:
    "company", primary_value: "OMSONS"), "DCCWS department ke brands, month-wise" (->
    primary_dimension: "department", primary_value: "DCCWS"), "April se May tak Semi Pre
    Whisky ka pivot report" (-> month_filter: {{"start":"Apr-26","end":"May-26"}})

29. "anomaly_detection" -- STATISTICAL anomaly/outlier detection -- brands (ya company/tse/
    department) ka month-over-month % change nikaalta hai, phir un mein se JO PEERS (baaki
    saare items) ki tulna mein STATISTICALLY UNUSUAL hain (z-score >= threshold), unhe flag
    karta hai. Yeh "top gainers/losers" (mom_gainers_losers) SE ALAG hai -- woh sirf RANK karta
    hai (top N), yeh STATISTICALLY "abnormal" cheezein dhoondta hai (mean se kitna door hai,
    standard deviations mein) -- matlab agar SAARE brands 50% grow ho rahe hain, ek brand jo
    55% grow hua woh "anomaly" NAHI hai (normal hai is context mein), lekin ek brand jo 900%
    grow hua woh HAI (statistically bahut alag baaki sabse).
    params: {{"dimension": "brand", "z_threshold": 2.0, "min_base_qty": 50, "anomaly_type_filter": null, "explain_top_n": 3}}
    "dimension" ho sakta hai: "brand" (default), "company", "tse", ya "department".
    "z_threshold" OPTIONAL hai (default 2.0) -- kitne standard deviations door hona chahiye
    "anomaly" maane jaane ke liye. Agar user "bahut zyada strict" ya "sirf extreme cases"
    bole, 3.0 use karo. Agar "thoda zyada sensitive" bole, 1.5 use karo.
    "min_base_qty" OPTIONAL hai (default 50) -- kam volume wale items ko exclude karta hai
    (taaki chhote numbers ka noisy % change "anomaly" na dikhe).
    "anomaly_type_filter" OPTIONAL hai -- agar user SPECIFICALLY sirf "spike"/"badhe hue" ya
    sirf "drop"/"gire hue" poochein (na ki dono), yahan "spike" ya "drop" daalo -- result sirf
    usi type tak filter ho jayega (agar us type ki koi anomaly na mile, ek clear "koi X anomaly
    nahi mili" message aayega, na ki doosre type ki anomalies confusingly dikhengi). Agar user
    "koi bhi anomaly" ya "spike aur drop dono" poochein, yeh null hi rakho (dono types aayenge).
    "explain_top_n" OPTIONAL hai (default 3 -- yeh EXAMPLE/DEFAULT hai, agar user koi SPECIFIC
    number bole to HAMESHA wahi use karo, "3" ko kabhi bhi user ke actual number ke upar priority
    mat do). Yeh control karta hai ki kitni anomalies ke liye AUTOMATICALLY "kaunse department
    se yeh change aayi" wala explanation chahiye (top_contributing_department field). Agar user
    "sabke liye explanation do" ya koi specific number (jaise "top 5 ke liye batao kaha se
    aaya") bole, wahi number daalo -- max 15 tak allowed hai.
    Trigger: "koi anomaly hai kya is mahine" (-> anomaly_type_filter: null), "kaunsa brand
    achanak spike hua" (-> anomaly_type_filter: "spike"), "kaunse brands achanak DROP hue"
    (-> anomaly_type_filter: "drop"), "statistically unusual changes dikhao", "abnormal
    growth/decline kahan hai", "top 5 anomalies ke liye batao kaha se aaya" (-> explain_top_n: 5)

Agar sawaal upar ke kisi specific intent (2-29) se match nahi karta, "generic" use karo.

Available dimensions (generic intent ke liye, sirf yehi use karo): {list(DIMENSIONS.keys())}

DIMENSION NAME SYNONYMS -- user hamesha exact dimension naam nahi bolega, in synonyms ko
pehchano aur sahi dimension pe map karo:
- "party" (shop) ke liye: "shop", "dukaan", "theka" (Delhi mein liquor shop ke liye common slang),
  "retailer", "outlet", "seller", "store", "branch", "counter", "vend" (excise/liquor licensing
  term jo shop ke liye use hota hai), "L1/L2/L10" jaise license-type codes bhi shop ko refer karte hain,
  "selling point", "point of sale", "pos"
- "company" ke liye: "manufacturer", "distillery", "brand owner", "supplier", "producer", "maker",
  "firm", "parent company", "manufacturing company" -- NOTE: "corporation"/"nigam" words yahan MAT
  use karna, woh already "department" (DSIIDC/DTTDC jaise govt corporations) se mapped hain --
  dono jagah use karne se confusion hoga.
- "tse" ke liye: "salesman", "sales rep", "field rep", "agent", "salesperson", "beat officer",
  "beat person" (FMCG mein route/territory ke liye "beat" bolte hain), "dsr" (distributor sales
  rep), "order booker", "field officer", "sales executive", "sales officer"
  ⚠️ IMPORTANT -- INSAAN KE NAAM (jaise "Sunil Sharma", "Ram Gopal", "Raj Kumar") is dataset mein
  SIRF "tse" dimension mein hote hain -- brand/company/shop names insaan ke naam jaise nahi
  lagte (woh product/company/location names hote hain). Actual TSE names is dataset mein:
  Sumit, Ravinder Kumar, Malkit Singh, Ankush, Raj kumar, Sher Singh, Shammi Kapoor, Sunil
  Sharma, Ram Gopal Sharma, Lalit Kumar, Thapa. Agar user "Naam1 vs Naam2" jaisa bole (jaise
  "Sunil Sharma vs Ram Gopal"), aur woh naam PERSON-NAME jaise lagte hain (first name + surname
  pattern), TURANT "compare_dimension_values" (dimension: "tse") use karo -- CLARIFICATION MAT
  MAANGO, guess mat maano "yeh TSE hai ya kuch aur" -- is dataset mein person-names ka MATLAB
  hi TSE hai, koi ambiguity nahi hai yahan.
  ⚠️ YEH SIRF FULL NAMES KE LIYE NAHI HAI -- BARE SURNAMES bhi (jaise sirf "Sharma", "Kumar",
  "Singh", "Kapoor" akela bola jaye) TURANT "tse" dimension maano, CLARIFICATION MAT MAANGO ki
  "yeh TSE hai ya brand/company/shop". Code-level (Python) apne aap check karega ki yeh surname
  KITNE TSEs se match karta hai -- agar 1 se zyada match ho (jaise "Sharma" 2 TSEs se match
  karta hai: Sunil Sharma, Ram Gopal Sharma), Python khud specific clarification dega (exact
  konse options hain, list ke saath) -- TUMHE (parser ko) bas dimension="tse" set karke aage
  badhna hai, apni taraf se "kya yeh TSE hai" wala doubt nahi uthana. Yehi rule "Kumar" aur
  "Singh" ke liye bhi hai.
  📌 CONCRETE EXAMPLE (isi tarah handle karo, hooba-hoo) -- Query: "Sharma ki sale batao".
  GALAT response: {{"query_understood": false, "clarification_needed": "Sharma se aapka matlab
  TSE hai ya brand/company?"}} -- YEH MAT KARO.
  SAHI response: {{"query_understood": true, "intent": "generic", "params": {{"filters":
  {{"tse": "Sharma"}}, "group_by": [], "metric": "sum"}}}} -- Python khud "Sharma" 2 TSEs se
  match hone par clarification dega, tumhe abhi se doubt nahi uthana.
- "department" ke liye: "vibhaag", "nigam" (yeh values khud corporations hain: DSIIDC, DTTDC,
  DCCWS, DSCSC, HCR), "corporation", "agency", "board", "govt corporation", "psu"
- "shop_code" ke liye: "shop id", "shop number", "outlet code", "outlet id", "retailer code",
  "license number", "license code" (excise licensing format jaisa dikhta hai, e.g. "01/2024/1491"),
  "vend code", "vend number", "registration number"
  DISTINCTION: agar user sirf "shop" bole bina "code/number/ID" qualifier ke, default "party"
  (shop ka NAAM) use karo, "shop_code" nahi. Sirf "shop code/number/ID/license number" jaisa
  explicit bole tabhi "shop_code" (unique identifier) use karo.
- "liquor_type" ke liye: "drink type", "spirit type", "alcohol type"
- "bd_segment" ke liye: "price segment", "price tier", "price band", "tier", "grade", "class",
  "quality segment", "quality tier" -- IMPORTANT: bare "category" word ko bd_segment se mat map
  karo, kyunki humare paas already ek ALAG "category" dimension hai (jiski sirf ek value hai
  "IMFL", meaningfully useless hai). "category" word ko uske apne dimension pe hi rehne do,
  confusion na banao.
- "pack_size" ke liye: "bottle size", "pack", "size", "volume", "ml size", "pack type",
  "quantity size", "pauwa" (Delhi/India slang for quarter/small bottle), "adha"/"half bottle"
  (Hindi), "quarter" (colloquial for small bottle). Real values is dimension ke: "Nip, Quarter",
  "Bottle", "Half", "Pint", "Miniature 90 ml", "Miniature 60 ml", "500 ML", "Imported 275 ml",
  "Imported Bottle 1000 ml", "Imported Bottle 2000 ml"
- "brand" ke liye: "product", "sku", "label", "trademark", "mark", "item ka naam" (par "item" akela
  mat use karna pack_size ke confusion se bachne ke liye, pura phrase "item ka naam"/"brand name"
  use karo tabhi map karo)

AMBIGUOUS WORD WARNING -- "vendor" jaisa word GENUINELY ambiguous hai is business mein: kabhi
iska matlab SHOP/RETAILER hota hai (jo product bechta hai), kabhi COMPANY/MANUFACTURER hota hai
(jo product banata/supply karta hai) -- yeh dono bilkul alag dimensions hain ("party" vs
"company"). Agar user "vendor" bole aur context se clear na ho konsa matlab hai, "query_understood":
false karo aur poocho "Vendor se aapka matlab shop/retailer hai ya manufacturer/company?" -- yahan
guess karna GALAT hoga kyunki dono results bilkul different honge.
IMPORTANT DISTINCTION: "vend" (bina "or" ke, jaise "is vend ka data do") EK ALAG word hai --
yeh Indian liquor excise licensing ki official terminology hai, aur HAMESHA "party" (shop) ko hi
refer karta hai, koi ambiguity nahi hai. Sirf "vendor" (poora word, "or" ke saath) ambiguous hai.

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

"metric" chaar types ka ho sakta hai:
- "sum" (default) -- sale_qty_in_box ka total. Yeh QUANTITY hai (boxes), currency NAHI hai.
  METRIC SYNONYMS: user "sale", "sales", "qty", "quantity", "volume", "units", "boxes",
  "off-take" (FMCG industry term), "lifting" (retailer ne kitna utha), "movement", "numbers"
  jaisa bhi bole -- sab isi "sum" (sale_qty_in_box) metric ko refer karte hain.
  ⚠️ AMBIGUOUS: "turnover", "business", "revenue" jaise words kabhi MONEY/CURRENCY imply karte
  hain -- humare paas revenue/currency data NAHI hai (sirf quantity hai). Agar user in words
  se currency/rupees maang raha lage, "query_understood": false karo aur clarify karo ki
  "sirf quantity (boxes) available hai, revenue/rupees nahi -- yehi chahiye kya?"
- "count_distinct" -- jab user "kitne total X hai" jaisa pooche (jaise "total kitne shop code hai", "kitne alag brand hain"). Is case mein "count_dimension" field mein woh dimension daalo jiska unique count chahiye, aur group_by/filters normal rahenge.
- "market_share" -- jab user kisi specific brand/product/company ka "market share" ya "% hissa" total sale mein poochta hai (jaise "Dennis ka market share kya hai har shop mein"). Is case mein:
  - "filters" mein overall context filters daalo (jaise month)
  - "share_filter" mein woh specific dimension+value daalo jiska share nikalna hai (jaise {{"brand": "Dennis"}})
  - "group_by" mein woh dimensions daalo jiske hisaab se share dikhana hai (jaise shop-wise ya department-wise share ke liye ["party", "department"]; agar sirf ek overall number chahiye, group_by empty [] rakho)
- "average" -- jab user "average/mean sale per X" jaisa pooche (jaise "Dennis ka average sale per shop", "brand wise average sale per shop"). Formula: Total Qty / Unique count of X. Is case mein:
  - "avg_per_dimension" mein woh dimension daalo jiske "per" average nikalna hai (jaise "per shop" -> "party", "per TSE" -> "tse")
  - "filters" mein context filters daalo (jaise brand)
  - "group_by" -- agar ek hi overall average chahiye, empty [] rakho. Agar "brand wise average" jaisa breakdown chahiye, group_by mein woh dimension daalo (jaise ["brand"])
  ⚠️ IMPORTANT EDGE CASE -- agar user "[X dimension]-wise average sale" bole JAHAN X dimension
  WAHI hai jo already avg_per_dimension mein hai (jaise "Royal Ace ki shop-wise average sale
  batao" -- yahan "average sale PER SHOP" already bola gaya pehle, ab "shop-wise breakdown"
  poocha ja raha hai) -- iska koi mathematical sense nahi banta agar group_by aur
  avg_per_dimension dono SHOP hi ho jayein (har group mein 1 hi shop hoga, average uska apna
  total hi ban jayega, useless calculation). Is case mein "avg_per_dimension" ko "month" set
  karo (chahe user ne explicitly na bola ho) -- yeh sabse sensible business metric hai: "har
  shop ka AVERAGE MONTHLY sale" (jitne mahino ka data hai unme se average). group_by mein
  wahi dimension rakho jo user ne bola (jaise ["party"] shop-wise ke liye).

Rules:
- ⚠️ CONVERSATION MEMORY -- agar tumhe PICHLE messages (conversation history) diye gaye hain is
  request mein, unhe FOLLOW-UP context ke liye use karo. Jaise agar pichla sawaal "Dennis ki May
  sale kya hai" tha, aur ab naya sawaal sirf "April ki bhi batao" hai (khud mein incomplete --
  "April ki KISKI bhi batao?"), pichle message se "Dennis" (brand) INHERIT karo, aur naya sawaal
  "Dennis ki April sale" jaisa treat karo. SIRF woh entities inherit karo jo NAYE sawaal mein
  missing hain (jaise brand/company/dimension) -- jo cheez naye sawaal mein EXPLICITLY badal di
  gayi hai (jaise "April" yahan month hai), usko naye sawaal se hi lo, purane se mat lo. Agar
  naya sawaal khud mein COMPLETE hai (sab entities clearly bataye gaye hain), purana context
  IGNORE karo -- sirf genuinely INCOMPLETE follow-up questions ke liye inherit karo.
  ⚠️ CORRECTION PATTERN (bahut zaroori) -- agar naya message "nahi X nahi, Y chahiye tha" ya
  "galat, Y bolo" ya "X nahi Y" jaisa NEGATION + REPLACEMENT ho (matlab user pichla answer galat
  bata raha hai aur sahi value de raha hai), TOH: (1) pichle sawaal ke SAARE OTHER entities
  (brand/company/dimension) as-it-is INHERIT karo, (2) SIRF jo specific value negate ki gayi hai
  (jaise "May" yahan), usko naye diye gaye value (jaise "April") se REPLACE karo. Example: pichla
  sawaal "Dennis ki May sale kya hai" tha, naya message "nahi May nahi, April chahiye tha" hai --
  iska matlab hai "Dennis ki April sale batao" (Dennis inherit hua, May → April replace hua).
  Yeh EXACT SAME MECHANISM hai jo simple follow-up ("April ki bhi batao") ke liye use hota hai --
  bas is case mein negation-language ("nahi X nahi") clearly signal karti hai ki KAUNSI purani
  value replace karni hai.
  ⚠️ "EXPLAIN THIS NUMBER" PATTERN -- agar naya message "yeh kaise calculate hua", "breakdown do",
  "explain karo", "kaise aaya yeh number", "isko todke dikhao" jaisa ho (matlab user pichle
  message mein diye gaye NUMBER ka BREAKDOWN/JUSTIFICATION maang raha hai, koi naya entity nahi
  de raha), TOH: (1) pichle sawaal ke SAARE entities (brand/company/TSE/etc.) as-it-is INHERIT
  karo, (2) intent ko "generic" set karo, group_by mein ek ADDITIONAL dimension add karo taaki
  breakdown dikhe jo total ko justify kare -- agar pichle sawaal mein KOI month_filter NAHI tha
  (matlab total SAARE loaded months ka combined tha), group_by mein "month" add karo (taaki
  month-wise breakdown dikhe jiska sum = original total). Agar pichle sawaal mein PEHLE SE hi
  ek specific month tha, group_by mein "department" add karo (taaki us specific month ke andar
  department-wise breakdown dikhe). Example: pichla sawaal "Dennis ki total sale kya hai" tha
  (koi month_filter nahi, matlab combined total), jawab "51617" tha, naya message "yeh kaise
  calculate hua" hai -- iska matlab hai filters: {{"brand": "Dennis"}}, group_by: ["month"],
  metric: "sum" (jisse "Apr-26: 31536, May-26: 20081" jaisa breakdown milega, jiska sum 51617
  ban jayega -- yehi "explanation" hai).
- group_by mein 1-3 dimensions daalo jo user pucha hai (jaise "TSE department wise" -> ["tse", "department"])
- ⚠️ CRITICAL -- BARE DIMENSION NAMES (jaise "brand", "tse", "month", "company") YA UNKE NATURAL
  VARIATIONS (jaise "which brand", "kaunsa brand", "brand kaun sa") KABHI FILTER VALUE NAHI HOTE,
  hamesha GROUP_BY dimension hote hain -- chahe SINGLE word ho ya "which/kaunsa/kaun sa" ke
  saath ho. Isi tarah, SALE/METRIC verbs (jaise "sell", "sold", "selling", "bikta", "becha",
  "bikti", "sale") kabhi filter value nahi hote, sirf metric confirm karte hain (sum). Jab user
  comma-separated keyword-list style query de (jaise "Rock and Storm, which brand, sell, mayur
  vihar shop" -- proper sentence nahi, sirf words/phrases ki list), samjho ki "which brand"
  yahan DIMENSION NAME hai jiske hisaab se BREAKDOWN chahiye (group_by mein "brand" daalo),
  "sell" sirf metric=sum confirm karta hai, "Rock and Storm" aur "mayur vihar shop" FILTER
  VALUES hain (company aur party). AISA MAT KARO: filters mein {{"brand": "which brand", "tse":
  "tse", "month": "month"}} jaisa literal phrase ko filter value maan lena -- yeh HAMESHA galat
  hoga (data mein "which brand" naam ka koi brand nahi hota), aur "koi data nahi mila" jaisa
  misleading empty result dega jabki asal mein data maujood hota hai. Sahi mapping ("Rock and
  Storm, which brand, sell, mayur vihar shop" ke liye): filters: {{"company": "Rock and Storm",
  "party": "mayur vihar shop"}}, group_by: ["brand"], metric: "sum". Sahi mapping ("Rock and
  Storm, brand, sale, tse, month" ke liye): filters: {{"company": "Rock and Storm"}}, group_by:
  ["brand", "tse", "month"], metric: "sum".
- ⚠️ EXCEPTION to above: agar "department/shop/tse wise" ke SAATH "market share" ya "segment
  share" (specific ek brand ke liye) bhi poocha ho, yeh generic group_by MAT use karo -- iske
  liye "brand_report" intent use karo (woh market share % + department breakdown dono deta hai
  ek saath). Generic sirf tab use karo jab SIRF plain quantity/sum chahiye ho, % share nahi.
- filters mein JITNE BHI dimensions ka specific value user ne mention kiya ho, sab daalo (multiple filters ek saath chal sakte hain -- jaise "April mein DCCWS department ka Whisky" -> {{"month": "Apr", "department": "DCCWS", "liquor_type": "Whisky"}})
- Agar do mahino ka comparison chahiye ("April vs May"), month ko group_by mein daalo, filter mein nahi
- top_n default 10, agar "top 5" jaisa kuch bola hai to wahi number daalo
- ⚠️ UNIVERSAL RULE (SAB intents ke liye, sirf generic ke liye nahi): jahan bhi "top_n",
  "top_n_shops", "top_n_brands", "bottom_n_shops", ya koi bhi "N/count/number" wala parameter
  ho, HAMESHA user ke sawaal mein jo ACTUAL number likha hai wahi use karo -- EXACT wahi digit.
  In system instructions mein jahan bhi examples mein "10", "20", "5" jaisi values dikhayi gayi
  hain (jaise "top_n": 20), yeh SIRF illustration hain, FIXED defaults NAHI -- inhe kabhi bhi
  user ke actual number ke upar priority mat do. Sawaal ko dobara dhyan se padho, jo number
  wahan likha hai (jaise "top 3" mein "3") wahi params mein daalo -- default value SIRF tab lo
  jab sawaal mein SACH MEIN koi number na ho.
- Agar sawaal total/overall pucha hai bina kisi grouping ke, group_by ko empty list [] rakho
- "kitne total/alag/unique X hai" jaise sawaalon ke liye metric="count_distinct" use karo, group_by ko empty [] rakho
- "value_range" -- jab user kisi NUMBER RANGE ke andar wale items poochta hai (jaise "500-1000
  boxes wale brands", "1000 se zyada bechne wale shops", "100 se kam sale wale TSE"). Yeh filter
  hai TOTAL QUANTITY pe (calculation ke BAAD), na ki kisi dimension value pe. Format:
  {{"min": 500, "max": 1000}} (dono ho sakte hain, ya sirf ek -- "1000 se zyada" ->
  {{"min": 1000, "max": null}}, "100 se kam" -> {{"min": null, "max": 100}}). group_by mein woh
  dimension daalo jiske range check karni hai (jaise ["brand"]). Jab value_range use ho, top_n
  ko 50 rakho (jab tak user khud koi number na de) -- taaki range ke SAARE matching items dikhein,
  sirf top 10 nahi.
- "sort_desc" IMPORTANT: default true hai (sabse zyada/top/highest). Agar user "sabse KAM", "kam se
  kam", "lowest", "minimum", "sabse chhota", "worst" jaisa kuch bole, "sort_desc": false karo
  (taaki lowest values sabse upar aayen). Jaise "Dennis ki sabse kam sale kaha hai" ->
  filters:{{"brand":"Dennis"}}, group_by:["party"], sort_desc:false, top_n:1 (ya jitna user maange)
"""


FIELD_DISPLAY_LABELS = {
    'brand': '🥃 Brand',
    'company': '🏢 Company',
    'bd_segment': '🏷️ BD Segment',
    'sale_qty': '📦 Sale Qty (Boxes)',
    'month': '📅 Month',
    'brand_pct_of_segment': '📊 Brand % of Segment',
    'Total': '📦 Total',
    'brand_pct_of_total_segment': '📊 Brand % of Total Segment',
    'brand_month_breakdown': '📊 Brand-wise Month Breakdown',
    'pct_within_bd_segment': '📊 % Within Segment',
    'pct_of_market': '🌍 % of Market',
    'shops_selling': '🏪 Shops Selling',
    'shops_selling_brand': '🏪 Shops Selling Brand',
    'department_breakdown': '🏛️ Department Breakdown',
    'department_market_share_pct': '🌍 Department Market Share %',
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
    # mom_gainers_losers / brand_mom_check / general report fields
    'current_month': '📅 Current Month',
    'previous_month': '📅 Previous Month',
    'top_gainers': '🚀 Top Gainers',
    'top_losers': '📉 Top Losers',
    'new_entries': '🆕 New Entries',
    'dropped_brands': '⚰️ Dropped Brands',
    'brand_name_as_per_company_data': '🥃 Brand',
    'current_qty': '📦 Current Qty',
    'previous_qty': '📦 Previous Qty',
    'change_qty': '🔄 Change (Qty)',
    'pct_change': '📊 % Change',
    'total_items_analyzed': '🔢 Total Items Analyzed',
    'mean_pct_change': '📊 Average % Change (All Items)',
    'std_pct_change': '📊 Std Deviation (% Change)',
    'anomalies_found': '🚨 Anomalies Found',
    'note': '📝 Note',
    'anomalies': '🚨 Anomalies',
    'item': '🥃 Item',
    'current_qty': '📦 Current Qty',
    'previous_qty': '📦 Previous Qty',
    'z_score': '📊 Z-Score',
    'anomaly_type': '🚨 Type',
    'top_contributing_department': '🏛️ Top Contributing Department',
    'top_contributor_change_qty': '🔄 Change From That Department',
    'current_month_qty': '📦 Current Month Qty',
    'previous_month_qty': '📦 Previous Month Qty',
    'is_new_entry': '🆕 New Entry?',
    'is_dropped': '⚰️ Dropped?',
    'rank': '🏆 Rank',
    'shop_code': '🏪 Shop Code',
    'shop_name_as_per_company_data': '🏪 Shop Name',
    'department': '🏛️ Department',
    'total_qty': '📦 Total Qty',
    'market_share_pct': '📊 Market Share %',
    'subset_qty': '📦 Qty',
    'brand_qty': '📦 Brand Qty',
    'brand_sale_qty': '📦 Brand Sale Qty',
    'breakdown_by': '🔍 Breakdown By',
    'overall_change_qty': '🔄 Overall Change (Qty)',
    'breakdown': '📊 Growth Breakdown',
    'salesman_tse': '👤 TSE',
    'pct_of_total_change': '📊 % of Total Change',
    'avg_qty': '📈 Average Qty',
    'total_count': '🔢 Total Count',
    'top_brand_pct': '📊 Top Brand % of Total',
    'value': '📊 Value',
    'brand_total_qty_in_segment': '📦 Brand Total Qty (Segment)',
    'top_shop_name': '🏪 Top Shop',
    'brand_qty_at_shop': '📦 Brand Qty at Shop',
    'brand_segment_pct_at_shop': '🌍 Brand Segment % at Shop',
    'brand_total_market_share': '🌍 Brand Total Market Share',
    'segment_total_sale': '📦 Segment Total Sale',
    'overall_total_market': '📦 Total Sale (All Segments)',
    'segment_pct_of_overall_market': '🌍 Segment % of Overall Market',
    'brand_overall_qty': '📦 Qty',
    'brand_overall_pct_of_market': '🌍 Market Share',
    'brand_overall_pct_of_segment': '📊 Segment Share',
    'company_name': '🏢 Company Name',
    'compare_brand_overall_qty': '📦 Qty',
    'compare_brand_overall_pct_of_market': '🌍 Market Share',
    'compare_brand_overall_pct_of_segment': '📊 Segment Share',
    'compare_brand_qty_at_shop': '📦 Compare Brand Qty at Shop',
    'segment_pct_at_shop': '🌍 Segment % at Shop',
    'total_market_share': '🌍 Total Market Share',
    'top_brands': '📊 Top Brands',
    'brand_total_qty_in_scope': '📦 Brand Total Qty',
    'brand_scope_pct_at_shop': '🌍 Brand % at Shop',
    'scope_total_sale': '📦 Total Sale',
    'pct_within_scope': '📊 % Within Scope',
    'scope_type': '🔍 Scope Type',
    'scope_value': '📌 Scope Value',
    'total_brands_in_scope': '🥃 Total Brands',
    'scope_filters': '🔍 Scope Filters',
    'scope_pct_of_overall_market': '🌍 % of Overall Market',
    'compare_brand_overall_pct_of_scope': '📊 Compare Brand Share',
    'brand_pct_of_total': '📊 Brand % of Total',
    'category_type': '🔍 Category Type',
    'category_value': '📌 Category Value',
    'category_total_sale': '📦 Category Total Sale',
    'total_brands_in_category': '🥃 Total Brands in Category',
    'combined_share': '📊 Combined Share %',
    'universe_dimension': '🌍 Universe Dimension',
    'total_universe_count': '🔢 Total Universe Count',
    'present_count': '✅ Present Count',
    'absent_count': '❌ Absent Count (Zero Sale)',
    'absent_items': '❌ Zero-Sale Items',
    'shop_name': '🏪 Shop Name',
    'sl_no': '🔢 Sl No',
    'sale_qty_in_box': '📦 Sale Qty in Box',
    'segment_sale_on_shop': '📦 Segment Sale on Shop',
    'rows': '📊 Zero-Sale Shops with Top Segment Brands',
    'rows_top': '📊 Zero-Sale Shops with Top Segment Brands',
    'rows_bottom': '📊 Zero-Sale Shops with Bottom Segment Brands',
    'rows_mid': '📊 Zero-Sale Shops with Mid Segment Brands',
    'top_n': '🔢 Top N',
    'n': '🔢 N',
    'rank_direction': '📊 Rank Direction',
    'transaction_count': '🔢 Transaction Count',
    'months': '📅 Month(s)',
    'target_transaction_count': '🎯 Target Count',
    'matching_shops_count': '🔢 Matching Shops (Total)',
    'shops_shown': '👁️ Shops Shown',
    'pivot_table': '📊 Pivot Table',
    'shop': '🏪 Shop',
    'brand_qty_shop_seg_pct': '📦 Qty / Shop Seg %',
    'top_1': '🥇 Top 1',
    'top_2': '🥈 Top 2',
    'top_3': '🥉 Top 3',
    'top_4': '🏅 Top 4',
    'top_5': '🏅 Top 5',
    'brand_query_name': '📌 Brand Query Name',
    'brand_segment_name': '🏷️ Brand Segment Name',
    'brand_query_shop_seg_pct': '📦 Brand - Shop Seg %',
    'brand_1': '🔹 Brand 1',
    'brand_2': '🔹 Brand 2',
    'brand_3': '🔹 Brand 3',
    'brand_4': '🔹 Brand 4',
    'brand_5': '🔹 Brand 5',
    'top_brands_at_each_shop': '📊 Top Brands at Each Shop',
    'rank_in_segment': '🏆 Rank in Segment',
    'hero_brand_in_segment': '👑 Hero Brand (Same Segment)',
    'hero_brand_qty': '📦 Hero Brand Qty',
    'row_dimension': '📊 Row Dimension',
    'col_dimension': '📊 Column Dimension',
    'matrix': '📊 Matrix',
    'ranking': '🏆 Ranking',
    'volume_rank': '📦 Volume Rank',
    'growth_rank': '📈 Growth Rank',
    'combined_rank_score': '🏆 Combined Score',
    'filters_applied': '🔍 Filters Applied',
    'breakdown_dimension': '🔍 Breakdown Dimension',
    'primary_total_qty': '📦 Total Qty',
    'primary_pct_of_overall_market': '🌍 Overall Market Share %',
    'breakdown': '📊 Breakdown',
    'item': '⭐ Item',
    'qty': '📦 Qty',
    'pct_within_primary': '📊 % Within Filter',
    'pct_of_overall_market': '🌍 % of Overall Market',
    'top_brand_market_share_pct_at_shop': '🌍 Market Share % (Segment)',
    'rank_here': '🏆 Rank Here',
    'top_brand_here': '⭐ Top Brand Here',
    'item': '📌 Item',
}
# For these fields, a HIGHER number is the "winner" (gets 🥇 highlighted)
HIGHER_IS_BETTER_FIELDS = {
    'sale_qty', 'pct_within_bd_segment', 'pct_of_market', 'shops_selling',
    'total_sale_qty', 'overall_market_share_pct', 'market_share_pct', 'number_of_brands',
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
    icon_and_label = {"brand": "🥃 Brand", "company": "🏢 Company", "value": "📊 Item"}.get(entity_key, "📋 Item")
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


def _pretty_label(key: str) -> str:
    return FIELD_DISPLAY_LABELS.get(key, "📌 " + str(key).replace("_", " ").title())


# Scalar (non-table) fields that represent a percentage -- when rendered as
# a plain "**Label:** value" line, a "%" is appended automatically so the
# number is unambiguous (e.g. "Market Share: 0.03%" instead of just "0.03").
PCT_SUFFIX_KEYS = {
    'segment_pct_of_overall_market',
    'compare_brand_overall_pct_of_market',
    'compare_brand_overall_pct_of_segment',
    'compare_brand_overall_pct_of_scope',
    'brand_overall_pct_of_market',
    'brand_overall_pct_of_segment',
    'primary_pct_of_overall_market',
    'scope_pct_of_overall_market',
    'market_share_pct',
    'pct_of_market',
    'mean_pct_change',
    'std_pct_change',
}


# Eye-catching emojis for the top 3 rows of a 'pct_change' column -- gainers
# (positive %) get rocket/fire emojis, losers (negative %) get warning/down
# emojis. Only the first 3 rows get decorated (assumes the list is already
# sorted by significance, which gainers/losers/rankings always are).
TOP3_GAIN_EMOJIS = ['🔥🚀', '🚀', '✨']
TOP3_LOSS_EMOJIS = ['🆘📉', '📉', '🔻']


def _decorate_cell(column: str, value, row_index: int) -> str:
    if column == 'pct_change':
        try:
            num = float(value)
        except (ValueError, TypeError):
            return str(value)
        if row_index < 3 and num != 0:
            emoji = TOP3_GAIN_EMOJIS[row_index] if num > 0 else TOP3_LOSS_EMOJIS[row_index]
            return f"**{value}% {emoji}**"
        return f"{value}%"
    return str(value)


def dicts_to_markdown_table(records: list) -> str:
    """Builds a markdown table directly from a list of dicts -- pure Python
    string formatting, zero LLM involvement. This is the ONLY place table
    numbers get written out, guaranteeing they exactly match what's in the
    data (an LLM asked to transcribe a table can occasionally slip a digit,
    which is unacceptable for a business analytics tool)."""
    if not records:
        return "_Koi data nahi mila is query ke liye._"
    columns = list(records[0].keys())
    header = "| " + " | ".join(_pretty_label(c) for c in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    rows = []
    for idx, r in enumerate(records):
        cells = [_decorate_cell(c, r.get(c, ""), idx) for c in columns]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, sep] + rows)


DOWNLOAD_DISPLAY_LIMIT = 15


def extract_download_table(data):
    """Finds the largest list-of-dicts value in a result (the 'main table'
    of the response) and returns it as {headers, rows} with ALL rows (not
    truncated) -- sent to the frontend separately from the (truncated)
    display text, so 'Download' can export the FULL dataset (e.g. all 94
    zero-sale shops) even though the screen only shows 50 for readability.
    Returns None if there's no table-shaped data to download."""
    candidates = []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        candidates.append(data)
    elif isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                candidates.append(value)
    if not candidates:
        return None
    best = max(candidates, key=len)
    columns = list(best[0].keys())
    headers = [_pretty_label(c) for c in columns]
    rows = [[str(r.get(c, "")) for c in columns] for r in best]
    return {"headers": headers, "rows": rows}


def render_data_deterministically(data) -> str:
    """Converts whatever run_query/run_special_intent returned (string,
    list of records, or a result dict) into final display text -- entirely
    in Python. No LLM ever re-types a number here."""
    if isinstance(data, str):
        return data

    if isinstance(data, list):
        return dicts_to_markdown_table(data[:DOWNLOAD_DISPLAY_LIMIT])

    if isinstance(data, dict):
        if data.get("found") is False:
            lines = [f"❌ {data.get('message', 'Data nahi mila.')}"]
            for key in ("similar_brands", "similar_companies"):
                if data.get(key):
                    lines.append("💡 Kya aapka matlab in mein se tha: " + ", ".join(data[key]))
            return "\n".join(lines)

        # Per-response override: some reports (e.g. segment_month_brand_
        # breakdown -- a management report meant to be reviewed in full,
        # not skimmed) explicitly ask to show ALL rows on screen instead
        # of the default truncated limit.
        row_limit = None if data.get("__show_full__") else DOWNLOAD_DISPLAY_LIMIT

        sections = []
        for key, value in data.items():
            if key in ("found", "__show_full__"):
                continue
            label = _pretty_label(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                display_rows = value if row_limit is None else value[:row_limit]
                sections.append(f"**{label}**\n\n{dicts_to_markdown_table(display_rows)}")
            elif isinstance(value, dict) and value:
                # A plain {name: number} dict (e.g. market_share's 'ranking'
                # field) -- convert to proper table rows instead of dumping
                # it as raw Python dict text like "{'X': 18.75, 'Y': 10.38}".
                records = [{"item": k, "value": v} for k, v in value.items()]
                sections.append(f"**{label}**\n\n{dicts_to_markdown_table(records)}")
            elif isinstance(value, list):
                sections.append(f"**{label}:** {', '.join(str(v) for v in value)}")
            elif key in PCT_SUFFIX_KEYS and isinstance(value, (int, float)):
                sections.append(f"**{label}:** {value}%")
            else:
                sections.append(f"**{label}:** {value}")
        return "\n\n".join(sections)

    return str(data)


def parse_query_with_claude(question: str, history: list = None) -> dict:
    messages = []
    if history:
        # Only the last few exchanges -- enough context for a natural
        # follow-up question ("April ki bhi batao") without bloating every
        # single parse call with the whole conversation. Anthropic's API
        # requires alternating user/assistant turns starting with "user",
        # so we filter to valid roles and keep them in order.
        recent = [m for m in history[-6:] if m.get("role") in ("user", "assistant") and m.get("content")]
        for m in recent:
            messages.append({"role": m["role"], "content": str(m["content"])})
    messages.append({"role": "user", "content": question})

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=700,  # schema has grown a lot (18 intents, many fields) -- 300 was
                         # too small and caused JSON to get cut off mid-structure for
                         # complex/combined queries, crashing the parser entirely.
        temperature=0,   # CRITICAL for consistency -- this is a structured-parsing task
                         # (turn a question into JSON), not a creative one. Without this,
                         # the API defaults to temperature=1.0, which means the SAME
                         # exact query can produce DIFFERENT JSON on different calls --
                         # this was the root cause of "works sometimes, not others".
                         # temperature=0 makes output maximally deterministic/repeatable.
        system=QUERY_PARSER_SYSTEM,
        messages=messages,
    )
    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Safety net: sometimes the model adds stray text before/after the
        # JSON despite instructions -- try extracting just the {...} block.
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


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
    3. AMBIGUITY CHECK -- if the user gave NO year at all and that bare
       month name actually matches MULTIPLE different years in the real
       data (e.g. "April" when both Apr-26 and Apr-27 exist), this does
       NOT guess. It returns a sentinel string that run_query recognizes
       and turns into a clarification question -- silently picking a year
       would be exactly the kind of confident-but-wrong answer that broke
       trust before.
    """
    v = value.strip().lower()

    if v in RELATIVE_MONTH_CURRENT:
        _, _, cur_label, _ = get_current_and_previous_month_df()
        return cur_label or value
    if v in RELATIVE_MONTH_PREVIOUS:
        _, _, _, prev_label = get_current_and_previous_month_df()
        return prev_label or value

    normalized_value = value
    for full_name, abbr in MONTH_NAME_TO_ABBR.items():
        if v == full_name or v.startswith(full_name + ' '):
            normalized_value = value.lower().replace(full_name, abbr)
            break

    # If the user gave no digits at all (no year mentioned), check whether
    # this bare month name actually spans multiple years in the real data.
    if not any(ch.isdigit() for ch in value) and not df.empty:
        month_prefix = normalized_value.strip().lower()[:3]
        matching_months = sorted(
            m for m in df[COL_MONTH].astype(str).unique()
            if str(m).lower().startswith(month_prefix)
        )
        if len(matching_months) > 1:
            return "__AMBIGUOUS_MONTH__:" + ",".join(matching_months)

    return normalized_value


# Words that should NEVER be an actual filter VALUE -- these are dimension
# NAMES, metric/verb words, or question words. No real brand/shop/company
# name in this dataset is literally "brand", "sell", or "which" -- so if
# the parser ever puts one of these as a filter value (a known recurring
# LLM mistake with terse/keyword-list style queries), it's a CERTAIN
# mistake, not ambiguity. Auto-correcting this here (moving it to group_by
# instead) is a permanent, code-level fix -- it catches EVERY future
# phrasing variation automatically, instead of needing a new prompt
# example added every time a new wording trips up the parser.
NON_VALUE_WORDS = {
    'brand', 'brands', 'tse', 'month', 'months', 'company', 'companies',
    'department', 'departments', 'shop', 'shops', 'party', 'parties',
    'segment', 'segments', 'bd_segment', 'liquor_type', 'pack_size',
    'category', 'shop_code', 'sale', 'sales', 'sell', 'sold', 'selling',
    'quantity', 'qty', 'total', 'which', 'kaunsa', 'kaun', 'konsa',
    'kya', 'wise',
}


def _is_non_value_phrase(value: str) -> bool:
    """True if EVERY word in the value is a dimension-name/verb/question
    word (meaning the WHOLE phrase is meta-talk, not a real named entity).
    A real shop name like 'Mayur Vihar Shop' has 'mayur'/'vihar' which
    ISN'T in the word list, so it's correctly left alone -- but "which
    brand" is ENTIRELY made of such words, so it's caught."""
    words = value.strip().lower().split()
    return bool(words) and all(w in NON_VALUE_WORDS for w in words)


def _autocorrect_filter_group_by_confusion(spec: dict):
    """If any filter's VALUE is literally a dimension-name/verb/question
    word or PHRASE (never a real value in this data), move that dimension
    to group_by instead of leaving it as a (guaranteed-wrong) filter."""
    filters = spec.get("filters") or {}
    group_by = spec.get("group_by") or []
    for dim in list(filters.keys()):
        if _is_non_value_phrase(str(filters[dim])):
            del filters[dim]
            if dim not in group_by:
                group_by.append(dim)
    spec["filters"] = filters
    spec["group_by"] = group_by


# Business context: TSE assignments in this dataset are tracked per-shop
# ACROSS ALL companies mixed together (a TSE's territory includes every
# company's brands sold at their assigned shops) -- but Angel's business
# is specifically about ROCK AND STORM DISTILLERIES's own performance
# through these TSEs, not the TSE's entire multi-company territory. So
# whenever a query touches the "tse" dimension WITHOUT an explicit,
# different company scope, default to Rock and Storm Distilleries --
# otherwise numbers silently include competitor brands' sales too (e.g.
# "Sunil ki sale" without this default included OMSONS's brands, which
# have nothing to do with Angel's own company).
DEFAULT_TSE_COMPANY_SCOPE = "Rock and Storm Distilleries"


def _apply_default_tse_company_scope(spec: dict):
    filters = spec.get("filters") or {}
    group_by = spec.get("group_by") or []
    touches_tse = "tse" in filters or "tse" in group_by
    has_explicit_company = "company" in filters
    if touches_tse and not has_explicit_company:
        filters["company"] = DEFAULT_TSE_COMPANY_SCOPE
    spec["filters"] = filters


def run_query(spec: dict, working_df=None):
    _autocorrect_filter_group_by_confusion(spec)
    _apply_default_tse_company_scope(spec)
    filtered = working_df if working_df is not None else df

    # Apply filters -- each value is first fuzzy-resolved to the closest
    # REAL value in that column (exact -> substring -> typo-tolerant match),
    # then applied as a filter. This means every dimension (department,
    # company, liquor_type, etc.) tolerates partial names and small spelling
    # differences, not just brand/bd_segment.
    for dim, value in (spec.get("filters") or {}).items():
        col = DIMENSIONS.get(dim)
        if col and col in filtered.columns:
            if dim == "month":
                original_value = value
                value = resolve_month_reference(str(value))
                if isinstance(value, str) and value.startswith("__AMBIGUOUS_MONTH__:"):
                    options = value.split(":", 1)[1]
                    return (f"🤔 '{original_value}' ke liye {len(options.split(','))} saal ka data mila "
                            f"({options}) -- konsa chahiye? Saal ke saath batao, jaise 'April 2026'.")
            if dim == "party":
                # Shop/location references often match MULTIPLE distinct
                # shops (e.g. "Mayur Vihar" matches 12 different outlets)
                # -- include ALL of them (not just the highest-selling
                # one), and auto-add "party" to group_by so the reply
                # shows a shop-wise split instead of silently collapsing
                # 12 shops' data into one blended number.
                all_matches = fuzzy_resolve_multi_match(str(value), col)
                if all_matches:
                    filtered = filtered[filtered[col].isin(all_matches)]
                    if len(all_matches) > 1:
                        group_by_list = spec.get("group_by") or []
                        if "party" not in group_by_list:
                            group_by_list.append("party")
                            spec["group_by"] = group_by_list
                    continue
            if dim == "brand":
                # Same ambiguity risk as specialized intents (e.g. "Royal"
                # matches 13 different products) -- use resolve_brand_name
                # (which raises BrandAmbiguityError on genuine ambiguity)
                # instead of the plain fuzzy_resolve_value, so the GENERIC
                # engine gets the same protection specialized intents do.
                resolved_value = resolve_brand_name(str(value))
                filtered = filtered[filtered[col].astype(str).str.contains(str(resolved_value), case=False, na=False)]
                continue
            if dim == "tse":
                # Same ambiguity risk as brand -- e.g. bare "Kumar" matches
                # 3 different TSEs (Ravinder Kumar, Raj kumar, Lalit Kumar).
                resolved_value = resolve_tse_name(str(value))
                filtered = filtered[filtered[col].astype(str).str.contains(str(resolved_value), case=False, na=False)]
                continue
            if dim == "company":
                # Same ambiguity risk -- e.g. "Rock and Storm" matches 2
                # distinct companies (Rock and Storm DISTILLERIES vs Rock
                # and Storm BOTTLERS).
                resolved_value = resolve_company_name(str(value))
                filtered = filtered[filtered[col].astype(str).str.contains(str(resolved_value), case=False, na=False)]
                continue
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

    # Average metric: Total Qty / Unique count of some dimension (e.g.
    # "average sale per shop" = total qty / distinct shop count)
    if spec.get("metric") == "average":
        avg_dim = spec.get("avg_per_dimension")
        avg_col = DIMENSIONS.get(avg_dim)
        if not avg_col:
            return "Average nikalne ke liye valid 'per' dimension chahiye (jaise shop, tse, department)."

        group_by = [DIMENSIONS[d] for d in (spec.get("group_by") or []) if d in DIMENSIONS]

        # Defensive fix: averaging "per X" while ALSO grouping BY X is both
        # mathematically meaningless (each group would trivially have
        # exactly 1 unique X, making "average" just equal the group's own
        # total) AND used to CRASH with a pandas KeyError (a groupby
        # column gets excluded from the per-group dataframe inside
        # .apply()). Auto-correct to a sensible default instead: average
        # per MONTH -- almost certainly what "[X]-wise average sale" means
        # when X is the same dimension already being averaged "per".
        if avg_col in group_by:
            avg_dim = "month"
            avg_col = DIMENSIONS.get("month")

        top_n = spec.get("top_n") or 10
        sort_desc = spec.get("sort_desc", True)

        if not group_by:
            total = filtered[COL_QTY].sum()
            count = filtered[avg_col].nunique()
            avg = round(total / count, 2) if count else 0
            return f"Average Sale per {avg_dim.title()}: {avg} (Total Qty: {total} / {count} unique {avg_dim})"

        grouped = filtered.groupby(group_by)
        avg_series = grouped.apply(
            lambda g: round(g[COL_QTY].sum() / g[avg_col].nunique(), 2) if g[avg_col].nunique() else 0
        )
        avg_series = avg_series.rename('avg_qty').sort_values(ascending=not sort_desc).head(top_n)
        return avg_series.reset_index().to_dict('records')

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

    # value_range: filter the AGGREGATED totals (like SQL's HAVING clause) --
    # e.g. "500-1000 boxes wale brands" keeps only groups whose total falls
    # in that range, applied AFTER summing, before sorting/limiting.
    value_range = spec.get("value_range")
    if value_range:
        if value_range.get("min") is not None:
            result = result[result >= value_range["min"]]
        if value_range.get("max") is not None:
            result = result[result <= value_range["max"]]
        if result.empty:
            return f"Is range ({value_range.get('min', '-')} se {value_range.get('max', '-')}) mein koi data nahi mila."

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
    # Also treat "&" and "and" as EQUIVALENT before stripping (convert "&"
    # to "AND" first) -- otherwise "White and Blue" wouldn't match the real
    # brand "WHITE & BLUE SELECT WHISKY", since stripping "&" to nothing
    # loses the word entirely while the user's "and" remains, breaking the
    # substring match.
    def _normalize(s: str) -> str:
        s = s.upper().replace('&', ' AND ')
        return re.sub(r'[^A-Z0-9]', '', s)

    normalized_user = _normalize(user_value)
    if normalized_user:
        normalized_map = {v: _normalize(v) for v in unique_values}
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


# Generic descriptor words that aren't part of an actual shop/location
# name -- users often add these as filler ("Mayur Vihar SHOP", "XYZ
# dukaan") even though the real shop name never literally contains them.
# Stripping them before matching avoids missing otherwise-clear matches.
GENERIC_LOCATION_WORDS = {'shop', 'shops', 'dukaan', 'theka', 'vend', 'store', 'outlet'}


def _strip_generic_location_words(value: str) -> str:
    words = value.split()
    filtered = [w for w in words if w.lower() not in GENERIC_LOCATION_WORDS]
    stripped = " ".join(filtered).strip()
    return stripped if stripped else value


def fuzzy_resolve_multi_match(user_value: str, column) -> list:
    """Like fuzzy_resolve_value's substring tier, but returns ALL distinct
    matching values instead of silently picking just the single highest-
    volume one. Important for shop/location references: "Mayur Vihar"
    genuinely matches MANY distinct physical shops -- silently narrowing to
    just 1 (as fuzzy_resolve_value does) throws away real data the user
    almost certainly wanted included. Falls back to fuzzy_resolve_value's
    full 5-tier single-match logic (wrapped in a list) if no substring
    match is found even after stripping generic words, so this is never
    LESS capable than the original single-match resolver."""
    if df.empty or not user_value or column not in df.columns:
        return []
    search_value = _strip_generic_location_words(user_value)

    col_series = df[column].astype(str)
    unique_values = col_series.unique()

    upper_to_actual = {}
    for v in unique_values:
        upper_to_actual.setdefault(v.upper(), v)
    if search_value.upper() in upper_to_actual:
        return [upper_to_actual[search_value.upper()]]

    contains_mask = col_series.str.contains(search_value, case=False, na=False, regex=False)
    if contains_mask.any():
        matches = df.loc[contains_mask]
        ranked = matches.groupby(column)[COL_QTY].sum().sort_values(ascending=False)
        return list(ranked.index)

    # Nothing matched even after stripping filler words -- fall back to the
    # full 5-tier single-match resolver (normalized/fuzzy/prefix matching)
    # rather than giving up entirely.
    fallback = fuzzy_resolve_value(search_value, column)
    return [fallback] if fallback else []


class BrandAmbiguityError(Exception):
    """Raised when a partial search term matches MULTIPLE distinct values
    of a dimension where combining/picking-one would be misleading (e.g.
    "Royal" matches 13 different brands, "Sharma" matches 2 different
    TSEs). Unlike shop/location references (where multiple matches are
    genuinely the SAME area and should be combined), different brands are
    different PRODUCTS and different TSEs are different PEOPLE -- silently
    picking one, or combining their sales into one number, would be
    misleading. Raised as an exception (not a return value) so it
    propagates up through ANY intent-handling code path without needing
    every individual call site to be modified -- caught ONCE, centrally,
    in the /chat endpoint. (Kept this name for backward compatibility even
    though it's now used for TSE ambiguity too, not just brands.)"""
    def __init__(self, search_term, options, dimension_label="brand"):
        self.search_term = search_term
        self.options = options
        self.dimension_label = dimension_label
        super().__init__(f"Ambiguous {dimension_label}: {search_term}")


def _resolve_with_ambiguity_check(partial_name: str, column: str, dimension_label: str) -> str:
    """Shared resolution logic used by resolve_brand_name and
    resolve_tse_name: exact match always wins (never ambiguous); if a
    substring match hits MULTIPLE distinct values, raise
    BrandAmbiguityError instead of silently picking the highest-volume
    one; otherwise fall back to the full 5-tier fuzzy_resolve_value for
    typo-tolerance (which only ever returns ONE value, so no ambiguity
    risk there)."""
    if df.empty or not partial_name:
        return fuzzy_resolve_value(partial_name, column)

    col_series = df[column].astype(str)
    unique_values = col_series.unique()
    upper_to_actual = {}
    for v in unique_values:
        upper_to_actual.setdefault(v.upper(), v)

    # Exact match is NEVER ambiguous, even if it's also a substring of
    # other values -- the user typed the complete, correct name.
    if partial_name.upper() in upper_to_actual:
        return upper_to_actual[partial_name.upper()]

    contains_mask = col_series.str.contains(partial_name, case=False, na=False, regex=False)
    if contains_mask.any():
        matches = df.loc[contains_mask]
        ranked = matches.groupby(column)[COL_QTY].sum().sort_values(ascending=False)
        if len(ranked) > 1:
            raise BrandAmbiguityError(partial_name, list(ranked.index[:10]), dimension_label)
        return ranked.index[0]

    return fuzzy_resolve_value(partial_name, column)


def resolve_brand_name(partial_name: str) -> str:
    return _resolve_with_ambiguity_check(partial_name, COL_BRAND, "brand")


def resolve_tse_name(partial_name: str) -> str:
    """Same ambiguity protection as resolve_brand_name, for TSE names --
    e.g. bare "Kumar" matches 3 different TSEs (Ravinder Kumar, Raj kumar,
    Lalit Kumar), "Singh" matches 2 (Malkit Singh, Sher Singh), "Sharma"
    matches 2 (Sunil Sharma, Ram Gopal Sharma) -- these ask for
    clarification. Unique first/last names (Sunil, Ravinder, Ankush, Raj,
    Sher, Shammi, Kapoor, Ram, Gopal, Lalit, Thapa, Malkit, Sumit) resolve
    straight through since each matches only ONE TSE."""
    return _resolve_with_ambiguity_check(partial_name, COL_TSE, "TSE")


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
    return _resolve_with_ambiguity_check(partial_name, COL_COMPANY, "company")


def run_special_intent(intent: str, params: dict, working_df=None):
    """Routes a parsed intent to the matching SmartQueryEngine method.
    Returns a JSON string of the result (or an error message string)."""
    engine = SmartQueryEngine(working_df if working_df is not None else df)  # rebuilt fresh each call

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
            category_type = DIMENSIONS.get(params.get("category_type", "bd_segment"), COL_BD_SEGMENT)
            resolved_value = fuzzy_resolve_value(str(params["category_value"]), category_type)
            result = engine.brand_share_filter(
                resolved_value,
                threshold=params.get("threshold", 5.0),
                mode=params.get("mode", "above"),
                category_type=category_type,
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

        elif intent == "compare_dimension_values":
            dim_col = DIMENSIONS.get(params.get("dimension"))
            if not dim_col:
                return "Valid dimension chahiye (department, shop_code, party, tse, bd_segment, liquor_type, ya pack_size)."

            def _resolve_dim_value(v, col):
                if col == COL_TSE:
                    return resolve_tse_name(str(v))
                if col == COL_BRAND:
                    return resolve_brand_name(str(v))
                return fuzzy_resolve_value(str(v), col)

            resolved_values = [_resolve_dim_value(v, dim_col) for v in params["values"]]
            resolved_scope_filters = {}
            for dim, val in (params.get("scope_filters") or {}).items():
                scope_col = DIMENSIONS.get(dim)
                if scope_col:
                    resolved_scope_filters[scope_col] = _resolve_dim_value(val, scope_col)
            # Same default as elsewhere: TSE comparisons default to Rock
            # and Storm Distilleries' own sales unless a different company
            # scope was explicitly given.
            if dim_col == COL_TSE and COL_COMPANY not in resolved_scope_filters:
                resolved_scope_filters[COL_COMPANY] = resolve_company_name(DEFAULT_TSE_COMPANY_SCOPE)
            engine_result = engine.compare_dimension_values(
                dim_col, resolved_values, scope_filters=resolved_scope_filters or None
            )
            if not engine_result.get("found") and "details" not in engine_result:
                result = engine_result
            else:
                field_names = []
                for detail in engine_result["details"].values():
                    if detail.get("found"):
                        field_names = [k for k in detail.keys() if k != "found"]
                        break

                complete_table = []
                for value_input in resolved_values:
                    detail = engine_result["details"].get(value_input, {})
                    if not detail.get("found"):
                        row = {"value": value_input}
                        for f in field_names:
                            row[f] = "❌ Not Found"
                        complete_table.append(row)
                        continue
                    row = {"value": value_input}
                    for k, v in detail.items():
                        if k == "found":
                            continue
                        row[k] = v
                    complete_table.append(row)

                # Same anchor pattern: FIRST value mentioned stays fixed
                # across every table, rest chunked 2-per-table.
                return render_anchor_comparison_table(complete_table, entity_key="value")

        elif intent == "brand_weak_shops_analysis":
            compare_brand = params.get("compare_brand")
            if compare_brand:
                compare_brand = resolve_brand_name(compare_brand)
            engine_result = engine.brand_weak_shops_analysis(
                params["brand_name"],
                bottom_n_shops=params.get("bottom_n_shops", 10),
                compare_brand=compare_brand,
                top_n_other_brands=params.get("top_n_other_brands", 5),
                find_bottom=params.get("find_bottom", True),
                restrict_to_own_segment=params.get("restrict_to_own_segment", False),
            )
            if engine_result.get("found"):
                # 'rows' is already a flat list of dicts -- return it
                # directly (a list), so the normal /chat pipeline renders
                # it as a table and adds ONE insight line, same as every
                # other intent (no need to duplicate that logic here).
                return engine_result["rows"]
            result = engine_result

        elif intent == "dimension_breakdown_report":
            breakdown_col = DIMENSIONS.get(params.get("breakdown_dimension"))
            if not breakdown_col:
                return "Valid breakdown_dimension chahiye."
            raw_filters = params.get("primary_filters") or {}
            if not raw_filters:
                return "Kam se kam ek primary filter chahiye (jaise segment, department, company)."
            resolved_filters = {}
            for dim, value in raw_filters.items():
                col = DIMENSIONS.get(dim)
                if col:
                    resolved_filters[col] = fuzzy_resolve_value(str(value), col)
            result = engine.dimension_breakdown_report(
                resolved_filters, breakdown_col, top_n=params.get("top_n", 5)
            )

        elif intent == "brand_transaction_count_shopwise_tables":
            brand_name = resolve_brand_name(params["brand_name"])
            engine_result = engine.brand_transaction_count_shopwise_tables(
                brand_name,
                target_count=params.get("target_count", 1),
                comparison=params.get("comparison", "equal"),
                top_n_shops=min(params.get("top_n_shops", 10), 2000),  # safety ceiling (effectively open)
                top_n_brands=params.get("top_n_brands", 3),
                other_n_brands=params.get("other_n_brands", 5),
                other_min_pct=params.get("other_min_pct", 1.0),
                name_maxlen=params.get("name_maxlen", 15),
            )
            if not engine_result.get("found"):
                return f"❌ {engine_result.get('message', 'Data nahi mila.')}"

            lines = [
                f"**📌 Brand Query Name:** {engine_result['brand_query_name']}",
                "",
                f"**🏷️ Brand Segment Name:** {engine_result['brand_segment_name']}",
                "",
                f"**🔢 Matching Shops (Total):** {engine_result['matching_shops_count']}",
                "",
                f"**👁️ Shops Shown:** {engine_result['shops_shown']}",
                "",
            ]
            for block in engine_result["blocks"]:
                lines.append(f"### 🏪 {block['shop_name']}")
                lines.append("")
                lines.append("| " + " | ".join(block["headers"]) + " |")
                lines.append("| " + " | ".join("---" for _ in block["headers"]) + " |")
                lines.append("| " + " | ".join(block["values"]) + " |")
                lines.append("")
            return "\n".join(lines)

        elif intent == "brand_transaction_count_pivot_view":
            brand_name = resolve_brand_name(params["brand_name"])
            top_n_brands = params.get("top_n_brands", 3)
            other_n_brands = params.get("other_n_brands", 5)
            requested_top_n = params.get("top_n_shops", 10)
            # DISPLAY_CAP: 20 by default, but if user EXPLICITLY asked for
            # more than 20 shown, respect that (up to the hard safety cap).
            DISPLAY_CAP = max(requested_top_n, 20) if requested_top_n > 20 else 20
            # COMPUTE cap: ALWAYS generous (200) regardless of what the
            # parser defaulted to -- otherwise, if the user's query didn't
            # explicitly mention a number, the engine only computes 10
            # rows to begin with, and the "download gets everything" logic
            # has nothing extra to actually download.
            # NO artificial cap -- None means "return every matching shop,
            # however many there are". The dataset itself naturally bounds
            # this (there are only ~1440 shops total in existence here),
            # so there's no real-world scenario where this needs limiting.
            compute_cap = None
            engine_result = engine.brand_transaction_count_pivot_view(
                brand_name,
                target_count=params.get("target_count", 1),
                comparison=params.get("comparison", "equal"),
                top_n_shops=compute_cap,
                top_n_brands=top_n_brands,
                other_n_brands=other_n_brands,
                other_min_pct=params.get("other_min_pct", 1.0),
                name_maxlen=params.get("name_maxlen", 15),
            )
            if not engine_result.get("found"):
                return f"❌ {engine_result.get('message', 'Data nahi mila.')}"

            seg_name = engine_result["brand_segment_name"]
            headers = ["Shop", f"{seg_name} - Sale @ Shop", "Brand - Shop Seg %"]
            for i in range(1, top_n_brands + 1):
                headers.append(f"Top {i}")
            headers.append(f"Total (Top1-{top_n_brands})")
            for i in range(1, other_n_brands + 1):
                headers.append(f"Brand {i}")
            headers.append(f"Total (Brand1-{other_n_brands})")

            def _row_to_cells(row):
                cells = [row["shop"], str(row["segment_sale_at_shop"]), row["brand_query_shop_seg_pct"]]
                for i in range(1, top_n_brands + 1):
                    cells.append(row.get(f"top_{i}", "-"))
                cells.append(row["total_top_n"])
                for i in range(1, other_n_brands + 1):
                    cells.append(row.get(f"brand_{i}", "-"))
                cells.append(row["total_other_n"])
                return cells

            all_rows = engine_result["pivot_rows"]

            # Sort shops by "Total (Top1-N)" % descending -- largest
            # concentration-in-top-brands first. Extracted from the
            # "qty / pct%" string already stored in each row.
            def _extract_pct(qty_pct_str):
                try:
                    return float(qty_pct_str.split('/')[-1].strip().rstrip('%'))
                except (ValueError, IndexError):
                    return 0.0
            all_rows = sorted(all_rows, key=lambda r: _extract_pct(r["total_top_n"]), reverse=True)

            display_rows = all_rows[:DISPLAY_CAP]

            display_headers = ["🏪 Shop", f"📦 {seg_name} - Sale @ Shop", "📦 Brand - Shop Seg %"]
            for i in range(1, top_n_brands + 1):
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "🏅")
                display_headers.append(f"{medal} Top {i}")
            display_headers.append(f"📊 Total (Top1-{top_n_brands})")
            for i in range(1, other_n_brands + 1):
                display_headers.append(f"🔹 Brand {i}")
            display_headers.append(f"📊 Total (Brand1-{other_n_brands})")

            lines = [
                f"**📌 Brand Query Name:** {engine_result['brand_query_name']}",
                "",
                f"**🏷️ Brand Segment Name:** {seg_name}",
                "",
                f"**🔢 Matching Shops (Total):** {engine_result['matching_shops_count']}",
                "",
                f"**👁️ Shops Shown (Screen):** {len(display_rows)}"
                + (f" — ⬇️ poori {len(all_rows)} shops ka data Download button se milega"
                   if len(all_rows) > len(display_rows) else ""),
                "",
                "| " + " | ".join(display_headers) + " |",
                "| " + " | ".join("---" for _ in display_headers) + " |",
            ]
            for row in display_rows:
                lines.append("| " + " | ".join(_row_to_cells(row)) + " |")

            return {
                "__reply__": "\n".join(lines),
                "__download_table__": {
                    "headers": headers,
                    "rows": [_row_to_cells(row) for row in all_rows],
                },
            }

        elif intent == "brand_transaction_count_analysis":
            brand_name = resolve_brand_name(params["brand_name"])
            engine_result = engine.brand_transaction_count_analysis(
                brand_name,
                target_count=params.get("target_count", 1),
                comparison=params.get("comparison", "equal"),
                show_segment_top_brands=params.get("show_segment_top_brands", False),
                top_n_shops=min(params.get("top_n_shops", 10), 2000),  # safety ceiling (effectively open)
                top_n_brands=params.get("top_n_brands", 5),
            )
            if engine_result.get("found"):
                if engine_result.get("rows") is not None:
                    result = {
                        "brand": engine_result["brand"],
                        "matching_shops_count": engine_result["matching_shops_count"],
                        "shops_shown": engine_result["shops_shown"],
                        "top_brands_at_each_shop": engine_result["rows"],
                    }
                elif engine_result.get("shops"):
                    return engine_result["shops"]
                else:
                    result = engine_result
            else:
                result = engine_result

        elif intent == "zero_presence_analysis":
            filter_col = DIMENSIONS.get(params.get("filter_dimension"))
            universe_col = DIMENSIONS.get(params.get("universe_dimension") or "shop_code")
            if not filter_col or not universe_col:
                return "Valid filter_dimension aur universe_dimension chahiye."
            resolved_value = fuzzy_resolve_value(str(params.get("filter_value", "")), filter_col)
            result = engine.zero_presence_analysis(
                filter_col, resolved_value, universe_col,
                show_hero_brand_in_segment=params.get("show_hero_brand_in_segment", False),
            )

        elif intent == "zero_sale_with_top_segment_brands":
            resolved_brand = resolve_brand_name(params["brand_name"])
            result = engine.zero_sale_with_top_segment_brands(
                resolved_brand, top_n=params.get("top_n", 20),
                rank_mode=params.get("rank_mode", "top"),
            )

        elif intent == "segment_month_brand_breakdown":
            primary_dim = DIMENSIONS.get(params.get("primary_dimension", "bd_segment"), COL_BD_SEGMENT)
            primary_value = params.get("primary_value")
            if primary_value:
                primary_value = fuzzy_resolve_value(str(primary_value), primary_dim)
            result = engine.dimension_month_brand_breakdown(
                primary_dim, primary_value=primary_value, top_n_brands=params.get("top_n_brands")
            )

        elif intent == "cross_tab_matrix":
            row_col = DIMENSIONS.get(params.get("row_dimension"))
            col_col = DIMENSIONS.get(params.get("col_dimension"))
            if not row_col or not col_col:
                return "Valid row_dimension aur col_dimension chahiye."
            result = engine.cross_tab_matrix(
                row_col, col_col,
                top_rows=params.get("top_rows", 10),
                top_cols=params.get("top_cols", 8),
            )

        elif intent == "compound_ranking":
            df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
            if df_current is None:
                return "Compound ranking ke liye kam se kam 2 mahino ka data chahiye."
            rank_col = DIMENSIONS.get(params.get("rank_col") or "brand") or COL_BRAND
            engine_result = SmartQueryEngine.compound_ranking(
                df_current, df_previous, rank_col=rank_col,
                top_n=params.get("top_n", 10), min_base=params.get("min_base", 100),
            )
            if engine_result.get("found"):
                engine_result["current_month"] = cur_label
                engine_result["previous_month"] = prev_label
            result = engine_result

        elif intent == "segment_top_brands_with_shop_and_compare":
            compare_brand = params.get("compare_brand")
            if compare_brand:
                compare_brand = resolve_brand_name(compare_brand)
            primary_dim = DIMENSIONS.get(params.get("primary_dimension", "bd_segment"), COL_BD_SEGMENT)
            primary_value = fuzzy_resolve_value(str(params["primary_value"]), primary_dim)
            result = engine.dimension_top_brands_with_shop_and_compare(
                primary_dim, primary_value, top_n=params.get("top_n", 20), compare_brand=compare_brand,
            )

        elif intent == "brand_growth_breakdown":
            df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
            if df_current is None:
                return "Growth breakdown ke liye kam se kam 2 mahino ka data chahiye. Abhi sirf 1 mahina loaded hai."

            breakdown_col_map = {"department": "department", "shop_code": "shop_code", "tse": "salesman_tse"}
            breakdown_by = breakdown_col_map.get(params.get("breakdown_by", "department"), "department")

            # Optional scoping filter -- e.g. "DSIIDC ki top shops" means
            # scope to department=DSIIDC FIRST, then break down by shop.
            extra_filters = {}
            for dim, value in (params.get("filters") or {}).items():
                col = DIMENSIONS.get(dim)
                if col:
                    extra_filters[col] = fuzzy_resolve_value(str(value), col)

            full_result = SmartQueryEngine.brand_growth_breakdown(
                params["brand_name"], df_current, df_previous,
                breakdown_by=breakdown_by, top_n=params.get("top_n", 10),
                extra_filters=extra_filters or None,
            )
            if full_result.get("found"):
                full_result["current_month"] = cur_label
                full_result["previous_month"] = prev_label
            result = full_result

        elif intent == "dimension_mom_check":
            df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
            if df_current is None:
                return "MoM comparison ke liye kam se kam 2 mahino ka data chahiye. Abhi sirf 1 mahina loaded hai."

            dim_col = DIMENSIONS.get(params.get("dimension"))
            if not dim_col:
                return "Valid dimension chahiye (department, shop_code, party, ya tse)."
            resolved_value = fuzzy_resolve_value(str(params.get("value", "")), dim_col)

            # Same default as the generic engine: TSE queries default to
            # Rock and Storm Distilleries' own sales (not the TSE's whole
            # multi-company territory) unless a different company is
            # explicitly given.
            if dim_col == COL_TSE:
                explicit_company = params.get("company")
                scope_company = resolve_company_name(explicit_company) if explicit_company else resolve_company_name(DEFAULT_TSE_COMPANY_SCOPE)
                df_current = df_current[df_current[COL_COMPANY].str.upper() == scope_company.upper()]
                df_previous = df_previous[df_previous[COL_COMPANY].str.upper() == scope_company.upper()]

            full_result = SmartQueryEngine.dimension_mom_check(dim_col, resolved_value, df_current, df_previous)
            if full_result.get("found"):
                full_result["current_month"] = cur_label
                full_result["previous_month"] = prev_label
            result = full_result

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
            }
            if bd_seg_filter:
                # Shown ONCE here (not repeated as a column in every row --
                # it's the same value on every row anyway when filtered).
                result["bd_segment"] = bd_seg_filter
            for section in requested_sections:
                json_key = section_key_map.get(section)
                if json_key:
                    rows = full_result[json_key]
                    if bd_seg_filter:
                        rows = [{k: v for k, v in row.items() if k != "bd_segment"} for row in rows]
                    result[json_key] = rows

        elif intent == "anomaly_detection":
            df_current, df_previous, cur_label, prev_label = get_current_and_previous_month_df()
            if df_current is None:
                return "Anomaly detection ke liye kam se kam 2 mahino ka data chahiye. Abhi sirf 1 mahina loaded hai."

            dim_col = DIMENSIONS.get(params.get("dimension", "brand"), COL_BRAND)
            anomaly_result = SmartQueryEngine.detect_anomalies(
                df_current, df_previous, dimension_col=dim_col,
                z_threshold=params.get("z_threshold", 2.0),
                min_base_qty=params.get("min_base_qty", 50),
            )
            if not anomaly_result.get("found"):
                result = anomaly_result
            else:
                anomalies = anomaly_result["anomalies"]
                # If the user specifically asked for only "spike" or only
                # "drop" anomalies, filter to JUST that type -- otherwise
                # every anomaly (regardless of type) was shown even when
                # the user asked specifically for one direction, which
                # was confusing (e.g. asking for "drops" but seeing a full
                # table of "spike" rows that don't answer the question).
                type_filter = params.get("anomaly_type_filter")
                if type_filter in ("spike", "drop"):
                    anomalies = [a for a in anomalies if a["anomaly_type"] == type_filter]
                result = {
                    "current_month": cur_label,
                    "previous_month": prev_label,
                    "total_items_analyzed": anomaly_result["total_items_analyzed"],
                    "mean_pct_change": anomaly_result["mean_pct_change"],
                    "std_pct_change": anomaly_result["std_pct_change"],
                    "anomalies_found": len(anomalies),
                }
                if anomalies:
                    # Auto-explain the top N anomalies (by |z-score|) --
                    # for each, find WHICH department contributed most to
                    # the change, using the (now-generalized) growth-
                    # breakdown function. N is user-configurable (default
                    # 3), capped at 15 to keep computation/response size
                    # reasonable even if someone asks for "all of them".
                    explain_top_n = min(params.get("explain_top_n", 3), 15)
                    for a in anomalies[:explain_top_n]:
                        try:
                            breakdown = SmartQueryEngine.brand_growth_breakdown(
                                a["item"], df_current, df_previous,
                                breakdown_by="department", top_n=1, dimension_col=dim_col,
                            )
                            if breakdown.get("found") and breakdown["breakdown"]:
                                top_dept = breakdown["breakdown"][0]
                                a["top_contributing_department"] = top_dept["department"]
                                a["top_contributor_change_qty"] = top_dept["change_qty"]
                        except Exception:
                            pass  # explanation is a bonus -- never let it break the main anomaly result
                    result["anomalies"] = anomalies
                elif type_filter:
                    result["note"] = f"Koi '{type_filter}' type ki anomaly nahi mili is period mein."

        elif intent == "brand_ranking":
            result = engine.brand_ranking(params["brand_name"])

        elif intent == "brands_in_bd_segment":
            scope_col = COL_COMPANY if params.get("scope_type") == "company" else COL_BD_SEGMENT
            result = engine.brands_in_bd_segment(
                params["brand_name"], top_n=params.get("top_n", 15), scope_col=scope_col
            )

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


def get_month_scoped_df(month_filter: dict):
    """Returns a df scoped to a single month or a month RANGE (e.g. 'Apr-26
    to Jun-26'), used to make specialized functions (brand_report,
    segment_top_brands_with_shop_and_compare, etc.) respect a custom period
    instead of always using ALL loaded months combined. Returns None if no
    valid scoping was requested (caller should then use the full df)."""
    if not month_filter:
        return None
    start = month_filter.get("start")
    end = month_filter.get("end") or start
    if not start:
        return None

    start_resolved = resolve_month_reference(str(start))
    end_resolved = resolve_month_reference(str(end))
    if not isinstance(start_resolved, str) or not isinstance(end_resolved, str):
        return None
    if start_resolved.startswith("__AMBIGUOUS_MONTH__:") or end_resolved.startswith("__AMBIGUOUS_MONTH__:"):
        return None  # let the normal filter path in run_query surface the ambiguity message instead

    month_dates = pd.to_datetime(df[COL_MONTH], format='%b-%y', errors='coerce')
    start_date = pd.to_datetime(start_resolved, format='%b-%y', errors='coerce')
    end_date = pd.to_datetime(end_resolved, format='%b-%y', errors='coerce')
    if pd.isnull(start_date) or pd.isnull(end_date):
        return None

    return df[(month_dates >= start_date) & (month_dates <= end_date)]


def format_period_label(month_filter: dict) -> str:
    """Turns a month_filter into a human-readable calendar date range, e.g.
    '01 Apr 26 - 30 Apr 26' for a single month, or '01 Apr 26 - 31 May 26'
    for a range -- shown above the table so it's clear WHICH period the
    numbers below actually cover."""
    start = month_filter.get("start")
    end = month_filter.get("end") or start
    start_resolved = resolve_month_reference(str(start))
    end_resolved = resolve_month_reference(str(end))
    if not isinstance(start_resolved, str) or not isinstance(end_resolved, str):
        return ""
    try:
        # NOTE: pd.Period('Apr-26', freq='M') misparses "26" (doesn't treat
        # it as a 2-digit year), so use pd.to_datetime with an EXPLICIT
        # format instead, then find that month's actual last day.
        start_date = pd.to_datetime(start_resolved, format='%b-%y', errors='coerce')
        end_date = pd.to_datetime(end_resolved, format='%b-%y', errors='coerce')
    except (ValueError, TypeError):
        return ""
    if pd.isnull(start_date) or pd.isnull(end_date):
        return ""
    end_of_month = end_date + pd.offsets.MonthEnd(0)
    start_str = start_date.strftime('%d %b %y')
    end_str = end_of_month.strftime('%d %b %y')
    return f"{start_str} - {end_str}"


def _solve_single_query(question: str, history: list = None) -> str:
    """Parses and solves ONE independent question end-to-end, returning
    ready-to-display text -- used for each part of a multi-step/multi-part
    query (e.g. 'Dennis ki May sale aur Royal Ace ki May sale dono batao'
    splits into 2 independent questions, each solved via this function).
    Errors in one part are contained here and don't crash the others."""
    try:
        sub_spec = parse_query_with_claude(question, history=history)
    except Exception as e:
        return f"⚠️ Is part ko samajh nahi paya: {e}"

    if not sub_spec.get("query_understood", True):
        clarification = sub_spec.get("clarification_needed") or "Thoda specific karo."
        return f"🤔 {clarification}"

    sub_working_df = get_month_scoped_df(sub_spec.get("month_filter"))
    try:
        sub_intent = sub_spec.get("intent", "generic")
        if sub_intent == "generic":
            sub_data = run_query(sub_spec, working_df=sub_working_df)
        else:
            sub_data = run_special_intent(sub_intent, sub_spec.get("params") or {}, working_df=sub_working_df)
    except BrandAmbiguityError as e:
        options_str = ", ".join(e.options)
        return f"🤔 '{e.search_term}' se {len(e.options)} alag {e.dimension_label} match hote hain: {options_str}."
    except Exception as e:
        return f"⚠️ Is part mein error aaya: {e}"

    if isinstance(sub_data, dict) and "__reply__" in sub_data:
        sub_data = sub_data["__reply__"]
    return render_data_deterministically(sub_data)


@app.post("/chat")
def chat(request: ChatRequest, http_req: Request):
    client_ip = http_req.client.host if http_req.client else "unknown"
    if _is_rate_limited(client_ip):
        return {"reply": ("⏳ Thoda dheere-dheere! Bahut zyada requests aa rahi hain kam samay mein -- "
                           f"{RATE_LIMIT_WINDOW_SECONDS} second wait karke phir try karo.")}

    if data_loading_status == "loading":
        return {"reply": "⏳ Data abhi Supabase se load ho raha hai, thodi der mein try karo (1-2 minute)."}
    if data_loading_status == "failed" or df.empty:
        return {"reply": "⚠️ Data load nahi ho paya. Backend logs check karo."}

    # Retry once on failure -- LLM parsing isn't 100% deterministic, so the
    # SAME query can occasionally produce malformed JSON or params that
    # crash execution, purely as a transient hiccup. Re-parsing from
    # scratch (not just re-running the same bad params) usually recovers,
    # since a fresh parse attempt often succeeds where the first didn't.
    spec = None
    data = None
    last_error = None
    for attempt in range(2):
        try:
            spec = parse_query_with_claude(request.message, history=request.history)
        except Exception as e:
            last_error = e
            print(f"Query parse failed (attempt {attempt + 1}): {e}")
            continue

        if not spec.get("query_understood", True):
            clarification = spec.get("clarification_needed") or "Sawaal thoda aur specific kar sakte ho?"
            return {"reply": f"🤔 Mujhe yeh sawaal 100% clear nahi hai. {clarification}"}

        # MULTI-STEP: user asked 2+ INDEPENDENT questions in one message
        # (e.g. "Dennis ki May sale aur Royal Ace ki May sale dono batao").
        # Solve each sub-question independently (via _solve_single_query,
        # same logic as a normal single query) and combine the results --
        # one part failing doesn't crash the others.
        if spec.get("is_multi_step") and spec.get("sub_queries"):
            sub_questions = spec["sub_queries"][:5]  # cap to prevent runaway cost
            parts = []
            for i, sq in enumerate(sub_questions, start=1):
                part_text = _solve_single_query(sq, history=request.history)
                parts.append(f"### {i}. {sq}\n\n{part_text}")
            return {"reply": "\n\n---\n\n".join(parts)}

        working_df = get_month_scoped_df(spec.get("month_filter"))
        try:
            intent = spec.get("intent", "generic")
            if intent == "generic":
                data = run_query(spec, working_df=working_df)
            else:
                data = run_special_intent(intent, spec.get("params") or {}, working_df=working_df)
            last_error = None
            break  # success -- stop retrying
        except BrandAmbiguityError as e:
            # Real ambiguity, not a transient failure -- retrying won't
            # help, so respond immediately with the matching options
            # instead of burning a retry attempt or giving a generic error.
            options_str = ", ".join(e.options)
            return {"reply": (f"🤔 '{e.search_term}' se {len(e.options)} alag {e.dimension_label} match hote hain: "
                               f"{options_str}. Konsa specifically chahiye?")}
        except Exception as e:
            last_error = e
            print(f"Query run failed (attempt {attempt + 1}): {e}")
            continue

    if last_error is not None:
        return {"reply": ("🤔 Sawaal samajh nahi paya. Try karo: 'Top TSE April mein', "
                           "'DCCWS department ka top brand', 'May vs April total', 'Dennis ka rank kya hai', etc.")}

    # Some intents need a SMALLER table on-screen (readability) but the
    # FULL matching dataset available for download -- they signal this by
    # returning a special dict instead of a plain string/list/dict. For
    # everything else, generically extract the largest table-shaped field
    # (full, untruncated) so "Download" always has access to ALL matching
    # rows, even though the screen only shows DOWNLOAD_DISPLAY_LIMIT.
    download_table = None
    if isinstance(data, dict) and "__reply__" in data:
        download_table = data.get("__download_table__")
        data = data["__reply__"]
    else:
        download_table = extract_download_table(data)

    # CRITICAL: the table/numbers are built here, in pure Python, from the
    # actual data -- never by asking an LLM to "re-type" or "format" them.
    # An LLM transcribing a table can occasionally alter a digit, which is
    # unacceptable for a business analytics tool (verified this happened:
    # a live query showed 27,837/21,121 when the real Supabase numbers were
    # 31,536/20,081 -- the calculation was correct, but the presentation
    # layer had silently changed the numbers while "formatting" them).
    deterministic_text = render_data_deterministically(data)

    # If a custom period (month or month-range) was applied, show it
    # clearly ABOVE the result -- otherwise it's not obvious to the user
    # WHICH period the numbers below actually cover.
    if working_df is not None and spec.get("month_filter"):
        period_label = format_period_label(spec["month_filter"])
        if period_label:
            deterministic_text = f"📅 **Period:** {period_label}\n\n{deterministic_text}"

    # Claude's ONLY job now is a short 1-2 line insight/comment -- it is
    # explicitly told not to repeat any numbers, since those are already
    # rendered exactly, above.
    try:
        insight_response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=150,
            temperature=0,  # grounding matters here too -- this call was seen
                            # fabricating claims (e.g. "only March data available")
                            # that had ZERO basis in the actual data, especially on
                            # follow-up questions where request.message alone (e.g.
                            # "April ki bhi batao") lacks the full resolved context
                            # (which brand/company, etc.) -- low temperature reduces
                            # this kind of unconstrained invention.
            system=(
                "Tu ek chhota insight-generator hai RSD liquor sales data ke liye. Tumhe neeche "
                "diya gaya data ek observation ke liye dikhaya ja raha hai -- ISE DOBARA MAT LIKHO, "
                "koi table ya number repeat mat karo (woh already user ko dikh chuka hai). Sirf EK "
                "CHHOTA 1-2 line ka Hinglish insight/comment do jo is data se related ho (jaise "
                "'yeh brand apne segment ka leader hai' ya 'yeh decline chinta ka vishay hai'). "
                "Emoji use karo. Agar data mein 'not found' / error ho, kuch mat likho, khaali "
                "string return karo.\n\n"
                "⚠️ CRITICAL -- SIRF neeche diye 'Data' section mein jo dikh raha hai, USI ke baare "
                "mein comment karo. KABHI BHI koi claim mat banao jo Data mein nahi likha hai -- "
                "jaise 'yeh data available nahi hai', 'sirf [X] tak ka data hai', 'system update "
                "chahiye', waghera -- YEH SAB TUMHE NAHI PATA, aur agar Data section mein koi number "
                "successfully dikh raha hai (matlab woh data MAUJOOD hai), to kabhi mat bolo ki woh "
                "available nahi hai. Sawaal ka text (jaise 'April ki bhi batao') THODA incomplete "
                "lag sakta hai kyunki yeh ek FOLLOW-UP question hai (pichle context se continue ho "
                "raha hai) -- is wajah se confused mat ho, sirf Data section ko dekho aur uske "
                "baare mein neutral, factual insight do."
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
    response = {"reply": final_reply}
    if download_table:
        response["download_table"] = download_table
    return response
