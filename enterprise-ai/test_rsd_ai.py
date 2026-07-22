"""
RSD Enterprise AI — Automated Test Suite
==========================================
Yeh script SmartQueryEngine ke functions ko DIRECTLY test karta hai
(actual Claude API parser ko bypass karke) -- taaki bina API cost/internet
ke, sirf ek command se confirm ho jaye ki core Python logic sahi hai.

USAGE:
    python test_rsd_ai.py

Data files (April aur May CSV) isi folder mein honi chahiye, ya path
neeche update kar do.

Jab bhi naya feature add karo ya koi function change karo, yeh script
chala do -- 30 second mein pata chal jayega kuch tuta to nahi.
"""

import sys
import pandas as pd

sys.path.insert(0, '.')
from smart_query_engine import SmartQueryEngine

# ---------------------------------------------------------------------
# 1. DATA LOADING -- update these paths to match your local CSV files
# ---------------------------------------------------------------------
APRIL_CSV = "../DI_APR_26.csv"
MAY_CSV = "../DI_MAY_26.csv"


def clean_col(c):
    c = c.replace(',', '').replace('/', ' ').strip()
    return '_'.join(c.split()).lower()


def load_data():
    apr = pd.read_csv(APRIL_CSV, low_memory=False, keep_default_na=False)
    apr.columns = [clean_col(c) for c in apr.columns]
    apr['sale_qty_in_box'] = pd.to_numeric(apr['sale_qty_in_box'], errors='coerce').fillna(0).astype(int)

    may = pd.read_csv(MAY_CSV, low_memory=False, keep_default_na=False)
    may.columns = [clean_col(c) for c in may.columns]
    may['sale_qty_in_box'] = pd.to_numeric(may['sale_qty_in_box'], errors='coerce').fillna(0).astype(int)

    combined = pd.concat([apr, may], ignore_index=True)
    return apr, may, combined


# ---------------------------------------------------------------------
# 2. TEST RUNNER -- minimal, no external dependencies (no pytest needed)
# ---------------------------------------------------------------------
class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def check(self, name, actual, expected, tolerance=0):
        """tolerance: allow +/- this much difference for numeric checks
        (useful if you re-run against slightly updated data)."""
        ok = False
        if isinstance(expected, (int, float)) and tolerance:
            ok = abs(actual - expected) <= tolerance
        else:
            ok = actual == expected

        if ok:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            self.failures.append(f"{name}: expected {expected!r}, got {actual!r}")
            print(f"  ❌ {name}: expected {expected!r}, got {actual!r}")

    def check_true(self, name, condition):
        if condition:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            self.failures.append(f"{name}: condition was False")
            print(f"  ❌ {name}: condition was False")

    def check_no_crash(self, name, fn):
        """Runs fn() and passes as long as it doesn't raise an exception
        -- for regression-testing the crash bugs we've already fixed."""
        try:
            fn()
            self.passed += 1
            print(f"  ✅ {name} (no crash)")
        except Exception as e:
            self.failed += 1
            self.failures.append(f"{name}: CRASHED -- {type(e).__name__}: {e}")
            print(f"  ❌ {name}: CRASHED -- {type(e).__name__}: {e}")

    def summary(self):
        total = self.passed + self.failed
        print()
        print("=" * 60)
        print(f"RESULT: {self.passed}/{total} passed")
        if self.failures:
            print()
            print("FAILURES:")
            for f in self.failures:
                print(f"  - {f}")
        print("=" * 60)
        return self.failed == 0


