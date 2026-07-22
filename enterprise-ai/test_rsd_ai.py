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

Is version mein 3 extra cheezein hain:
1. DATA SANITY CHECKS -- data-loading issues bhi pakड़ta hai (jaise
   ampersand encoding, missing rows), na ki sirf code bugs.
2. PERFORMANCE TIMING -- har test kitna time leta hai, track karta hai.
3. REPORT FILE -- har run ke baad ek timestamped markdown report
   file banata hai (test_report.md) jo business owner ko dikhane layak hai.
"""

import sys
import time
import datetime
import pandas as pd

sys.path.insert(0, '.')
from smart_query_engine import SmartQueryEngine

# ---------------------------------------------------------------------
# 1. DATA LOADING -- update these paths to match your local CSV files
# ---------------------------------------------------------------------
APRIL_CSV = "../DI_APR_26.csv"
MAY_CSV = "../DI_MAY_26.csv"

# Expected data ranges (used by Data Sanity Checks below) -- update these
# if your data legitimately grows/changes (e.g. new month added).
EXPECTED_MIN_TOTAL_ROWS = 250000
EXPECTED_MAX_TOTAL_ROWS = 400000
EXPECTED_MIN_COMPANIES = 60
EXPECTED_MIN_BRANDS = 300
EXPECTED_MIN_SHOPS = 600
EXPECTED_MONTHS = {"Apr-26", "May-26"}


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
#    Now with per-check TIMING and REPORT generation.
# ---------------------------------------------------------------------
class TestRunner:
    SLOW_THRESHOLD_SEC = 1.0  # flag any single check slower than this

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []
        self.timings = []  # list of (name, seconds)
        self.current_section = "General"
        self.section_results = {}  # section -> {"passed": n, "failed": n}
        self.start_time = time.time()

    def section(self, name):
        """Call before a group of related checks -- powers both the
        printed header and the per-section breakdown in the report."""
        print(f"\n--- {name} ---")
        self.current_section = name
        self.section_results.setdefault(name, {"passed": 0, "failed": 0})

    def _record(self, name, ok, detail=""):
        self.section_results[self.current_section]["passed" if ok else "failed"] += 1
        if ok:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            self.failures.append(f"[{self.current_section}] {name}: {detail}")
            print(f"  ❌ {name}: {detail}")

    def _timed(self, name, fn):
        t0 = time.time()
        result = fn()
        elapsed = time.time() - t0
        self.timings.append((f"[{self.current_section}] {name}", elapsed))
        if elapsed > self.SLOW_THRESHOLD_SEC:
            print(f"  ⏱️  SLOW: {name} took {elapsed:.2f}s (threshold: {self.SLOW_THRESHOLD_SEC}s)")
        return result

    def check(self, name, actual, expected, tolerance=0):
        """tolerance: allow +/- this much difference for numeric checks
        (useful if you re-run against slightly updated data)."""
        if isinstance(expected, (int, float)) and tolerance:
            ok = abs(actual - expected) <= tolerance
        else:
            ok = actual == expected
        self._record(name, ok, "" if ok else f"expected {expected!r}, got {actual!r}")

    def check_true(self, name, condition):
        self._record(name, bool(condition), "condition was False")

    def check_no_crash(self, name, fn):
        """Runs fn() (timed) and passes as long as it doesn't raise an
        exception -- for regression-testing the crash bugs we've already
        fixed."""
        try:
            self._timed(name, fn)
            self._record(f"{name} (no crash)", True)
        except Exception as e:
            self._record(f"{name}", False, f"CRASHED -- {type(e).__name__}: {e}")

    def check_timed(self, name, fn, expected=None, tolerance=0):
        """Like check(), but also times the function call fn() and warns
        if it's unexpectedly slow."""
        actual = self._timed(name, fn)
        if expected is not None:
            self.check(name, actual, expected, tolerance)
        return actual

    def summary(self):
        total = self.passed + self.failed
        total_time = time.time() - self.start_time
        print()
        print("=" * 60)
        print(f"RESULT: {self.passed}/{total} passed  (total time: {total_time:.2f}s)")
        if self.failures:
            print()
            print("FAILURES:")
            for f in self.failures:
                print(f"  - {f}")
        slow = [t for t in self.timings if t[1] > self.SLOW_THRESHOLD_SEC]
        if slow:
            print()
            print("SLOW CHECKS (>1s):")
            for name, secs in slow:
                print(f"  - {name}: {secs:.2f}s")
        print("=" * 60)
        return self.failed == 0

    def write_report(self, path="test_report.md"):
        """Generates a timestamped markdown report -- shareable proof of
        system health for business stakeholders, and a historical record
        so you can compare runs over time."""
        total = self.passed + self.failed
        total_time = time.time() - self.start_time
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"# RSD Enterprise AI — Test Report",
            f"",
            f"**Run at:** {now}",
            f"**Result:** {self.passed}/{total} passed ({total_time:.2f}s total)",
            f"**Status:** {'✅ ALL PASS' if self.failed == 0 else f'❌ {self.failed} FAILURE(S)'}",
            f"",
            f"## Section Breakdown",
            f"",
            f"| Section | Passed | Failed |",
            f"|---|---|---|",
        ]
        for sec, counts in self.section_results.items():
            lines.append(f"| {sec} | {counts['passed']} | {counts['failed']} |")

        if self.failures:
            lines += ["", "## Failures", ""]
            for f in self.failures:
                lines.append(f"- {f}")

        slow = [t for t in self.timings if t[1] > self.SLOW_THRESHOLD_SEC]
        if slow:
            lines += ["", "## Slow Checks (>1s)", ""]
            for name, secs in slow:
                lines.append(f"- {name}: {secs:.2f}s")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n📄 Report saved: {path}")


