import pandas as pd
import numpy as np
from google.cloud import bigquery
from scoring_rules import (
    score_ap_row,
    score_bank_row,
    score_tax_row,
    score_lease_row,
)

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
PROJECT_ID = "confident-totem-390801"
DATASET = "peak_recon"

AP_TABLE = "ap_subledger"
BANK_TABLE = "bank_transactions"
TAX_TABLE = "tax_detail"
LEASE_TABLE = "lease_schedule"
GL_TABLE = "gl_trial_balance_summary"
TAX_RATE_TABLE = "tax_rate_reference"

BQ_LOCATION = "us-east1"

client = bigquery.Client(
    project=PROJECT_ID,
    location=BQ_LOCATION
)

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def load_table(table_name: str) -> pd.DataFrame:
    query = f"""
        SELECT *
        FROM `{PROJECT_ID}.{DATASET}.{table_name}`
    """
    return client.query(query).to_dataframe()


def write_output(df: pd.DataFrame, filename: str):
    df.to_csv(f"output/{filename}", index=False)
    print(f"✅ Wrote output/{filename}")


# --------------------------------------------------
# MODEL A — AP ↔ GL VALIDATION
# --------------------------------------------------
def validate_ap():
    print(" Validating AP_Subledger …")

    ap = load_table(AP_TABLE)

    # Type safety
    ap["Total_Invoice_Amount"] = pd.to_numeric(ap["Total_Invoice_Amount"], errors="coerce").fillna(0)
    ap["Expected_Total"] = pd.to_numeric(ap["Expected_Total"], errors="coerce").fillna(0)

    # Flags
    ap["amount_mismatch"] = (ap["Total_Invoice_Amount"] - ap["Expected_Total"]).abs() > 25
    ap["missing_in_GL"] = ap["AP_Match_Key"].isna() | (ap["AP_Match_Key"].astype(str).str.strip() == "") | (ap["AP_Match_Key"] == "Missing")

    ap["Invoice_Date"] = pd.to_datetime(ap["Invoice_Date"], errors="coerce")
    year_end = pd.Timestamp("2025-12-31")
    ap["late_posting"] = (ap["Unpaid_AsOfYE"] == True) & ((year_end - ap["Invoice_Date"]).dt.days > 60)

    ap["duplicate_invoice_number"] = ap.duplicated(subset=["Vendor", "Invoice_ID"], keep=False)

    vendor_gl_mode = (
        ap.groupby(["Vendor", "GL_Account"])
          .size()
          .reset_index(name="cnt")
          .sort_values("cnt", ascending=False)
          .drop_duplicates("Vendor")
    )
    vendor_gl_mode = vendor_gl_mode.rename(columns={"GL_Account": "mode_gl"})
    ap = ap.merge(vendor_gl_mode[["Vendor", "mode_gl"]], on="Vendor", how="left")
    ap["unusual_GL_account"] = ap["GL_Account"] != ap["mode_gl"]

    # Risk scoring
    ap["risk_score"], ap["risk_level"] = zip(*ap.apply(score_ap_row, axis=1))

    write_output(ap, "AP_with_risk.csv")
    return ap


# --------------------------------------------------
# MODEL B — BANK ↔ AP VALIDATION
# --------------------------------------------------
def validate_bank(ap):
    print(" Validating Bank_Transactions …")

    bank = load_table(BANK_TABLE)
    bank["Amount"] = pd.to_numeric(bank["Amount"], errors="coerce").fillna(0)

    ap_join = ap[["AP_Match_Key", "Total_Invoice_Amount"]].rename(
        columns={"AP_Match_Key": "Match_Key", "Total_Invoice_Amount": "Invoice_Amount"}
    )
    bank = bank.merge(ap_join, on="Match_Key", how="left")

    bank["no_matching_invoice"] = bank["Invoice_Amount"].isna()
    bank["duplicate_payment"] = bank["Duplicate_Payment_Flag"] == True
    bank["amount_mismatch"] = (bank["Amount"] - bank["Invoice_Amount"].fillna(0)).abs() > 1

    q90 = bank.groupby("Vendor")["Amount"].quantile(0.90).reset_index(name="q90")
    bank = bank.merge(q90, on="Vendor", how="left")
    bank["unusual_vendor_payment"] = bank["Amount"] > bank["q90"]

    bank["invoice_marked_paid_but_no_bank_txn"] = False

    bank["risk_score"], bank["risk_level"] = zip(*bank.apply(score_bank_row, axis=1))

    write_output(bank, "Bank_with_risk.csv")
    return bank


