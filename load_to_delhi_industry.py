"""
RSD Enterprise AI — Load ONE monthly CSV into Supabase delhi_industry table

Design: files stay separate per month (DI_APR_26.csv, DI_MAY_26.csv, DI_JUN_26.csv...).
Each month, run this script ONCE with that month's file. It tags the rows with
file_source and appends into the same growing Supabase table — no manual merging needed.

Usage:
    python load_to_supabase.py DI_JUN_26.csv

Requirements: pip install supabase pandas --break-system-packages
"""

import sys
import os
import pandas as pd
from supabase import create_client

# --- CONFIG: replace with your actual Supabase project values ---
SUPABASE_URL = "https://eolwowzmrqznwgdakoqn.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_KEY")   # use service_role key, not anon key, for bulk insert
BATCH_SIZE = 1000  # insert in chunks to avoid payload limits


def clean_col(c):
    c = c.replace(',', '').replace('/', ' ').strip()
    return '_'.join(c.split()).lower()


# Columns that must be numeric in the delhi_industry table
NUMERIC_COLUMNS = [
    'product_itemsize', 'unit_qty_in_box', 'sale_qty_in_box',
    'mrp_nip_quarter', 'mrp_bottle', 'mrp_half', 'mrp_500_ml', 'mrp_pint',
    'mrp_miniature_60_ml', 'mrp_miniature_90_ml', 'mrp_miniature_100_ml',
    'mrp_imported_200_ml', 'mrp_imported_250_ml', 'mrp_imported_275_ml',
    'mrp_imported_700_ml', 'mrp_imported_bottle_1000_ml', 'mrp_imported_bottle_2000_ml',
]


def clean_numeric_columns(df):
    """Fix junk values like '&nbsp;' and stray text in numeric columns.
    We only coerce to numeric here (invalid -> NaN). The actual int/None
    conversion happens later per-record (see fix_record_numerics), because
    pandas always upcasts a column back to float64 the moment it contains
    any missing value -- there's no way to keep a DataFrame column as true
    int+None at the same time. Fighting that inside the DataFrame is a
    losing battle, so we fix it after converting to plain Python dicts.
    """
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def fix_record_numerics(record):
    """Convert numeric fields in a single record (plain Python dict) to true
    int or None, undoing pandas' float64 upcasting. Run this AFTER
    df.to_dict(orient='records') -- fixing it earlier gets overwritten by
    pandas internals."""
    for col in NUMERIC_COLUMNS:
        val = record.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            record[col] = None
        else:
            record[col] = int(val)
    return record


def main():
    if len(sys.argv) != 2:
        print("Usage: python load_to_supabase.py <path_to_month_csv>")
        sys.exit(1)

    csv_path = sys.argv[1]
    file_source = os.path.splitext(os.path.basename(csv_path))[0]  # e.g. DI_JUN_26

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    df = pd.read_csv(csv_path, low_memory=False, keep_default_na=False)
    df.columns = [clean_col(c) for c in df.columns]
    df = clean_numeric_columns(df)
    df['file_source'] = file_source

    # safety check: don't double-load the same month twice
    existing = supabase.table("delhi_industry").select("id", count="exact") \
        .eq("file_source", file_source).execute()
    if existing.count and existing.count > 0:
        print(f"'{file_source}' already has {existing.count} rows in delhi_industry. Skipping to avoid duplicates.")
        print("If you want to reload, delete those rows first (by file_source) in Supabase.")
        sys.exit(0)

    records = df.to_dict(orient="records")
    records = [fix_record_numerics(r) for r in records]
    total = len(records)
    print(f"Loading '{file_source}': {total} rows")

    for i in range(0, total, BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        supabase.table("delhi_industry").insert(batch).execute()
        print(f"Inserted {min(i + BATCH_SIZE, total)} / {total}")

    print(f"Done. '{file_source}' fully loaded into delhi_industry.")


if __name__ == "__main__":
    main()