# ---------------------------------------------------------------------
# 3. DATA SANITY CHECKS -- catches DATA-loading issues (bad CSV, dropped
#    rows, encoding bugs like the ampersand issue) -- not just code bugs.
#    This is often MORE valuable than code tests, since in this project
#    data-loading problems (Supabase connection drops, HTML entity
#    encoding) have been at least as common as actual code bugs.
# ---------------------------------------------------------------------
def run_data_sanity_checks(t, apr, may, combined):
    t.section("Data Sanity Checks")

    total_rows = len(combined)
    t.check_true(f"Total row count in expected range ({EXPECTED_MIN_TOTAL_ROWS}-{EXPECTED_MAX_TOTAL_ROWS}, got {total_rows})",
                 EXPECTED_MIN_TOTAL_ROWS <= total_rows <= EXPECTED_MAX_TOTAL_ROWS)

    n_companies = combined['company_name'].nunique()
    t.check_true(f"Company count looks sane (>= {EXPECTED_MIN_COMPANIES}, got {n_companies})",
                 n_companies >= EXPECTED_MIN_COMPANIES)

    n_brands = combined['brand_name_as_per_company_data'].nunique()
    t.check_true(f"Brand count looks sane (>= {EXPECTED_MIN_BRANDS}, got {n_brands})",
                 n_brands >= EXPECTED_MIN_BRANDS)

    n_shops = combined['shop_code'].nunique()
    t.check_true(f"Shop count looks sane (>= {EXPECTED_MIN_SHOPS}, got {n_shops})",
                 n_shops >= EXPECTED_MIN_SHOPS)

    actual_months = set(combined['month'].astype(str).unique())
    t.check_true(f"Expected months present ({EXPECTED_MONTHS})", EXPECTED_MONTHS.issubset(actual_months))

    # Critical columns should have NO nulls/blanks -- if they do, either
    # the CSV export was incomplete or a column got mis-mapped during load.
    for col in ['brand_name_as_per_company_data', 'company_name', 'shop_code', 'bd_segment']:
        blank_count = (combined[col].astype(str).str.strip() == '').sum()
        t.check(f"'{col}' has no blank values (found {blank_count})", blank_count, 0)

    # sale_qty_in_box should never be negative (would indicate a parsing
    # or data-entry error).
    negative_qty_count = (combined['sale_qty_in_box'] < 0).sum()
    t.check(f"No negative sale_qty_in_box values", negative_qty_count, 0)

    # The ampersand-encoding bug we fixed earlier: company/brand names
    # should never contain the literal HTML entity "&amp;" -- if this
    # ever reappears, the html.unescape() step in the loader broke.
    amp_bug_companies = combined['company_name'].astype(str).str.contains('&amp;', case=False, na=False).sum()
    t.check(f"No unescaped '&amp;' HTML entities in company_name (regression guard)", amp_bug_companies, 0)