# --------------------------------------------------
# MODEL C — SALES & USE TAX VALIDATION
# --------------------------------------------------
def validate_tax():
    print(" Validating Sales & Use Tax …")

    tax = load_table(TAX_TABLE)
    gl = load_table(GL_TABLE)
    rates = load_table(TAX_RATE_TABLE)

    tax["Taxable_Amount"] = pd.to_numeric(tax["Taxable_Amount"], errors="coerce").fillna(0)
    tax["Calculated_Tax"] = pd.to_numeric(tax["Calculated_Tax"], errors="coerce").fillna(0)
    tax["Recalc_Tax"] = pd.to_numeric(tax["Recalc_Tax"], errors="coerce").fillna(0)

    rates = rates.rename(columns={
        "Tax_Jurisdiction": "State",
        "Total_Tax_Rate_2025": "Ref_Tax_Rate"
    })

    tax = tax.merge(rates[["State", "Ref_Tax_Rate"]], on="State", how="left")

    tax["jurisdiction_missing"] = tax["State"].isna() | (tax["State"].astype(str).str.strip() == "")
    tax["rate_mismatch"] = ~np.isclose(tax["Tax_Rate"], tax["Ref_Tax_Rate"], atol=0.0001, equal_nan=True)
    tax["tax_missing"] = (tax["Taxable_Amount"] > 0) & (tax["Calculated_Tax"] == 0)
    tax["tax_on_nontaxable_item"] = (tax["Taxable_Amount"] == 0) & (tax["Calculated_Tax"] > 0)
    tax["tax_diff_abs"] = (tax["Calculated_Tax"] - tax["Recalc_Tax"]).abs()

    gl_tax = gl[gl["Account"].str.contains("Tax", case=False, na=False)]
    gl_tax_balance = gl_tax["Ending_Balance"].sum()
    invoice_tax_total = tax["Calculated_Tax"].sum()

    tax["gl_tax_diff_flag"] = abs(gl_tax_balance - invoice_tax_total) > 100

    tax["risk_score"], tax["risk_level"] = zip(*tax.apply(score_tax_row, axis=1))

    write_output(tax, "Tax_with_risk.csv")
    return tax


# --------------------------------------------------
# MODEL D — ASC 842 LEASE VALIDATION
# --------------------------------------------------
def validate_leases():
    print("🔍 Validating ASC 842 Leases …")

    leases = load_table(LEASE_TABLE)
    gl = load_table(GL_TABLE)

    leases["ip_sum_mismatch"] = leases["IP_Sum_Mismatch_Flag"] == True
    leases["missing_periods"] = leases["Sequence_Check"] == "Sequence Error"

    lease_totals = leases.groupby("Lease_ID").agg(
        sched_liability=("Ending_Lease_Liability", "max"),
        sched_rou=("ROU_Asset_Balance", "max")
    ).reset_index()

    gl_liab = gl[gl["Account"].str.contains("Lease", case=False, na=False)]
    gl_rou = gl[gl["Account"].str.contains("ROU", case=False, na=False)]

    leases["schedule_to_GL_liability_diff_flag"] = abs(gl_liab["Ending_Balance"].sum() - lease_totals["sched_liability"].sum()) > 0
    leases["schedule_to_GL_ROU_diff_flag"] = abs(gl_rou["Ending_Balance"].sum() - lease_totals["sched_rou"].sum()) > 0

    leases["incorrect_opening_entry"] = False
    leases["classification_flag"] = False

    leases["risk_score"], leases["risk_level"] = zip(*leases.apply(score_lease_row, axis=1))

    write_output(leases, "Lease_with_risk.csv")
    return leases


# --------------------------------------------------
# MASTER RUNNER
# --------------------------------------------------
def run_pipeline():
    print("\n Starting Peak Power Services Year-End Validator\n")

    ap = validate_ap()
    validate_bank(ap)
    validate_tax()
    validate_leases()

    print("\n Year-end validation pipeline completed successfully.")


if __name__ == "__main__":
    run_pipeline()
