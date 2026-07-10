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
