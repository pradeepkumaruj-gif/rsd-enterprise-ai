"""
RSD Enterprise AI - Smart Query Engine
Backend functions for liquor sales data analysis (Delhi Industry data)

Usage:
    import pandas as pd
    from smart_query_engine import SmartQueryEngine

    df = pd.read_csv('DI_MAY_26.csv')
    engine = SmartQueryEngine(df)

    result = engine.brand_report('DENNIS SPECIAL GOLD WHISKY')
"""

import pandas as pd


class SmartQueryEngine:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.total_market = df['sale_qty_in_box'].sum()

    # ------------------------------------------------------------------
    # a) Brand-specific lookup
    # ------------------------------------------------------------------
    def brand_report(self, brand_name: str, top_shops: int = 10):
        df = self.df
        sub = df[df['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        if sub.empty:
            similar = df[df['brand_name_as_per_company_data'].str.contains(
                brand_name.split()[0], case=False, na=False)]['brand_name_as_per_company_data'].unique()
            return {
                'found': False,
                'message': f'Brand "{brand_name}" not found.',
                'similar_brands': list(similar[:10])
            }

        bd_segment = sub['bd_segment'].unique()
        brand_qty = sub['sale_qty_in_box'].sum()
        bd_total = df[df['bd_segment'].isin(bd_segment)]['sale_qty_in_box'].sum()
        shop_count = sub['shop_code'].nunique()

        shop_sales = (sub.groupby(['shop_code', 'shop_name_as_per_company_data'])['sale_qty_in_box']
                      .sum().sort_values(ascending=False).head(top_shops))

        # Department-wise breakdown: brand's qty AND its market share WITHIN
        # each department (brand_qty_in_dept / total_dept_qty * 100) --
        # combines "department wise sale" + "market share" in one place.
        dept_qty = sub.groupby('department')['sale_qty_in_box'].sum().sort_values(ascending=False)
        dept_totals = df.groupby('department')['sale_qty_in_box'].sum()
        department_breakdown = []
        for dept, qty in dept_qty.items():
            dept_total = dept_totals.get(dept, 0)
            pct = float(round(qty / dept_total * 100, 2)) if dept_total else 0.0
            department_breakdown.append({
                'department': dept,
                'brand_qty': int(qty),
                'department_market_share_pct': pct,
            })

        return {
            'found': True,
            'brand': brand_name,
            'company_name': list(sub['company_name'].unique()),
            'bd_segment': list(bd_segment),
            'bd_segment_total_sale': int(bd_total),
            'brand_sale_qty': int(brand_qty),
            'brand_pct_within_bd_segment': float(round(brand_qty / bd_total * 100, 2)),
            'brand_pct_of_market': float(round(brand_qty / self.total_market * 100, 2)),
            'shops_selling_brand': shop_count,
            'department_breakdown': department_breakdown,
            'top_shops': shop_sales.reset_index().to_dict('records')
        }

    # ------------------------------------------------------------------
    # b) BD Segment + Brand combo query
    # ------------------------------------------------------------------
    def smart_query(self, bd_segment: str, brand_name: str):
        df = self.df
        bd_sub = df[df['bd_segment'].str.upper() == bd_segment.upper()]
        if bd_sub.empty:
            return {'found': False, 'message': f'BD Segment "{bd_segment}" not found.'}

        bd_total = bd_sub['sale_qty_in_box'].sum()
        brand_sub = bd_sub[bd_sub['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        if brand_sub.empty:
            return {'found': False,
                    'message': f'Brand "{brand_name}" not found within BD Segment "{bd_segment}".'}

        brand_qty = brand_sub['sale_qty_in_box'].sum()
        shop_count = brand_sub['shop_code'].nunique()
        total_shops = bd_sub['shop_code'].nunique()

        return {
            'found': True,
            'bd_segment': bd_segment,
            'bd_segment_total_sale': int(bd_total),
            'brand_sale_qty': int(brand_qty),
            'brand_pct_within_bd_segment': float(round(brand_qty / bd_total * 100, 2)),
            'brand_pct_of_market': float(round(brand_qty / self.total_market * 100, 2)),
            'shops_selling_brand': shop_count,
            'total_shops_in_segment': total_shops,
            'brand_presence_pct': round(shop_count / total_shops * 100, 2)
        }

    # ------------------------------------------------------------------
    # c) Market share by any dimension
    # ------------------------------------------------------------------
    def market_share(self, dimension: str, top_n: int = 10):
        valid_dims = ['company_name', 'liquor_type', 'bd_segment',
                      'department', 'salesman_tse']
        if dimension not in valid_dims:
            return {'found': False, 'message': f'Invalid dimension. Choose from {valid_dims}'}

        share = (self.df.groupby(dimension)['sale_qty_in_box'].sum()
                 .sort_values(ascending=False))
        share_pct = (share / self.total_market * 100).round(2)

        return {
            'found': True,
            'dimension': dimension,
            'total_market': int(self.total_market),
            'ranking': {k: float(v) for k, v in share_pct.head(top_n).to_dict().items()},
            'top_n_combined_share': float(round(share_pct.head(top_n).sum(), 2))
        }

    # ------------------------------------------------------------------
    # d) Shop-wise comparison: target brand vs top competitors
    # ------------------------------------------------------------------
    def shop_comparison(self, brand_name: str, top_n: int = 10):
        df = self.df
        seg_val = df[df['brand_name_as_per_company_data'].str.upper() ==
                     brand_name.upper()]['bd_segment'].unique()
        if len(seg_val) == 0:
            return {'found': False, 'message': f'Brand "{brand_name}" not found.'}

        same_seg = df[df['bd_segment'].isin(seg_val)]
        other_brands = same_seg[same_seg['brand_name_as_per_company_data'].str.upper()
                                 != brand_name.upper()]
        top_competitors = (other_brands.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                            .sum().sort_values(ascending=False).head(top_n).index.tolist())

        all_brands = [brand_name] + top_competitors
        pivot = same_seg[same_seg['brand_name_as_per_company_data'].isin(all_brands)].pivot_table(
            index=['shop_code', 'shop_name_as_per_company_data'],
            columns='brand_name_as_per_company_data',
            values='sale_qty_in_box', aggfunc='sum', fill_value=0
        )
        pivot = pivot[all_brands].sort_values(brand_name, ascending=False).reset_index()
        pivot.insert(0, 'Rank', range(1, len(pivot) + 1))

        return {
            'found': True,
            'brand': brand_name,
            'bd_segment': list(seg_val),
            'top_competitors': top_competitors,
            'total_shops': len(pivot),
            'table': pivot.head(20).to_dict('records')  # top 20 shops for display
        }

    # ------------------------------------------------------------------
    # e) Leading (>=threshold%) or long-tail (<threshold%) brands
    #    Fixed to use ONLY "BD Segment" as the category dimension.
    # ------------------------------------------------------------------
    def brand_share_filter(self, bd_segment: str, threshold: float = 5.0, mode: str = 'above'):
        df = self.df
        category_type = 'bd_segment'

        sub = df[df[category_type].str.upper() == bd_segment.upper()]
        if sub.empty:
            return {'found': False, 'message': f'{category_type} "{bd_segment}" not found.'}

        cat_total = sub['sale_qty_in_box'].sum()
        brand_pct = (sub.groupby('brand_name_as_per_company_data')['sale_qty_in_box'].sum()
                     / cat_total * 100).round(2).sort_values(ascending=False)

        result = brand_pct[brand_pct >= threshold] if mode == 'above' else brand_pct[brand_pct < threshold]

        return {
            'found': True,
            'category_type': category_type,
            'category_value': bd_segment,
            'category_total_sale': int(cat_total),
            'mode': mode,
            'threshold': threshold,
            'brands': {k: float(v) for k, v in result.to_dict().items()},
            'count': len(result),
            'combined_share': float(round(result.sum(), 2)),
            'total_brands_in_category': len(brand_pct)
        }

    # ------------------------------------------------------------------
    # j) Single-brand Month-over-Month check
    #    User enters ANY brand name -> tells current vs previous month
    #    sale, and flags clearly if it's a brand-new entry (wasn't sold
    #    in the previous month at all).
    # ------------------------------------------------------------------
    @staticmethod
    def brand_mom_check(brand_name: str, df_current: pd.DataFrame, df_previous: pd.DataFrame):
        cur_sub = df_current[df_current['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        prev_sub = df_previous[df_previous['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]

        if cur_sub.empty and prev_sub.empty:
            return {'found': False, 'message': f'Brand "{brand_name}" not found in either month.'}

        current_qty = int(cur_sub['sale_qty_in_box'].sum())
        previous_qty = int(prev_sub['sale_qty_in_box'].sum())
        change_qty = current_qty - previous_qty

        is_new_entry = (previous_qty == 0 and current_qty > 0)
        is_dropped = (current_qty == 0 and previous_qty > 0)

        pct_change = None
        if previous_qty > 0:
            pct_change = float(round((change_qty / previous_qty) * 100, 2))

        bd_segment = list(cur_sub['bd_segment'].unique()) if not cur_sub.empty else list(prev_sub['bd_segment'].unique())

        return {
            'found': True,
            'brand': brand_name,
            'bd_segment': bd_segment,
            'current_month_qty': current_qty,
            'previous_month_qty': previous_qty,
            'change_qty': change_qty,
            'pct_change': pct_change,
            'is_new_entry': is_new_entry,
            'is_dropped': is_dropped
        }


    # ------------------------------------------------------------------
    # f) Compare multiple brands side-by-side (2 to 10 brands)
    # ------------------------------------------------------------------
    def compare_brands(self, brands: list, max_brands: int = 10):
        if len(brands) < 2:
            return {'found': False, 'message': 'Please provide at least 2 brands to compare.'}
        if len(brands) > max_brands:
            return {'found': False,
                    'message': f'Maximum {max_brands} brands allowed for comparison. You gave {len(brands)}.'}

        result = {}
        for brand in brands:
            sub = self.df[self.df['brand_name_as_per_company_data'].str.upper() == brand.upper()]
            if sub.empty:
                result[brand] = {'found': False, 'message': f'Brand "{brand}" not found.'}
                continue
            canonical_name = sub['brand_name_as_per_company_data'].iloc[0]
            bd_seg = sub['bd_segment'].unique()
            bd_total = self.df[self.df['bd_segment'].isin(bd_seg)]['sale_qty_in_box'].sum()
            qty = sub['sale_qty_in_box'].sum()
            overall_rank_series = (self.df.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                                    .sum().sort_values(ascending=False))
            overall_rank = int(overall_rank_series.index.get_loc(canonical_name) + 1)

            result[brand] = {
                'found': True,
                'company': list(sub['company_name'].unique()),
                'bd_segment': list(bd_seg),
                'sale_qty': int(qty),
                'pct_within_bd_segment': float(round(qty / bd_total * 100, 2)),
                'pct_of_market': float(round(qty / self.total_market * 100, 2)),
                'shops_selling': int(sub['shop_code'].nunique()),
                'overall_rank': overall_rank
            }

        # Ranked summary table (only brands that were found), sorted by sale_qty
        found_brands = {b: v for b, v in result.items() if v.get('found')}
        ranking = sorted(found_brands.items(), key=lambda x: x[1]['sale_qty'], reverse=True)
        summary_table = [
            {'rank': i + 1, 'brand': b, **{k: v for k, v in data.items() if k != 'found'}}
            for i, (b, data) in enumerate(ranking)
        ]

        return {
            'found': True,
            'brands_compared': len(brands),
            'details': result,
            'summary_table': summary_table
        }

    # ------------------------------------------------------------------
    # g) Cross-reference: Brand A's top shops -> check Brand B's sale there
    # ------------------------------------------------------------------
    def cross_reference_shops(self, primary_brand: str, secondary_brand: str, top_n: int = 10):
        df = self.df
        primary_sub = df[df['brand_name_as_per_company_data'].str.upper() == primary_brand.upper()]
        if primary_sub.empty:
            return {'found': False, 'message': f'Brand "{primary_brand}" not found.'}

        top_shops = (primary_sub.groupby(['shop_code', 'shop_name_as_per_company_data'])['sale_qty_in_box']
                     .sum().sort_values(ascending=False).head(top_n))
        top_shop_codes = top_shops.reset_index()['shop_code'].tolist()

        secondary_sub = df[(df['brand_name_as_per_company_data'].str.upper() == secondary_brand.upper()) &
                            (df['shop_code'].isin(top_shop_codes))]
        secondary_by_shop = secondary_sub.groupby('shop_code')['sale_qty_in_box'].sum()

        table = top_shops.reset_index()
        table.columns = ['shop_code', 'Shop Name', f'{primary_brand} Qty']
        table[f'{secondary_brand} Qty'] = table['shop_code'].map(secondary_by_shop).fillna(0).astype(int)
        table.insert(0, 'Rank', range(1, len(table) + 1))

        zero_gap_shops = table[table[f'{secondary_brand} Qty'] == 0]

        return {
            'found': True,
            'primary_brand': primary_brand,
            'secondary_brand': secondary_brand,
            'table': table.to_dict('records'),
            'gap_shops_count': len(zero_gap_shops),
            'gap_shops': zero_gap_shops['Shop Name'].tolist()
        }

    # ------------------------------------------------------------------
    # h) Month-over-Month Gainers & Losers (Segment-wise, Brand-wise)
    #    NOTE: needs a second month's dataframe (e.g. April data) to run.
    #    Static method so it can be called as:
    #        SmartQueryEngine.mom_gainers_losers(df_current, df_previous, ...)
    # ------------------------------------------------------------------
    @staticmethod
    def mom_gainers_losers(df_current: pd.DataFrame, df_previous: pd.DataFrame,
                            group_col: str = 'bd_segment', min_base: int = 500, top_n: int = 10):
        """
        Compares brand-wise sale within each value of group_col (bd_segment)
        between current month and previous month, and returns
        top gainers and top losers by % change.

        group_col: 'bd_segment' (only supported grouping)
        min_base: minimum previous-month qty required for a brand to be
                  considered in gainers/losers ranking. This avoids misleading
                  swings from tiny-volume brands (e.g. 1 box -> 5 box = 400%).
                  New entries and dropped brands are still returned separately,
                  regardless of min_base.
        """
        cur = (df_current.groupby([group_col, 'brand_name_as_per_company_data'])['sale_qty_in_box']
               .sum().reset_index().rename(columns={'sale_qty_in_box': 'current_qty'}))
        prev = (df_previous.groupby([group_col, 'brand_name_as_per_company_data'])['sale_qty_in_box']
                .sum().reset_index().rename(columns={'sale_qty_in_box': 'previous_qty'}))

        merged = pd.merge(cur, prev, on=[group_col, 'brand_name_as_per_company_data'], how='outer').fillna(0)
        merged['current_qty'] = merged['current_qty'].astype(int)
        merged['previous_qty'] = merged['previous_qty'].astype(int)
        merged['change_qty'] = merged['current_qty'] - merged['previous_qty']

        def pct_change(row):
            if row['previous_qty'] == 0:
                return None  # new entry, % change undefined
            return round((row['change_qty'] / row['previous_qty']) * 100, 2)

        merged['pct_change'] = merged.apply(pct_change, axis=1)

        # Only brands with a meaningful previous-month base are ranked as
        # gainers/losers, to avoid noise from tiny-volume swings.
        meaningful = merged[(merged['pct_change'].notna()) & (merged['previous_qty'] >= min_base)]

        gainers = meaningful.sort_values('pct_change', ascending=False).head(top_n)
        losers = meaningful.sort_values('pct_change', ascending=True).head(top_n)
        new_entries = merged[merged['previous_qty'] == 0].sort_values('current_qty', ascending=False).head(top_n)
        dropped = merged[merged['current_qty'] == 0].sort_values('previous_qty', ascending=False).head(top_n)

        return {
            'group_col': group_col,
            'min_base_used': min_base,
            'top_gainers': gainers.to_dict('records'),
            'top_losers': losers.to_dict('records'),
            'new_entries': new_entries.to_dict('records'),
            'dropped_brands': dropped.to_dict('records')
        }

    # ------------------------------------------------------------------
    # i) Brand Ranking — rank at BD Segment, Segment, and Overall Market level
    # ------------------------------------------------------------------
    def brand_ranking(self, brand_name: str):
        df = self.df
        sub = df[df['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        if sub.empty:
            return {'found': False, 'message': f'Brand "{brand_name}" not found.'}

        # IMPORTANT: use the actual database spelling/casing from here on, not
        # the user's raw input -- .index.get_loc() needs an exact match, and
        # a user typing "dennis" instead of "DENNIS SPECIAL GOLD WHISKY"
        # would otherwise raise KeyError.
        canonical_name = sub['brand_name_as_per_company_data'].iloc[0]

        bd_segment = sub['bd_segment'].unique()
        brand_qty = sub['sale_qty_in_box'].sum()

        bd_sub = df[df['bd_segment'].isin(bd_segment)]
        bd_rank_series = bd_sub.groupby('brand_name_as_per_company_data')['sale_qty_in_box'].sum().sort_values(ascending=False)
        bd_rank = int(bd_rank_series.index.get_loc(canonical_name) + 1)
        bd_total_brands = len(bd_rank_series)

        overall_rank_series = df.groupby('brand_name_as_per_company_data')['sale_qty_in_box'].sum().sort_values(ascending=False)
        overall_rank = int(overall_rank_series.index.get_loc(canonical_name) + 1)
        overall_total_brands = len(overall_rank_series)

        return {
            'found': True,
            'brand': brand_name,
            'sale_qty': int(brand_qty),
            'bd_segment': list(bd_segment),
            'rank_within_bd_segment': bd_rank,
            'total_brands_in_bd_segment': bd_total_brands,
            'percentile_in_bd_segment': float(round((1 - (bd_rank - 1) / bd_total_brands) * 100, 1)),
            'overall_market_rank': overall_rank,
            'total_brands_overall': overall_total_brands,
            'percentile_overall': float(round((1 - (overall_rank - 1) / overall_total_brands) * 100, 1))
        }

    # ------------------------------------------------------------------
    # k) List ALL brands within the same bd_segment as a given brand
    #    (e.g. "Royal Ace ke segment mein baaki brands kaunse hain")
    # ------------------------------------------------------------------
    def brands_in_bd_segment(self, brand_name: str, top_n: int = 15):
        df = self.df
        sub = df[df['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        if sub.empty:
            return {'found': False, 'message': f'Brand "{brand_name}" not found.'}

        bd_seg = sub['bd_segment'].unique()
        same_seg = df[df['bd_segment'].isin(bd_seg)]

        ranking = (same_seg.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                   .sum().sort_values(ascending=False))
        seg_total = ranking.sum()

        rows = []
        for rank, (brand, qty) in enumerate(ranking.head(top_n).items(), start=1):
            rows.append({
                'rank': rank,
                'brand': brand,
                'sale_qty': int(qty),
                'pct_within_bd_segment': float(round(qty / seg_total * 100, 2)),
                'is_queried_brand': brand.upper() == brand_name.upper(),
            })

        return {
            'found': True,
            'brand_queried': brand_name,
            'bd_segment': list(bd_seg),
            'total_brands_in_bd_segment': len(ranking),
            'bd_segment_total_sale': int(seg_total),
            'brands': rows,
        }

    # ------------------------------------------------------------------
    # l) Company-wide report: total sale across ALL brands under a company
    #    (e.g. "Dennis brand ki company ki total sale kya hai" needs to
    #    resolve Dennis -> its manufacturer -> sum across ALL that
    #    manufacturer's brands, not just the one brand asked about)
    # ------------------------------------------------------------------
    def company_report(self, company_name: str, top_brands: int = 10):
        df = self.df
        sub = df[df['company_name'].str.upper() == company_name.upper()]
        if sub.empty:
            similar = df[df['company_name'].str.contains(
                company_name.split()[0], case=False, na=False)]['company_name'].unique()
            return {
                'found': False,
                'message': f'Company "{company_name}" not found.',
                'similar_companies': list(similar[:10])
            }

        total_qty = int(sub['sale_qty_in_box'].sum())
        pct_of_market = float(round(total_qty / self.total_market * 100, 2))
        brand_breakdown = (sub.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                            .sum().sort_values(ascending=False))
        bd_segments = list(sub['bd_segment'].unique())

        return {
            'found': True,
            'company': company_name,
            'total_sale_qty': total_qty,
            'pct_of_market': pct_of_market,
            'bd_segments_covered': bd_segments,
            'total_brands_under_company': len(brand_breakdown),
            'top_brands': [
                {'brand': b, 'sale_qty': int(q)} for b, q in brand_breakdown.head(top_brands).items()
            ],
        }

    # ------------------------------------------------------------------
    # m) Full company comparison profile -- metrics 1,2,3,4,5,6,7,8,10
    #    (metric 9, month-over-month, is handled separately via
    #    company_mom_check below since it needs two months' dataframes)
    # ------------------------------------------------------------------
    def company_full_profile(self, company_name: str):
        df = self.df
        sub = df[df['company_name'].str.upper() == company_name.upper()]
        if sub.empty:
            similar = df[df['company_name'].str.contains(
                company_name.split()[0], case=False, na=False)]['company_name'].unique()
            return {
                'found': False,
                'message': f'Company "{company_name}" not found.',
                'similar_companies': list(similar[:10])
            }

        canonical_name = sub['company_name'].iloc[0]
        total_qty = int(sub['sale_qty_in_box'].sum())

        # 2. Overall Market Share %
        market_share_pct = float(round(total_qty / self.total_market * 100, 2))

        # 3. Overall Rank
        overall_rank_series = df.groupby('company_name')['sale_qty_in_box'].sum().sort_values(ascending=False)
        overall_rank = int(overall_rank_series.index.get_loc(canonical_name) + 1)
        total_companies = len(overall_rank_series)

        # 4. Number of Brands
        num_brands = int(sub['brand_name_as_per_company_data'].nunique())

        # 5. Number of BD Segments Present
        num_bd_segments = int(sub['bd_segment'].nunique())

        # 6. Top Brand (Hero SKU) + % contribution
        brand_breakdown = sub.groupby('brand_name_as_per_company_data')['sale_qty_in_box'].sum().sort_values(ascending=False)
        top_brand = brand_breakdown.index[0]
        top_brand_qty = int(brand_breakdown.iloc[0])
        top_brand_pct_of_company = float(round(top_brand_qty / total_qty * 100, 2)) if total_qty else 0.0

        # 7. Shops Covered
        shops_covered = int(sub['shop_code'].nunique())

        # 8. Avg Sale per Shop
        avg_sale_per_shop = float(round(total_qty / shops_covered, 2)) if shops_covered else 0.0

        # 10. Department-wise Presence (strongest department)
        dept_breakdown = sub.groupby('department')['sale_qty_in_box'].sum().sort_values(ascending=False)
        top_department = dept_breakdown.index[0] if len(dept_breakdown) else None
        top_department_qty = int(dept_breakdown.iloc[0]) if len(dept_breakdown) else 0

        return {
            'found': True,
            'company': canonical_name,
            'total_sale_qty': total_qty,
            'overall_market_share_pct': market_share_pct,
            'overall_rank': overall_rank,
            'total_companies': total_companies,
            'number_of_brands': num_brands,
            'number_of_bd_segments': num_bd_segments,
            'top_brand': top_brand,
            'top_brand_qty': top_brand_qty,
            'top_brand_pct_of_company': top_brand_pct_of_company,
            'shops_covered': shops_covered,
            'avg_sale_per_shop': avg_sale_per_shop,
            'top_department': top_department,
            'top_department_qty': top_department_qty,
        }

    # ------------------------------------------------------------------
    # n) Company month-over-month check -- metric 9
    # ------------------------------------------------------------------
    @staticmethod
    def company_mom_check(company_name: str, df_current, df_previous):
        cur = df_current[df_current['company_name'].str.upper() == company_name.upper()]
        prev = df_previous[df_previous['company_name'].str.upper() == company_name.upper()]

        if cur.empty and prev.empty:
            return {'found': False, 'message': f'Company "{company_name}" not found in either month.'}

        cur_qty = int(cur['sale_qty_in_box'].sum())
        prev_qty = int(prev['sale_qty_in_box'].sum())
        change_qty = cur_qty - prev_qty
        pct_change = float(round(change_qty / prev_qty * 100, 2)) if prev_qty else None

        return {
            'found': True,
            'company': company_name,
            'current_month_qty': cur_qty,
            'previous_month_qty': prev_qty,
            'change_qty': change_qty,
            'pct_change': pct_change,
            'is_new_entry': bool(prev_qty == 0 and cur_qty > 0),
            'is_dropped': bool(cur_qty == 0 and prev_qty > 0),
        }

    # ------------------------------------------------------------------
    # q) GENERIC month-over-month check -- works for ANY dimension value
    #    (department, shop_code, salesman_tse, etc.), not just brand/
    #    company. E.g. "DCCWS department ka growth kitna hai" -- total
    #    sale of that department (all brands combined), current vs
    #    previous month.
    # ------------------------------------------------------------------
    @staticmethod
    def dimension_mom_check(column: str, value: str, df_current, df_previous):
        cur = df_current[df_current[column].astype(str).str.upper() == str(value).upper()]
        prev = df_previous[df_previous[column].astype(str).str.upper() == str(value).upper()]

        if cur.empty and prev.empty:
            return {'found': False, 'message': f'"{value}" not found in either month.'}

        cur_qty = int(cur['sale_qty_in_box'].sum())
        prev_qty = int(prev['sale_qty_in_box'].sum())
        change_qty = cur_qty - prev_qty
        pct_change = float(round(change_qty / prev_qty * 100, 2)) if prev_qty else None

        return {
            'found': True,
            'value': value,
            'current_month_qty': cur_qty,
            'previous_month_qty': prev_qty,
            'change_qty': change_qty,
            'pct_change': pct_change,
            'is_new_entry': bool(prev_qty == 0 and cur_qty > 0),
            'is_dropped': bool(cur_qty == 0 and prev_qty > 0),
        }

    # ------------------------------------------------------------------
    # r) GENERIC profile for any dimension value (department, shop, TSE) --
    #    same idea as company_full_profile but works for any column.
    # ------------------------------------------------------------------
    def dimension_full_profile(self, column: str, value: str):
        df = self.df
        sub = df[df[column].astype(str).str.upper() == str(value).upper()]
        if sub.empty:
            return {'found': False, 'message': f'"{value}" not found.'}

        canonical_value = sub[column].iloc[0]
        total_qty = int(sub['sale_qty_in_box'].sum())
        market_share_pct = float(round(total_qty / self.total_market * 100, 2))

        overall_rank_series = df.groupby(column)['sale_qty_in_box'].sum().sort_values(ascending=False)
        overall_rank = int(overall_rank_series.index.get_loc(canonical_value) + 1)
        total_count = len(overall_rank_series)

        num_brands = int(sub['brand_name_as_per_company_data'].nunique())

        brand_breakdown = sub.groupby('brand_name_as_per_company_data')['sale_qty_in_box'].sum().sort_values(ascending=False)
        top_brand = brand_breakdown.index[0]
        top_brand_qty = int(brand_breakdown.iloc[0])
        top_brand_pct = float(round(top_brand_qty / total_qty * 100, 2)) if total_qty else 0.0

        return {
            'found': True,
            'value': canonical_value,
            'total_sale_qty': total_qty,
            'market_share_pct': market_share_pct,
            'overall_rank': overall_rank,
            'total_count': total_count,
            'number_of_brands': num_brands,
            'top_brand': top_brand,
            'top_brand_qty': top_brand_qty,
            'top_brand_pct': top_brand_pct,
        }

    # ------------------------------------------------------------------
    # s) Compare 2-10 values of the SAME dimension (department vs
    #    department, shop vs shop, TSE vs TSE) -- reuses
    #    dimension_full_profile for each value.
    # ------------------------------------------------------------------
    def compare_dimension_values(self, column: str, values: list, max_values: int = 10):
        if len(values) < 2:
            return {'found': False, 'message': 'Please provide at least 2 values to compare.'}
        if len(values) > max_values:
            return {'found': False,
                    'message': f'Maximum {max_values} values allowed. You gave {len(values)}.'}

        details = {v: self.dimension_full_profile(column, v) for v in values}
        return {'found': True, 'values_compared': len(values), 'details': details}

    # ------------------------------------------------------------------
    # o) Compare 2-10 companies side by side (reuses company_full_profile's
    #    metrics for each company)
    # ------------------------------------------------------------------
    def compare_companies(self, companies: list, max_companies: int = 10):
        if len(companies) < 2:
            return {'found': False, 'message': 'Please provide at least 2 companies to compare.'}
        if len(companies) > max_companies:
            return {'found': False,
                    'message': f'Maximum {max_companies} companies allowed. You gave {len(companies)}.'}

        details = {company: self.company_full_profile(company) for company in companies}
        return {'found': True, 'companies_compared': len(companies), 'details': details}

    # ------------------------------------------------------------------
    # u) UNIVERSAL dimension breakdown report -- the "Excel filter" style
    #    tool: take ANY dimension + value as the primary filter (segment,
    #    department, company, shop, liquor_type, pack_size...), and get a
    #    breakdown by ANY OTHER dimension, with %-of-market AND
    #    %-within-the-primary-filter for every breakdown row. This single
    #    function covers "Premium Whisky segment's overall share + its top
    #    5 brands with their share", "DCCWS department's top TSEs",
    #    "Company X's top shops", etc. -- any primary+breakdown combination,
    #    without needing a dedicated function per combination.
    # ------------------------------------------------------------------
    def dimension_breakdown_report(self, primary_filters: dict, breakdown_col: str, top_n: int = 5):
        """primary_filters: dict of {column: value} -- can be ONE filter or
        MULTIPLE filters combined (like Excel's AutoFilter on several
        columns at once), e.g. {'bd_segment': 'Premium Whisky',
        'department': 'DCCWS'} filters BOTH simultaneously before doing
        the breakdown."""
        df = self.df
        filtered = df
        canonical_filters = {}
        for col, value in primary_filters.items():
            match_mask = filtered[col].astype(str).str.upper() == str(value).upper()
            if not match_mask.any():
                return {'found': False, 'message': f'"{value}" not found in {col}.'}
            canonical_filters[col] = filtered.loc[match_mask, col].iloc[0]
            filtered = filtered[match_mask]

        if filtered.empty:
            return {'found': False, 'message': 'Is filter combination ke liye koi data nahi mila.'}

        primary_total_qty = int(filtered['sale_qty_in_box'].sum())
        primary_pct_of_market = float(round(primary_total_qty / self.total_market * 100, 2))

        breakdown_qty = (filtered.groupby(breakdown_col)['sale_qty_in_box']
                          .sum().sort_values(ascending=False).head(top_n))

        breakdown_rows = []
        for item, qty in breakdown_qty.items():
            qty = int(qty)
            breakdown_rows.append({
                'item': item,
                'qty': qty,
                'pct_within_primary': float(round(qty / primary_total_qty * 100, 2)) if primary_total_qty else 0.0,
                'pct_of_overall_market': float(round(qty / self.total_market * 100, 2)),
            })

        return {
            'found': True,
            'filters_applied': canonical_filters,
            'breakdown_dimension': breakdown_col,
            'primary_total_qty': primary_total_qty,
            'primary_pct_of_overall_market': primary_pct_of_market,
            'breakdown': breakdown_rows,
        }

    # ------------------------------------------------------------------
    # z) Transaction-count analysis -- shops where a brand appeared in
    #    EXACTLY N transactions (rows), not N boxes. E.g. "Royal Ace sold
    #    only ONCE at this shop, never again" -- a completely different
    #    concept from sale QUANTITY, which every other function tracks.
    # ------------------------------------------------------------------
    def brand_transaction_count_analysis(self, brand_name: str, target_count: int = 1,
                                          comparison: str = 'equal', show_segment_top_brands: bool = False,
                                          top_n_shops: int = 10, top_n_brands: int = 5):
        df = self.df
        sub = df[df['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        if sub.empty:
            return {'found': False, 'message': f'Brand "{brand_name}" not found.'}

        txn_counts = sub.groupby(['shop_code', 'shop_name_as_per_company_data']).size()

        if comparison == 'less_equal':
            matched = txn_counts[txn_counts <= target_count]
        elif comparison == 'greater_equal':
            matched = txn_counts[txn_counts >= target_count]
        else:
            matched = txn_counts[txn_counts == target_count]

        total_matching = len(matched)

        if show_segment_top_brands:
            # For each (capped) matching shop, show the top N brands within
            # the SAME bd_segment as brand_name -- answers "at these
            # one-time shops, who's actually winning this category?"
            own_bd_segment = sub['bd_segment'].unique()
            segment_df = df[df['bd_segment'].isin(own_bd_segment)]
            rows = []
            for (shop_code, shop_name), count in list(matched.items())[:top_n_shops]:
                brand_qty = int(sub[sub['shop_code'] == shop_code]['sale_qty_in_box'].sum())
                shop_segment_df = segment_df[segment_df['shop_code'] == shop_code]
                top_here = (shop_segment_df.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                            .sum().sort_values(ascending=False).head(top_n_brands))
                for rank, (other_brand, other_qty) in enumerate(top_here.items(), start=1):
                    rows.append({
                        'shop_code': shop_code,
                        'shop_name': shop_name,
                        'transaction_count': int(count),
                        f'{brand_name}_qty': brand_qty,
                        'rank_in_segment': rank,
                        'top_brand_here': other_brand,
                        'top_brand_qty': int(other_qty),
                    })
            return {
                'found': True,
                'brand': brand_name,
                'target_transaction_count': target_count,
                'comparison': comparison,
                'matching_shops_count': total_matching,
                'shops_shown': total_matching if top_n_shops is None else min(top_n_shops, total_matching),
                'rows': rows,
            }

        rows = []
        for (shop_code, shop_name), count in matched.items():
            shop_txns = sub[sub['shop_code'] == shop_code]
            rows.append({
                'shop_code': shop_code,
                'shop_name': shop_name,
                'transaction_count': int(count),
                'total_qty': int(shop_txns['sale_qty_in_box'].sum()),
                'months': ', '.join(sorted(shop_txns['month'].unique())),
            })

        return {
            'found': True,
            'brand': brand_name,
            'target_transaction_count': target_count,
            'comparison': comparison,
            'matching_shops_count': len(rows),
            'shops': rows[:50],  # cap for readable display
        }

    # ------------------------------------------------------------------
    # aa) Pivot-style view: for shops matching a transaction-count filter,
    #    ONE ROW PER SHOP, with the brand's own qty/segment-share, PLUS
    #    top-N and bottom-N brands (short name + qty/share) as separate
    #    columns -- an Excel-pivot-style wide table.
    # ------------------------------------------------------------------
    @staticmethod
    def _short_brand_name(name: str, maxlen: int = 15) -> str:
        if len(name) <= maxlen:
            return name
        truncated = name[:maxlen]
        if ' ' in truncated:
            truncated = truncated.rsplit(' ', 1)[0]
        return truncated + '..'

    def brand_transaction_count_pivot_view(self, brand_name: str, target_count: int = 1,
                                            comparison: str = 'equal', top_n_shops: int = 10,
                                            top_n_brands: int = 3, other_n_brands: int = 5,
                                            other_min_pct: float = 1.0, name_maxlen: int = 15):
        df = self.df
        sub = df[df['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        if sub.empty:
            return {'found': False, 'message': f'Brand "{brand_name}" not found.'}

        txn_counts = sub.groupby(['shop_code', 'shop_name_as_per_company_data']).size()
        if comparison == 'less_equal':
            matched = txn_counts[txn_counts <= target_count]
        elif comparison == 'greater_equal':
            matched = txn_counts[txn_counts >= target_count]
        else:
            matched = txn_counts[txn_counts == target_count]

        total_matching = len(matched)
        own_bd_segment = sub['bd_segment'].unique()
        segment_df = df[df['bd_segment'].isin(own_bd_segment)]

        canonical_segment = own_bd_segment[0] if len(own_bd_segment) else ''
        segment_col_key = 'segment_sale_at_shop'

        rows = []
        for (shop_code, shop_name), _count in list(matched.items())[:top_n_shops]:
            shop_seg_df = segment_df[segment_df['shop_code'] == shop_code]
            shop_seg_total = int(shop_seg_df['sale_qty_in_box'].sum())
            brand_qty = int(sub[sub['shop_code'] == shop_code]['sale_qty_in_box'].sum())
            brand_pct = round(brand_qty / shop_seg_total * 100, 2) if shop_seg_total else 0.0

            ranked = (shop_seg_df.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                      .sum().sort_values(ascending=False))
            top_n = ranked.head(top_n_brands)

            # "Other brands" -- everything AFTER the top-N, that still has at
            # least `other_min_pct`% share of this shop's segment (so we
            # only show brands that are genuinely significant here, not
            # truly tiny/bottom performers).
            remaining = ranked.iloc[top_n_brands:]
            if shop_seg_total:
                remaining_pct = (remaining / shop_seg_total * 100)
                qualifying = remaining[remaining_pct >= other_min_pct].head(other_n_brands)
            else:
                qualifying = remaining.head(0)

            row = {
                'shop': shop_name,
                segment_col_key: shop_seg_total,
                'brand_query_shop_seg_pct': f"{brand_qty} / {brand_pct}%",
            }
            for i, (b, q) in enumerate(top_n.items(), 1):
                pct = round(int(q) / shop_seg_total * 100, 2) if shop_seg_total else 0.0
                row[f'top_{i}'] = f"{self._short_brand_name(b, name_maxlen)}: {int(q)}/{pct}%"

            top_n_qty_sum = int(top_n.sum())
            top_n_pct_sum = round(top_n_qty_sum / shop_seg_total * 100, 2) if shop_seg_total else 0.0
            row['total_top_n'] = f"{top_n_qty_sum} / {top_n_pct_sum}%"

            for i in range(1, other_n_brands + 1):
                if i <= len(qualifying):
                    b, q = list(qualifying.items())[i - 1]
                    pct = round(int(q) / shop_seg_total * 100, 2) if shop_seg_total else 0.0
                    row[f'brand_{i}'] = f"{self._short_brand_name(b, name_maxlen)}: {int(q)}/{pct}%"
                else:
                    row[f'brand_{i}'] = "-"

            other_qty_sum = int(qualifying.sum())
            other_pct_sum = round(other_qty_sum / shop_seg_total * 100, 2) if shop_seg_total else 0.0
            row['total_other_n'] = f"{other_qty_sum} / {other_pct_sum}%"

            rows.append(row)

        canonical_segment = own_bd_segment[0] if len(own_bd_segment) else ''
        return {
            'found': True,
            'brand_query_name': brand_name,
            'brand_segment_name': canonical_segment,
            'matching_shops_count': total_matching,
            'shops_shown': total_matching if top_n_shops is None else min(top_n_shops, total_matching),
            'pivot_rows': rows,
        }

    # ------------------------------------------------------------------
    # ab) Shop-wise SEPARATE tables: same data as
    #    brand_transaction_count_pivot_view, but ONE SMALL TABLE PER SHOP
    #    instead of one big table -- because each shop's top/other brands
    #    are DIFFERENT, so brand names can be used as the actual COLUMN
    #    HEADERS (impossible to do that cleanly in a single shared table).
    # ------------------------------------------------------------------
    def brand_transaction_count_shopwise_tables(self, brand_name: str, target_count: int = 1,
                                                 comparison: str = 'equal', top_n_shops: int = 10,
                                                 top_n_brands: int = 3, other_n_brands: int = 5,
                                                 other_min_pct: float = 1.0, name_maxlen: int = 15):
        df = self.df
        sub = df[df['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        if sub.empty:
            return {'found': False, 'message': f'Brand "{brand_name}" not found.'}

        txn_counts = sub.groupby(['shop_code', 'shop_name_as_per_company_data']).size()
        if comparison == 'less_equal':
            matched = txn_counts[txn_counts <= target_count]
        elif comparison == 'greater_equal':
            matched = txn_counts[txn_counts >= target_count]
        else:
            matched = txn_counts[txn_counts == target_count]

        total_matching = len(matched)
        own_bd_segment = sub['bd_segment'].unique()
        segment_df = df[df['bd_segment'].isin(own_bd_segment)]
        canonical_segment = own_bd_segment[0] if len(own_bd_segment) else ''
        brand_short = self._short_brand_name(brand_name, name_maxlen)

        blocks = []
        for (shop_code, shop_name), _count in list(matched.items())[:top_n_shops]:
            shop_seg_df = segment_df[segment_df['shop_code'] == shop_code]
            shop_seg_total = int(shop_seg_df['sale_qty_in_box'].sum())
            brand_qty = int(sub[sub['shop_code'] == shop_code]['sale_qty_in_box'].sum())
            brand_pct = round(brand_qty / shop_seg_total * 100, 2) if shop_seg_total else 0.0

            ranked = (shop_seg_df.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                      .sum().sort_values(ascending=False))
            top_n = ranked.head(top_n_brands)
            remaining = ranked.iloc[top_n_brands:]
            if shop_seg_total:
                remaining_pct = remaining / shop_seg_total * 100
                qualifying = remaining[remaining_pct >= other_min_pct].head(other_n_brands)
            else:
                qualifying = remaining.head(0)

            headers = ['Shop', f'{brand_short} - Shop Seg %']
            values = [shop_name, f"{brand_qty} / {brand_pct}%"]
            for b, q in top_n.items():
                pct = round(int(q) / shop_seg_total * 100, 2) if shop_seg_total else 0.0
                headers.append(self._short_brand_name(b, name_maxlen))
                values.append(f"{int(q)} / {pct}%")
            for b, q in qualifying.items():
                pct = round(int(q) / shop_seg_total * 100, 2) if shop_seg_total else 0.0
                headers.append(self._short_brand_name(b, name_maxlen))
                values.append(f"{int(q)} / {pct}%")

            blocks.append({'shop_name': shop_name, 'headers': headers, 'values': values})

        return {
            'found': True,
            'brand_query_name': brand_name,
            'brand_segment_name': canonical_segment,
            'matching_shops_count': total_matching,
            'shops_shown': total_matching if top_n_shops is None else min(top_n_shops, total_matching),
            'blocks': blocks,
        }

    # ------------------------------------------------------------------
    # v) GAP #7: Zero-presence analysis -- given a filter (e.g. a company),
    #    find ALL values of a "universe" dimension (e.g. all shops) where
    #    that filter has ZERO sales -- true absence across the FULL
    #    universe, not just within some other brand's top-N shops.
    # ------------------------------------------------------------------
    def zero_presence_analysis(self, filter_col: str, filter_value: str, universe_col: str = 'shop_code',
                                show_hero_brand_in_segment: bool = False):
        df = self.df
        mask = df[filter_col].astype(str).str.upper() == str(filter_value).upper()
        if not mask.any():
            return {'found': False, 'message': f'"{filter_value}" not found in {filter_col}.'}
        canonical_value = df.loc[mask, filter_col].iloc[0]

        all_universe_values = set(df[universe_col].dropna().unique())
        present_universe_values = set(df.loc[mask, universe_col].dropna().unique())
        absent_values = sorted(all_universe_values - present_universe_values)

        # Enrichment fields (only meaningful when checking a BRAND's zero-
        # presence): the brand's own segment context (segment total sale,
        # overall market %) + the brand's own overall qty/market-share/
        # segment-share + its company -- shown ONCE above the table, same
        # style as segment_top_brands_with_shop_and_compare.
        enrichment = {}
        if filter_col == 'brand_name_as_per_company_data':
            own_bd_segment_val = df.loc[mask, 'bd_segment'].iloc[0]
            segment_df = df[df['bd_segment'] == own_bd_segment_val]
            segment_total_qty = int(segment_df['sale_qty_in_box'].sum())
            overall_total_market = int(self.total_market)
            brand_overall_qty = int(df.loc[mask, 'sale_qty_in_box'].sum())
            enrichment = {
                'bd_segment': own_bd_segment_val,
                'segment_total_sale': segment_total_qty,
                'overall_total_market': overall_total_market,
                'segment_pct_of_overall_market': (
                    float(round(segment_total_qty / self.total_market * 100, 2)) if self.total_market else 0.0
                ),
                'brand_overall_qty': brand_overall_qty,
                'brand_overall_pct_of_market': (
                    float(round(brand_overall_qty / self.total_market * 100, 2)) if self.total_market else 0.0
                ),
                'brand_overall_pct_of_segment': (
                    float(round(brand_overall_qty / segment_total_qty * 100, 2)) if segment_total_qty else 0.0
                ),
                'company_name': df.loc[mask, 'company_name'].iloc[0],
            }
        else:
            own_bd_segment_val = None

        if universe_col == 'shop_code' and filter_col == 'brand_name_as_per_company_data':
            # Sl No, Department, Shop Name, Shop Code, Sale Qty in Box
            # (always 0). Brand/BD Segment are NOT repeated per row (same
            # value every time) -- shown ONCE above the table instead.
            dept_map = df.drop_duplicates('shop_code').set_index('shop_code')['department'].to_dict()
            name_map = (df.drop_duplicates('shop_code')
                        .set_index('shop_code')['shop_name_as_per_company_data'].to_dict())
            absent_items = [
                {
                    'sl_no': idx + 1,
                    'department': dept_map.get(v, ''),
                    'shop_name': name_map.get(v, ''),
                    'shop_code': v,
                    'sale_qty_in_box': 0,
                }
                for idx, v in enumerate(absent_values)
            ]
        elif universe_col == 'shop_code':
            name_map = (df.drop_duplicates('shop_code')
                        .set_index('shop_code')['shop_name_as_per_company_data'].to_dict())
            absent_items = [{'shop_code': v, 'shop_name': name_map.get(v, '')} for v in absent_values]
        else:
            absent_items = [{'item': v} for v in absent_values]

        # Optional enrichment: at EACH zero-presence shop, who is the "hero"
        # (top-selling) brand within the SAME bd_segment as the filter
        # brand? E.g. "Dennis absent here -- who's winning Regular Whisky
        # at this shop instead?" -- only makes sense when filter_col is a
        # brand (bd_segment is a brand-level attribute).
        if show_hero_brand_in_segment and filter_col == 'brand_name_as_per_company_data' and universe_col == 'shop_code':
            own_bd_segment = df.loc[mask, 'bd_segment'].unique()
            segment_df = df[df['bd_segment'].isin(own_bd_segment)]
            for item in absent_items:
                shop_seg_df = segment_df[segment_df['shop_code'] == item['shop_code']]
                if not shop_seg_df.empty:
                    hero = (shop_seg_df.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                            .sum().sort_values(ascending=False))
                    item['hero_brand_in_segment'] = hero.index[0]
                    item['hero_brand_qty'] = int(hero.iloc[0])
                else:
                    item['hero_brand_in_segment'] = None
                    item['hero_brand_qty'] = 0

        result = {
            'found': True,
            filter_col: canonical_value,
            **enrichment,
            'universe_dimension': universe_col,
            'total_universe_count': len(all_universe_values),
            'present_count': len(present_universe_values),
            'absent_count': len(absent_values),
            'absent_items': absent_items,  # FULL list -- display-truncation happens at the API layer, not here
        }
        return result

    # ------------------------------------------------------------------
    # z) Zero-sale shops + top N brands (SAME segment) at each shop, shown
    #    as WIDE columns (TOP 1, TOP 2, ... TOP N) -- each cell is
    #    "Brand Name - Qty / Shop Segment %".
    # ------------------------------------------------------------------
    def zero_sale_with_top_segment_brands(self, brand_name: str, top_n: int = 20, rank_mode: str = 'top'):
        df = self.df
        mask = df['brand_name_as_per_company_data'].str.upper() == brand_name.upper()
        if not mask.any():
            return {'found': False, 'message': f'Brand "{brand_name}" not found.'}
        canonical_brand = df.loc[mask, 'brand_name_as_per_company_data'].iloc[0]
        own_bd_segment = df.loc[mask, 'bd_segment'].iloc[0]
        segment_df = df[df['bd_segment'] == own_bd_segment]

        # Same enrichment header as zero_presence_analysis: brand's own
        # segment context, overall stats, and company -- shown ONCE above
        # the wide TOP/BOTTOM/MID table.
        segment_total_qty = int(segment_df['sale_qty_in_box'].sum())
        overall_total_market = int(self.total_market)
        brand_overall_qty = int(df.loc[mask, 'sale_qty_in_box'].sum())
        segment_pct_of_overall_market = (
            float(round(segment_total_qty / self.total_market * 100, 2)) if self.total_market else 0.0
        )
        brand_overall_pct_of_market = (
            float(round(brand_overall_qty / self.total_market * 100, 2)) if self.total_market else 0.0
        )
        brand_overall_pct_of_segment = (
            float(round(brand_overall_qty / segment_total_qty * 100, 2)) if segment_total_qty else 0.0
        )
        company_name = df.loc[mask, 'company_name'].iloc[0]

        all_shops = set(df['shop_code'].dropna().unique())
        present_shops = set(df.loc[mask, 'shop_code'].dropna().unique())
        absent_shops = sorted(all_shops - present_shops)

        dept_map = df.drop_duplicates('shop_code').set_index('shop_code')['department'].to_dict()
        name_map = (df.drop_duplicates('shop_code')
                    .set_index('shop_code')['shop_name_as_per_company_data'].to_dict())

        # Column key prefix changes based on direction -- "bottom_1",
        # "mid_1"... vs "top_1"... -- so table headers automatically read
        # "Bottom 1", "Mid 1" (via the default label formatter) matching
        # which slice of the segment ranking is being shown.
        col_prefix = rank_mode if rank_mode in ('top', 'bottom', 'mid') else 'top'

        rows = []
        for idx, shop_code in enumerate(absent_shops, start=1):
            shop_seg_df = segment_df[segment_df['shop_code'] == shop_code]
            shop_seg_total = int(shop_seg_df['sale_qty_in_box'].sum())
            full_ranked = (shop_seg_df.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                           .sum().sort_values(ascending=False))

            if col_prefix == 'bottom':
                ranked_here = full_ranked.sort_values(ascending=True).head(top_n)
            elif col_prefix == 'mid':
                # Middle N brands from the FULL segment-at-this-shop ranking
                # -- a slice centered around the median rank, neither the
                # strongest nor the weakest performers.
                total_here = len(full_ranked)
                start = max(0, (total_here - top_n) // 2)
                ranked_here = full_ranked.iloc[start:start + top_n]
            else:
                ranked_here = full_ranked.head(top_n)

            row = {
                'sl_no': idx,
                'department': dept_map.get(shop_code, ''),
                'shop_name': name_map.get(shop_code, ''),
                'shop_code': shop_code,
                'sale_qty_in_box': 0,
                'segment_sale_on_shop': shop_seg_total,
            }
            ranked_list = list(ranked_here.items())
            for rank in range(1, top_n + 1):
                col_key = f'{col_prefix}_{rank}'
                if rank <= len(ranked_list):
                    b_name, b_qty = ranked_list[rank - 1]
                    b_qty = int(b_qty)
                    b_pct = round(b_qty / shop_seg_total * 100, 2) if shop_seg_total else 0.0
                    row[col_key] = f"{b_name} - {b_qty} / {b_pct}%"
                else:
                    row[col_key] = ""
            rows.append(row)

        return {
            'found': True,
            'brand': canonical_brand,
            'bd_segment': own_bd_segment,
            'segment_total_sale': segment_total_qty,
            'overall_total_market': overall_total_market,
            'segment_pct_of_overall_market': segment_pct_of_overall_market,
            'brand_overall_qty': brand_overall_qty,
            'brand_overall_pct_of_market': brand_overall_pct_of_market,
            'brand_overall_pct_of_segment': brand_overall_pct_of_segment,
            'company_name': company_name,
            'absent_count': len(absent_shops),
            'rank_direction': col_prefix,
            'n': top_n,
            f'rows_{col_prefix}': rows,
        }

    # ------------------------------------------------------------------
    # ab) BD Segment x Month x Brand breakdown -- for each (segment, month,
    #     brand) combination, shows sale qty and the brand's % share of
    #     that segment IN that specific month. BD Segment reflects in
    #     EVERY row (not summarized once) since this report can span
    #     multiple segments and months at once, unlike our other reports
    #     which are scoped to one segment/brand.
    # ------------------------------------------------------------------
    def segment_month_brand_breakdown(self, bd_segment: str = None, top_n_brands: int = None):
        """PIVOT-style report: one row per (BD Segment, Brand), with EACH
        month's sale as a SEPARATE column (e.g. 'Apr-26 Sale', 'May-26
        Sale'), plus a 'Total' column (sum across the whole period) and
        'Brand % of Total Segment' (that brand's share of the segment's
        TOTAL sale across the whole period, not per-month)."""
        df = self.df
        canonical_segment = None
        if bd_segment:
            mask = df['bd_segment'].astype(str).str.upper() == str(bd_segment).upper()
            if not mask.any():
                return {'found': False, 'message': f'"{bd_segment}" not found in bd_segment.'}
            canonical_segment = df.loc[mask, 'bd_segment'].iloc[0]
            df = df[mask]

        if df.empty:
            return {'found': False, 'message': 'Is filter ke liye koi data nahi mila.'}

        # Chronological month order (not alphabetical) -- so columns read
        # left-to-right in real calendar sequence.
        months = sorted(df['month'].astype(str).unique(),
                         key=lambda m: pd.to_datetime(m, format='%b-%y', errors='coerce'))
        month_cols = [f'{m} Sale' for m in months]

        # Segment's TOTAL sale across the WHOLE period (all months combined)
        # -- the denominator for "Brand % of Total Segment".
        segment_totals = df.groupby('bd_segment')['sale_qty_in_box'].sum()

        pivot = df.pivot_table(index=['bd_segment', 'brand_name_as_per_company_data'],
                                columns='month', values='sale_qty_in_box',
                                aggfunc='sum', fill_value=0)
        pivot = pivot.reindex(columns=months, fill_value=0)

        rows = []
        for (seg, brand), row_data in pivot.iterrows():
            total_qty = int(row_data.sum())
            seg_total = int(segment_totals.get(seg, 0))
            pct = float(round(total_qty / seg_total * 100, 2)) if seg_total else 0.0

            row = {}
            if canonical_segment is None:
                row['bd_segment'] = seg
            row['brand'] = brand
            for m, col_label in zip(months, month_cols):
                row[col_label] = int(row_data[m])
            row['Total'] = total_qty
            row['brand_pct_of_total_segment'] = pct
            rows.append(row)

        # Sort by Total descending within each segment, cap to top_n_brands
        # PER segment (not overall) -- otherwise one huge segment would
        # crowd out smaller ones entirely.
        rows.sort(key=lambda r: (r.get('bd_segment', ''), -r['Total']))
        if top_n_brands:
            capped_rows = []
            current_key = None
            count_in_group = 0
            for r in rows:
                key = r.get('bd_segment', canonical_segment)
                if key != current_key:
                    current_key = key
                    count_in_group = 0
                count_in_group += 1
                if count_in_group <= top_n_brands:
                    capped_rows.append(r)
            rows = capped_rows

        result = {'found': True, '__show_full__': True}
        if canonical_segment is not None:
            result['bd_segment'] = canonical_segment
        result['rows'] = rows
        return result

    # ------------------------------------------------------------------
    # w) GAP #9: Cross-tab / matrix report -- one dimension as rows,
    #    another as columns, sale qty as cell values (like an Excel
    #    pivot table).
    # ------------------------------------------------------------------
    def cross_tab_matrix(self, row_dim: str, col_dim: str, top_rows: int = 10, top_cols: int = 8):
        df = self.df
        if row_dim == col_dim:
            return {'found': False,
                    'message': ('Row aur Column dimension SAME nahi ho sakte cross-tab ke liye -- '
                                'yeh ek matrix hai, dono taraf same dimension dikhane ka koi matlab '
                                'nahi banta. Alag-alag dimensions do (jaise department vs liquor_type).')}
        top_row_vals = (df.groupby(row_dim)['sale_qty_in_box'].sum()
                         .sort_values(ascending=False).head(top_rows).index.tolist())
        top_col_vals = (df.groupby(col_dim)['sale_qty_in_box'].sum()
                         .sort_values(ascending=False).head(top_cols).index.tolist())

        filtered = df[df[row_dim].isin(top_row_vals) & df[col_dim].isin(top_col_vals)]
        if filtered.empty:
            return {'found': False, 'message': 'Is combination ke liye koi data nahi mila.'}

        pivot = filtered.pivot_table(index=row_dim, columns=col_dim, values='sale_qty_in_box',
                                      aggfunc='sum', fill_value=0)
        pivot = pivot.reindex(index=top_row_vals, columns=top_col_vals, fill_value=0)
        pivot.columns.name = None

        return {
            'found': True,
            'row_dimension': row_dim,
            'col_dimension': col_dim,
            'matrix': pivot.reset_index().to_dict('records'),
        }

    # ------------------------------------------------------------------
    # x) GAP #10: Compound ranking -- rank items by BOTH current volume
    #    AND month-over-month growth simultaneously (two criteria at
    #    once), showing both ranks side by side.
    # ------------------------------------------------------------------
    @staticmethod
    def compound_ranking(df_current, df_previous, rank_col: str = 'brand_name_as_per_company_data',
                          top_n: int = 10, min_base: int = 100):
        cur = df_current.groupby(rank_col)['sale_qty_in_box'].sum()
        prev = df_previous.groupby(rank_col)['sale_qty_in_box'].sum()
        merged = pd.DataFrame({'current_qty': cur, 'previous_qty': prev}).fillna(0)
        merged = merged[merged['previous_qty'] >= min_base]
        if merged.empty:
            return {'found': False, 'message': 'min_base ke saath koi data nahi mila.'}

        merged['pct_change'] = (
            (merged['current_qty'] - merged['previous_qty']) / merged['previous_qty'] * 100
        ).round(2)
        merged['volume_rank'] = merged['current_qty'].rank(ascending=False, method='min').astype(int)
        merged['growth_rank'] = merged['pct_change'].rank(ascending=False, method='min').astype(int)
        merged['combined_rank_score'] = merged['volume_rank'] + merged['growth_rank']

        top = merged.sort_values('combined_rank_score').head(top_n).reset_index()
        top['current_qty'] = top['current_qty'].astype(int)
        top['previous_qty'] = top['previous_qty'].astype(int)

        return {'found': True, 'ranking': top.to_dict('records')}

    # ------------------------------------------------------------------
    # y) Segment top brands + each brand's #1 shop + segment-share there,
    #    PLUS a specific compare_brand's status at those SAME shops.
    #    e.g. "Semi Pre Whisky top 20 brands, their best shop, that
    #    brand's segment-share at that shop, and what 8PM's segment-share
    #    is at that SAME shop" -- a nested drill-down comparison.
    # ------------------------------------------------------------------
    def segment_top_brands_with_shop_and_compare(self, bd_segment: str, top_n: int = 20,
                                                   compare_brand: str = None):
        df = self.df
        segment_df = df[df['bd_segment'].str.upper() == bd_segment.upper()]
        if segment_df.empty:
            return {'found': False, 'message': f'"{bd_segment}" not found in bd_segment.'}
        canonical_segment = segment_df['bd_segment'].iloc[0]

        # Segment-level summary (shown ONCE, above the per-brand table) --
        # total sale of the whole segment + its share of the overall market
        # + the overall market total itself (for direct comparison).
        segment_total_qty = int(segment_df['sale_qty_in_box'].sum())
        overall_total_market = int(self.total_market)
        segment_pct_of_market = (
            float(round(segment_total_qty / self.total_market * 100, 2)) if self.total_market else 0.0
        )

        top_brands = (segment_df.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                      .sum().sort_values(ascending=False).head(top_n))

        # Compare brand's TRUE overall stats (its total across ALL shops/
        # segments, not scoped to any one shop) -- shown ONCE at top level
        # since it doesn't change per-row. This answers "how big is this
        # brand OVERALL", separate from "how much of it sells at brand X's
        # top shop specifically" (which the per-row fields below cover).
        compare_brand_overall_qty = None
        compare_brand_overall_pct_of_market = None
        compare_brand_overall_pct_of_segment = None
        if compare_brand:
            comp_all = df[df['brand_name_as_per_company_data'].str.upper() == compare_brand.upper()]
            compare_brand_overall_qty = int(comp_all['sale_qty_in_box'].sum())
            compare_brand_overall_pct_of_market = (
                round(compare_brand_overall_qty / self.total_market * 100, 2) if self.total_market else 0.0
            )
            comp_in_segment_qty = int(
                segment_df[segment_df['brand_name_as_per_company_data'].str.upper() == compare_brand.upper()]
                ['sale_qty_in_box'].sum()
            )
            compare_brand_overall_pct_of_segment = (
                round(comp_in_segment_qty / segment_total_qty * 100, 2) if segment_total_qty else 0.0
            )

        # FIXED (not dynamic) column keys -- the compare_brand's actual name
        # is already shown once at the top level, so per-row columns use
        # short, clean, constant labels instead of repeating the full brand
        # name in every column header.
        qty_key = 'compare_brand_qty_at_shop'
        seg_pct_key = 'segment_pct_at_shop'
        market_pct_key = 'total_market_share'

        rows = []
        for brand, brand_total_qty in top_brands.items():
            brand_df = segment_df[segment_df['brand_name_as_per_company_data'] == brand]
            shop_qty = (brand_df.groupby(['shop_code', 'shop_name_as_per_company_data'])['sale_qty_in_box']
                        .sum().sort_values(ascending=False))
            if shop_qty.empty:
                continue
            top_shop_code, top_shop_name = shop_qty.index[0]
            brand_qty_at_shop = int(shop_qty.iloc[0])

            # Segment total AT THIS SPECIFIC SHOP (denominator for % share)
            shop_segment_total = int(
                segment_df[segment_df['shop_code'] == top_shop_code]['sale_qty_in_box'].sum()
            )
            brand_pct_at_shop = (
                round(brand_qty_at_shop / shop_segment_total * 100, 2) if shop_segment_total else 0.0
            )
            # This brand's OWN overall total-market share % (not scoped to
            # this one shop) -- so both the top brand AND the compare brand
            # have a like-for-like "overall market share" figure shown.
            brand_overall_market_pct = (
                float(round(int(brand_total_qty) / self.total_market * 100, 2)) if self.total_market else 0.0
            )

            row = {
                'brand': brand,
                'brand_total_qty_in_segment': int(brand_total_qty),
                'top_shop_name': top_shop_name,
                'brand_qty_at_shop': brand_qty_at_shop,
                'brand_segment_pct_at_shop': brand_pct_at_shop,
                'brand_total_market_share': brand_overall_market_pct,
            }

            if compare_brand:
                comp_df = segment_df[
                    (segment_df['shop_code'] == top_shop_code) &
                    (segment_df['brand_name_as_per_company_data'].str.upper() == compare_brand.upper())
                ]
                comp_qty = int(comp_df['sale_qty_in_box'].sum())
                comp_seg_pct = float(round(comp_qty / shop_segment_total * 100, 2)) if shop_segment_total else 0.0
                comp_market_pct = float(round(comp_qty / self.total_market * 100, 2)) if self.total_market else 0.0
                row[qty_key] = comp_qty
                row[seg_pct_key] = comp_seg_pct
                row[market_pct_key] = comp_market_pct

            rows.append(row)

        return {
            'found': True,
            'bd_segment': canonical_segment,
            'segment_total_sale': segment_total_qty,
            'overall_total_market': overall_total_market,
            'segment_pct_of_overall_market': segment_pct_of_market,
            'compare_brand': compare_brand,
            'compare_brand_overall_qty': compare_brand_overall_qty,
            'compare_brand_overall_pct_of_market': compare_brand_overall_pct_of_market,
            'compare_brand_overall_pct_of_segment': compare_brand_overall_pct_of_segment,
            'top_brands': rows,
        }

    # ------------------------------------------------------------------
    # p) Growth breakdown -- WHERE (which department/shop/TSE) did a
    #    brand's month-over-month growth/decline actually come from.
    #    NOTE: this only decomposes growth by data dimensions already in
    #    the dataset -- it CANNOT explain external business causes
    #    (marketing, pricing, competitor actions) since that data doesn't
    #    exist in this table at all.
    # ------------------------------------------------------------------
    @staticmethod
    def brand_growth_breakdown(brand_name: str, df_current, df_previous,
                                breakdown_by: str = 'department', top_n: int = 10,
                                extra_filters: dict = None):
        cur = df_current[df_current['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        prev = df_previous[df_previous['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]

        # Optional additional scoping filter -- e.g. {"department": "DSIIDC"}
        # to see the shop-wise breakdown WITHIN just that department, rather
        # than across the whole brand.
        if extra_filters:
            for col, val in extra_filters.items():
                cur = cur[cur[col].astype(str).str.upper() == str(val).upper()]
                prev = prev[prev[col].astype(str).str.upper() == str(val).upper()]

        if cur.empty and prev.empty:
            return {'found': False, 'message': f'Brand "{brand_name}" not found in either month (with given filters).'}

        cur_group = cur.groupby(breakdown_by)['sale_qty_in_box'].sum()
        prev_group = prev.groupby(breakdown_by)['sale_qty_in_box'].sum()

        merged = pd.DataFrame({'current_qty': cur_group, 'previous_qty': prev_group}).fillna(0)
        merged['change_qty'] = (merged['current_qty'] - merged['previous_qty']).astype(int)
        merged['current_qty'] = merged['current_qty'].astype(int)
        merged['previous_qty'] = merged['previous_qty'].astype(int)

        total_change = int(merged['change_qty'].sum())
        if total_change != 0:
            merged['pct_of_total_change'] = (merged['change_qty'] / total_change * 100).round(2)
        else:
            merged['pct_of_total_change'] = 0.0

        merged = merged.sort_values('change_qty', ascending=False).reset_index()
        merged = merged.rename(columns={breakdown_by: breakdown_by})

        return {
            'found': True,
            'brand': brand_name,
            'breakdown_by': breakdown_by,
            'overall_change_qty': total_change,
            'breakdown': merged.head(top_n).to_dict('records'),
        }

    # ------------------------------------------------------------------
    # t) Shop-strength analysis: find a brand's BOTTOM N shops (weakest,
    #    where it sells least) OR TOP N shops (strongest), then for those
    #    SAME shops, show either (a) the top-N other brands selling there,
    #    or (b) a SPECIFIC competitor brand's performance there. Useful for
    #    finding under-penetrated shops (weak) OR understanding the
    #    competitive landscape in a brand's strongholds (top).
    # ------------------------------------------------------------------
    def brand_weak_shops_analysis(self, brand_name: str, bottom_n_shops: int = 10,
                                   compare_brand: str = None, top_n_other_brands: int = 5,
                                   find_bottom: bool = True, restrict_to_own_segment: bool = False):
        df = self.df
        sub = df[df['brand_name_as_per_company_data'].str.upper() == brand_name.upper()]
        if sub.empty:
            return {'found': False, 'message': f'Brand "{brand_name}" not found.'}

        # If restricting to the brand's own bd_segment, only consider brands
        # within that same segment when finding "top brands at this shop" --
        # e.g. only other Regular Whisky brands, not every brand overall.
        own_bd_segment = sub['bd_segment'].unique()
        universe_df = df[df['bd_segment'].isin(own_bd_segment)] if restrict_to_own_segment else df

        shop_sales = (sub.groupby(['shop_code', 'shop_name_as_per_company_data'])['sale_qty_in_box']
                      .sum().sort_values(ascending=find_bottom).head(bottom_n_shops))

        rows = []
        for (shop_code, shop_name), brand_qty in shop_sales.items():
            shop_df = universe_df[universe_df['shop_code'] == shop_code]

            if compare_brand:
                comp_sub = shop_df[shop_df['brand_name_as_per_company_data'].str.upper() == compare_brand.upper()]
                comp_qty = int(comp_sub['sale_qty_in_box'].sum())
                rows.append({
                    'shop_code': shop_code,
                    'shop_name': shop_name,
                    f'{brand_name}_qty': int(brand_qty),
                    f'{compare_brand}_qty': comp_qty,
                })
            else:
                # Market share % = this brand's qty at this shop / TOTAL
                # qty at this shop (within the same universe -- own segment
                # if restrict_to_own_segment, else all brands) -- replaces
                # a plain rank number with a more useful business metric.
                shop_total_qty = int(shop_df['sale_qty_in_box'].sum())
                top_here = (shop_df.groupby('brand_name_as_per_company_data')['sale_qty_in_box']
                            .sum().sort_values(ascending=False).head(top_n_other_brands))
                for rank, (other_brand, other_qty) in enumerate(top_here.items(), start=1):
                    market_share_pct = (
                        round(int(other_qty) / shop_total_qty * 100, 2) if shop_total_qty else 0.0
                    )
                    rows.append({
                        'shop_code': shop_code,
                        'shop_name': shop_name,
                        f'{brand_name}_qty_here': int(brand_qty),
                        'rank_here': rank,
                        'top_brand_here': other_brand,
                        'top_brand_qty': int(other_qty),
                        'top_brand_market_share_pct_at_shop': market_share_pct,
                    })

        return {
            'found': True,
            'brand': brand_name,
            'analysis_type': 'weakest_shops' if find_bottom else 'strongest_shops',
            'restricted_to_own_bd_segment': restrict_to_own_segment,
            'bd_segment': list(own_bd_segment) if restrict_to_own_segment else None,
            'n_shops': bottom_n_shops,
            'compare_brand': compare_brand,
            'rows': rows,
        }


# ----------------------------------------------------------------------
# Example usage / quick test
# ----------------------------------------------------------------------
if __name__ == '__main__':
    df = pd.read_csv('/mnt/user-data/uploads/DI_MAY_26.csv', low_memory=False)
    engine = SmartQueryEngine(df)

    print(engine.brand_report('DENNIS SPECIAL GOLD WHISKY'))
    print()
    print(engine.smart_query('Semi Pre Whisky', '8 PM PREMIUM BLACK BLENDED WHISKY'))
    print()
    print(engine.market_share('company_name', top_n=5))
    print()
    print(engine.brand_share_filter('Semi Pre Whisky', threshold=5.0, mode='above'))
    print()
    print(engine.compare_brands(['OLD HABBIT PREMIUM WHISKY', 'ROYAL ACE RARE BLENDED WHISKY',
                                   'ALL SEASONS COLLECTORS COLLECTION RESERVE WHISKY']))
    print()
    print(engine.cross_reference_shops('OLD HABBIT PREMIUM WHISKY', 'ROYAL ACE RARE BLENDED WHISKY', top_n=5))

    # MoM example (using real April vs May data):
    df_april = pd.read_csv('/mnt/user-data/uploads/DI_APR_26.csv', low_memory=False)
    mom_result = SmartQueryEngine.mom_gainers_losers(df, df_april, group_col='bd_segment',
                                                       min_base=500, top_n=10)
    print()
    print('Top Gainer:', mom_result['top_gainers'][0])
    print('Top Loser:', mom_result['top_losers'][0])