# ---------------------------------------------------------------------
# 4. FUNCTIONAL TEST CASES -- known-good expected values (verified
#    manually earlier), now timed via check_timed/check_no_crash.
# ---------------------------------------------------------------------
def run_all_tests():
    print("Loading data...")
    apr, may, combined = load_data()
    engine = SmartQueryEngine(combined)
    engine_may = SmartQueryEngine(may)
    t = TestRunner()

    run_data_sanity_checks(t, apr, may, combined)

    t.section("Brand Report")
    r = t.check_timed("brand_report('DENNIS SPECIAL GOLD WHISKY') runs", lambda: engine.brand_report('DENNIS SPECIAL GOLD WHISKY'))
    t.check("Dennis total qty (Apr+May combined)", r['brand_sale_qty'], 51617)
    t.check_true("Dennis brand_report has department_breakdown", 'department_breakdown' in r)

    t.section("Zero Presence Analysis")
    r = t.check_timed(
        "zero_presence_analysis runs",
        lambda: engine_may.zero_presence_analysis('brand_name_as_per_company_data', 'ROYAL ACE RARE BLENDED WHISKY', 'shop_code')
    )
    t.check("Royal Ace absent_count (May only)", r['absent_count'], 221)
    t.check_true("Royal Ace zero_presence has enrichment (bd_segment)", 'bd_segment' in r)

    t.section("Zero Sale + Top/Bottom/Mid Segment Brands")
    for mode in ['top', 'bottom', 'mid']:
        r = t.check_timed(
            f"zero_sale_with_top_segment_brands(rank_mode={mode}) runs",
            lambda m=mode: engine_may.zero_sale_with_top_segment_brands('DENNIS SPECIAL GOLD WHISKY', top_n=5, rank_mode=m)
        )
        rows_key = f'rows_{mode}'
        t.check_true(f"Dennis zero_sale rank_mode={mode} has correct key", rows_key in r)
        first_row = r[rows_key][0] if r.get(rows_key) else {}
        t.check_true(f"Dennis zero_sale rank_mode={mode} has {mode}_1 column", f'{mode}_1' in first_row)

    t.section("Company Full Profile")
    r = t.check_timed("company_full_profile('OMSONS...') runs", lambda: engine.company_full_profile('OMSONS MARKETING PRIVATE LIMITED'))
    t.check("OMSONS total_sale_qty", r['total_sale_qty'], 417249)
    t.check("OMSONS number_of_brands", r['number_of_brands'], 9)

    t.section("Generalized Dimension Month-Brand Breakdown")
    r = t.check_timed(
        "dimension_month_brand_breakdown(company) runs",
        lambda: engine.dimension_month_brand_breakdown('company_name', 'OMSONS MARKETING PRIVATE LIMITED')
    )
    t.check("OMSONS brand_month_breakdown row count matches number_of_brands", len(r['brand_month_breakdown']), 9)
    r_seg = engine.dimension_month_brand_breakdown('bd_segment', 'Semi Pre Whisky', top_n_brands=3)
    t.check("Segment scope still works (backward compat)", len(r_seg['brand_month_breakdown']), 3)

    t.section("Brands In Scope (Segment / Company)")
    r = engine_may.brands_in_bd_segment('DENNIS SPECIAL GOLD WHISKY', top_n=5, scope_col='company_name')
    t.check_true("Dennis's company siblings include Royal Ace",
                 any(b['brand'] == 'ROYAL ACE RARE BLENDED WHISKY' for b in r['brands']))

    t.section("Regression: Previously-Crashing Edge Cases")
    t.check_no_crash(
        "cross_tab_matrix same dimension (used to ValueError crash)",
        lambda: engine.cross_tab_matrix('department', 'department', top_rows=2, top_cols=2)
    )
    r = engine.cross_tab_matrix('department', 'department', top_rows=2, top_cols=2)
    t.check("cross_tab_matrix same-dimension returns found=False (not crash)", r['found'], False)

    t.section("Compare Dimension Values (with scope_filters)")
    r = t.check_timed(
        "compare_dimension_values (scoped) runs",
        lambda: engine_may.compare_dimension_values(
            'salesman_tse', ['Sunil Sharma', 'Ram Gopal Sharma'],
            scope_filters={'company_name': 'ROCK AND STORM DISTILLERIES PVT.LTD.,'}
        )
    )
    t.check_true("Scoped TSE comparison found", r['found'])
    sunil_brands = r['details']['Sunil Sharma']['number_of_brands']
    t.check("Scoped comparison shows Rock & Storm's brand count (not whole territory)", sunil_brands, 5)

    t.section("Empty/Invalid Input Handling (should NOT crash)")
    t.check_no_crash("brand_report with fake brand name", lambda: engine.brand_report("XYZ_NOT_REAL"))
    r = engine.brand_report("XYZ_NOT_REAL")
    t.check("Fake brand returns found=False", r['found'], False)

    t.section("Brand Ambiguity Data Property (regression guard)")
    # NOTE: main.py's actual BrandAmbiguityError logic isn't directly
    # testable here (main.py needs API keys/app context to import cleanly)
    # -- this instead guards the underlying DATA property the fix depends
    # on: "Royal" must still match MULTIPLE distinct brands.
    royal_matches = combined[combined['brand_name_as_per_company_data'].str.contains('ROYAL', case=False, na=False)]['brand_name_as_per_company_data'].nunique()
    t.check_true("'Royal' still matches multiple distinct brands (ambiguity check still relevant)", royal_matches > 1)

    t.section("TSE Ambiguity Data Property (regression guard)")
    kumar_matches = combined[combined['salesman_tse'].str.contains('Kumar', case=False, na=False)]['salesman_tse'].nunique()
    t.check_true("'Kumar' still matches multiple distinct TSEs (ambiguity check still relevant)", kumar_matches > 1)
    sunil_matches = combined[combined['salesman_tse'].str.contains('Sunil', case=False, na=False)]['salesman_tse'].nunique()
    t.check("'Sunil' matches exactly 1 TSE (should resolve without clarification)", sunil_matches, 1)

    t.section("Company Ambiguity Data Property (regression guard)")
    rs_matches = combined[combined['company_name'].str.contains('Rock and Storm', case=False, na=False)]['company_name'].nunique()
    t.check("'Rock and Storm' matches exactly 2 distinct companies (Distilleries vs Bottlers)", rs_matches, 2)

    t.section("Month Ambiguity Logic (multi-year, synthetic test)")
    synthetic_row = combined.iloc[0:1].copy()
    synthetic_row['month'] = 'Apr-27'
    test_df_multiyear = pd.concat([combined, synthetic_row], ignore_index=True)
    month_prefix = "april"[:3]
    matches = sorted(m for m in test_df_multiyear['month'].astype(str).unique() if str(m).lower().startswith(month_prefix))
    t.check("'April' (no year) matches 2 distinct years when both exist -- should trigger clarification", len(matches), 2)

    t.section("Default TSE Company Scope (business rule regression guard)")
    # BUSINESS RULE: TSE queries in main.py default to Rock and Storm
    # Distilleries' own sales (not the TSE's whole multi-company
    # territory), since main.py's _apply_default_tse_company_scope adds
    # this automatically. This guards the underlying DATA property the
    # rule depends on: Sunil Sharma's UNSCOPED total must include brands
    # from OTHER companies too (proving the default is necessary) --
    # if this ever becomes false (e.g. TSEs get split per-company in the
    # data), the default-scoping logic in main.py should be reconsidered.
    sunil_all = combined[combined['salesman_tse'] == 'Sunil Sharma']
    sunil_companies = sunil_all['company_name'].nunique()
    t.check_true(f"Sunil Sharma's unscoped territory spans multiple companies (found {sunil_companies}) -- confirms default-scoping is needed",
                 sunil_companies > 1)
    sunil_rs_only = sunil_all[sunil_all['company_name'] == 'ROCK AND STORM DISTILLERIES PVT.LTD.,']
    sunil_rs_brands = sunil_rs_only['brand_name_as_per_company_data'].nunique()
    t.check("Sunil Sharma's Rock-and-Storm-DISTILLERIES-scoped brand count", sunil_rs_brands, 5)

    success = t.summary()
    t.write_report()
    return success


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