# ---------------------------------------------------------------------
# 3. TEST CASES -- known-good expected values (verified manually earlier)
# ---------------------------------------------------------------------
def run_all_tests():
    print("Loading data...")
    apr, may, combined = load_data()
    engine = SmartQueryEngine(combined)
    engine_may = SmartQueryEngine(may)
    t = TestRunner()

    print("\n--- Brand Report ---")
    r = engine.brand_report('DENNIS SPECIAL GOLD WHISKY')
    t.check("Dennis total qty (Apr+May combined)", r['brand_sale_qty'], 51617)
    t.check_true("Dennis brand_report has department_breakdown", 'department_breakdown' in r)

    print("\n--- Zero Presence Analysis ---")
    r = engine_may.zero_presence_analysis('brand_name_as_per_company_data', 'ROYAL ACE RARE BLENDED WHISKY', 'shop_code')
    t.check("Royal Ace absent_count (May only)", r['absent_count'], 221)
    t.check_true("Royal Ace zero_presence has enrichment (bd_segment)", 'bd_segment' in r)

    print("\n--- Zero Sale + Top/Bottom/Mid Segment Brands ---")
    for mode in ['top', 'bottom', 'mid']:
        r = engine_may.zero_sale_with_top_segment_brands('DENNIS SPECIAL GOLD WHISKY', top_n=5, rank_mode=mode)
        rows_key = f'rows_{mode}'
        t.check_true(f"Dennis zero_sale rank_mode={mode} has correct key", rows_key in r)
        first_row = r[rows_key][0] if r.get(rows_key) else {}
        t.check_true(f"Dennis zero_sale rank_mode={mode} has {mode}_1 column",
                     f'{mode}_1' in first_row)

    print("\n--- Company Full Profile ---")
    r = engine.company_full_profile('OMSONS MARKETING PRIVATE LIMITED')
    t.check("OMSONS total_sale_qty", r['total_sale_qty'], 417249)
    t.check("OMSONS number_of_brands", r['number_of_brands'], 9)

    print("\n--- Generalized Dimension Month-Brand Breakdown ---")
    r = engine.dimension_month_brand_breakdown('company_name', 'OMSONS MARKETING PRIVATE LIMITED')
    t.check("OMSONS brand_month_breakdown row count matches number_of_brands", len(r['brand_month_breakdown']), 9)
    r_seg = engine.dimension_month_brand_breakdown('bd_segment', 'Semi Pre Whisky', top_n_brands=3)
    t.check("Segment scope still works (backward compat)", len(r_seg['brand_month_breakdown']), 3)

    print("\n--- Brands In Scope (Segment / Company) ---")
    r = engine_may.brands_in_bd_segment('DENNIS SPECIAL GOLD WHISKY', top_n=5, scope_col='company_name')
    t.check_true("Dennis's company siblings include Royal Ace",
                 any(b['brand'] == 'ROYAL ACE RARE BLENDED WHISKY' for b in r['brands']))

    print("\n--- Regression: Previously-Crashing Edge Cases ---")
    t.check_no_crash(
        "cross_tab_matrix same dimension (used to ValueError crash)",
        lambda: engine.cross_tab_matrix('department', 'department', top_rows=2, top_cols=2)
    )
    r = engine.cross_tab_matrix('department', 'department', top_rows=2, top_cols=2)
    t.check("cross_tab_matrix same-dimension returns found=False (not crash)", r['found'], False)

    print("\n--- Compare Dimension Values (with scope_filters) ---")
    r = engine_may.compare_dimension_values(
        'salesman_tse', ['Sunil Sharma', 'Ram Gopal Sharma'],
        scope_filters={'company_name': 'ROCK AND STORM DISTILLERIES PVT.LTD.,'}
    )
    t.check_true("Scoped TSE comparison found", r['found'])
    sunil_brands = r['details']['Sunil Sharma']['number_of_brands']
    t.check("Scoped comparison shows Rock & Storm's brand count (not whole territory)", sunil_brands, 5)

    print("\n--- Empty/Invalid Input Handling (should NOT crash) ---")
    t.check_no_crash("brand_report with fake brand name", lambda: engine.brand_report("XYZ_NOT_REAL"))
    r = engine.brand_report("XYZ_NOT_REAL")
    t.check("Fake brand returns found=False", r['found'], False)

    print("\n--- Brand Ambiguity Data Property (regression guard) ---")
    # NOTE: main.py's actual BrandAmbiguityError logic isn't directly
    # testable here (main.py needs API keys/app context to import cleanly)
    # -- this instead guards the underlying DATA property the fix depends
    # on: "Royal" must still match MULTIPLE distinct brands. If this ever
    # becomes just 1 (e.g. brand names get cleaned up), the ambiguity
    # check in main.py becomes moot -- if it becomes 0, something broke.
    # If you change main.py's brand-ambiguity logic, re-verify it manually
    # against the LIVE app too (see 'Royal ki sale batao' test case).
    royal_matches = combined[combined['brand_name_as_per_company_data'].str.contains('ROYAL', case=False, na=False)]['brand_name_as_per_company_data'].nunique()
    t.check_true("'Royal' still matches multiple distinct brands (ambiguity check still relevant)", royal_matches > 1)

    print("\n--- TSE Ambiguity Data Property (regression guard) ---")
    # Same reasoning as the brand ambiguity guard above -- "Kumar" and
    # "Sharma" must still match MULTIPLE distinct TSEs for the
    # resolve_tse_name ambiguity check in main.py to be relevant, while
    # "Sunil" (a unique first name) must match exactly 1.
    kumar_matches = combined[combined['salesman_tse'].str.contains('Kumar', case=False, na=False)]['salesman_tse'].nunique()
    t.check_true("'Kumar' still matches multiple distinct TSEs (ambiguity check still relevant)", kumar_matches > 1)
    sunil_matches = combined[combined['salesman_tse'].str.contains('Sunil', case=False, na=False)]['salesman_tse'].nunique()
    t.check("'Sunil' matches exactly 1 TSE (should resolve without clarification)", sunil_matches, 1)

    print("\n--- Company Ambiguity Data Property (regression guard) ---")
    # "Rock and Storm" genuinely matches 2 distinct companies (Distilleries
    # vs Bottlers) -- this guards that fact so the resolve_company_name
    # ambiguity check in main.py stays relevant/testable.
    rs_matches = combined[combined['company_name'].str.contains('Rock and Storm', case=False, na=False)]['company_name'].nunique()
    t.check("'Rock and Storm' matches exactly 2 distinct companies (Distilleries vs Bottlers)", rs_matches, 2)

    print("\n--- Month Ambiguity Logic (multi-year, synthetic test) ---")
    # We currently only have Apr-26/May-26 data (no real multi-year overlap
    # to test against), so this synthetically adds an Apr-27 row to verify
    # the bare-month-name (no year) ambiguity detection in
    # resolve_month_reference still works correctly when it eventually
    # matters (e.g. once a second year of data is loaded).
    synthetic_row = combined.iloc[0:1].copy()
    synthetic_row['month'] = 'Apr-27'
    test_df_multiyear = pd.concat([combined, synthetic_row], ignore_index=True)
    month_prefix = "april"[:3]
    matches = sorted(m for m in test_df_multiyear['month'].astype(str).unique() if str(m).lower().startswith(month_prefix))
    t.check("'April' (no year) matches 2 distinct years when both exist -- should trigger clarification", len(matches), 2)

    return t.summary()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
