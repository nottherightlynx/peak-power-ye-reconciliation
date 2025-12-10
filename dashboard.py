import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------
st.set_page_config(
    page_title="Peak Power Services - YE Reconciliation Dashboard",
    layout="wide",
    page_icon=None
)

# --------------------------------------------------
# TITLE & PURPOSE CALLOUT
# --------------------------------------------------
st.title("Peak Power Services - YE Reconciliation Dashboard (FY 2025)")

st.caption(
    "Self-service year-end reconciliation dashboard designed to support the Controller, "
    "Billing team, and leadership during close."
)

st.markdown(
    """
    This dashboard provides a single, consolidated view of Peak Power Services’ 2025 year-end
    reconciliation across accounts payable, cash, sales & use tax, and leases.

    It prioritizes higher-risk transactions so review time is focused where adjustments or follow-up
    are most likely required.

    It also surfaces controller-ready summaries and suggested journal entry support to streamline
    close review, documentation, and audit readiness.
    """
)

st.divider()

# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------
@st.cache_data
def load_data():
    ap = pd.read_csv("output/AP_with_risk.csv")
    bank = pd.read_csv("output/Bank_with_risk.csv")
    tax = pd.read_csv("output/Tax_with_risk.csv")
    lease = pd.read_csv("output/Lease_with_risk.csv")
    return ap, bank, tax, lease

ap_df, bank_df, tax_df, lease_df = load_data()

# --------------------------------------------------
# GLOBAL FILTERS
# --------------------------------------------------
st.sidebar.header("Global Filters")

risk_threshold = st.sidebar.slider(
    "Minimum Risk Score",
    min_value=0,
    max_value=100,
    value=60,
    step=5,
    help="Focus the dashboard on higher-risk items."
)

vendor_filter = st.sidebar.multiselect(
    "Vendor",
    sorted(ap_df["Vendor"].dropna().unique())
)

if vendor_filter:
    ap_df = ap_df[ap_df["Vendor"].isin(vendor_filter)]
    bank_df = bank_df[bank_df["Vendor"].isin(vendor_filter)]

# --------------------------------------------------
# EXECUTIVE SCORECARD
# --------------------------------------------------
st.subheader("Executive Close Status")

k1, k2, k3, k4, k5 = st.columns(5)

k1.metric("AP Invoices", f"{len(ap_df):,}")
k2.metric("High-Risk AP", f"{(ap_df['risk_score'] >= risk_threshold).sum():,}")
k3.metric("High-Risk Bank Items", f"{(bank_df['risk_score'] >= risk_threshold).sum():,}")
k4.metric("Tax Exceptions", f"{(tax_df['risk_score'] >= risk_threshold).sum():,}")
k5.metric("Lease Exceptions", f"{(lease_df['risk_score'] >= risk_threshold).sum():,}")

st.divider()

# ==================================================
# SECTION 1 — YEAR-END CLOSE HEALTH (LEADERSHIP)
# ==================================================
st.header(
    "Year-End Close Health Overview", 
    help="High-level view of how many higher-risk items remain in AP, bank, tax, and leases so leadership can assess close readiness."
)

health_df = pd.DataFrame({
    "Area": ["AP", "Bank", "Tax", "Leases"],
    "High Risk Items": [
        (ap_df["risk_score"] >= risk_threshold).sum(),
        (bank_df["risk_score"] >= risk_threshold).sum(),
        (tax_df["risk_score"] >= risk_threshold).sum(),
        (lease_df["risk_score"] >= risk_threshold).sum()
    ]
})

health_fig = px.bar(
    health_df,
    x="Area",
    y="High Risk Items",
    title="High-Risk Items by Close Area",
    color="Area"
)

st.plotly_chart(health_fig, use_container_width=True)

st.caption(
    "This view is designed for senior leadership to quickly see where residual risk is concentrated at year-end."
)

st.divider()

# ==================================================
# SECTION 2 — AP DEEP DIVE
# ==================================================
st.header(
    "AP Reconciliation - Detail & Trend Analysis",
    help="Identifies unpaid invoices, duplicates, GL mismatches, and posting anomalies impacting AP accuracy at year-end."
)


ap_risk_dist = px.histogram(
    ap_df,
    x="risk_score",
    nbins=25,
    title="AP Risk Score Distribution",
)
st.plotly_chart(ap_risk_dist, use_container_width=True)

ap_root_cause = pd.DataFrame({
    "Issue": ["Missing in GL", "Amount Mismatch", "Duplicate Invoice", "Unusual GL"],
    "Count": [
        ap_df["missing_in_GL"].sum(),
        ap_df["amount_mismatch"].sum(),
        ap_df["duplicate_invoice_number"].sum(),
        ap_df["unusual_GL_account"].sum(),
    ]
})

ap_cause_fig = px.pie(
    ap_root_cause,
    names="Issue",
    values="Count",
    title="AP Exception Root Causes"
)

st.plotly_chart(ap_cause_fig, use_container_width=True)

st.subheader("High-Risk AP Invoices")
st.dataframe(
    ap_df[ap_df["risk_score"] >= risk_threshold]
    .sort_values("risk_score", ascending=False),
    use_container_width=True
)

st.divider()

# ==================================================
# SECTION 3 — BANK / CASH CONTROL
# ==================================================
st.header(
    "Cash and Bank Controls",
    help="Highlights vendors and payments with higher cash control risk, including duplicate payments and payments without matching invoices."
)

bank_vendor_fig = px.bar(
    bank_df.groupby("Vendor")["risk_score"].mean().reset_index(),
    x="Vendor",
    y="risk_score",
    title="Average Bank Risk by Vendor"
)
st.plotly_chart(bank_vendor_fig, use_container_width=True)

bank_flags = pd.DataFrame({
    "Issue": ["No Matching Invoice", "Duplicate Payment", "Amount Mismatch"],
    "Count": [
        bank_df["no_matching_invoice"].sum(),
        bank_df["duplicate_payment"].sum(),
        bank_df["amount_mismatch"].sum(),
    ]
})

bank_flag_fig = px.bar(
    bank_flags,
    x="Issue",
    y="Count",
    title="Bank Exception Breakdown"
)

st.plotly_chart(bank_flag_fig, use_container_width=True)

st.subheader("Payments Requiring Review")
st.dataframe(
    bank_df[bank_df["risk_score"] >= risk_threshold]
    .sort_values("risk_score", ascending=False),
    use_container_width=True
)

st.divider()

# ==================================================
# SECTION 4 — SALES & USE TAX (FLORIDA)
# ==================================================
st.header(
    "Sales and Use Tax Compliance — Florida Focus",
    help="Summarizes tax risk by jurisdiction and exception type so the team can validate Florida sales and use tax before filing."
)

tax_juris_fig = px.bar(
    tax_df.groupby("State")["risk_score"].mean().reset_index(),
    x="State",
    y="risk_score",
    title="Average Tax Risk by Jurisdiction"
)
st.plotly_chart(tax_juris_fig, use_container_width=True)

tax_issue_mix = pd.DataFrame({
    "Issue": ["Rate Mismatch", "Missing Tax", "GL Variance"],
    "Count": [
        tax_df["rate_mismatch"].sum(),
        tax_df["tax_missing"].sum(),
        tax_df["gl_tax_diff_flag"].sum(),
    ]
})

tax_issue_fig = px.pie(
    tax_issue_mix,
    names="Issue",
    values="Count",
    title="Tax Compliance Issues"
)
st.plotly_chart(tax_issue_fig, use_container_width=True)

st.subheader("Tax Items Needing Adjustment")
st.dataframe(
    tax_df[tax_df["risk_score"] >= risk_threshold]
    .sort_values("risk_score", ascending=False),
    use_container_width=True
)

st.divider()

# ==================================================
# SECTION 5 — ASC 842 LEASE ACCOUNTING
# ==================================================
st.header(
    "Lease Accounting — ASC 842",
    help="Shows lease-related exceptions such as missing periods and schedule versus general ledger variances for ASC 842 compliance."
)

lease_risk_fig = px.histogram(
    lease_df,
    x="risk_score",
    nbins=20,
    title="Lease Risk Distribution"
)
st.plotly_chart(lease_risk_fig, use_container_width=True)

lease_issues = pd.DataFrame({
    "Issue": ["Missing Periods", "IP Sum Mismatch", "GL Tie-Out Variance"],
    "Count": [
        lease_df["missing_periods"].sum(),
        lease_df["ip_sum_mismatch"].sum(),
        lease_df["schedule_to_GL_liability_diff_flag"].sum(),
    ]
})

lease_issue_fig = px.bar(
    lease_issues,
    x="Issue",
    y="Count",
    title="Lease Exception Breakdown"
)
st.plotly_chart(lease_issue_fig, use_container_width=True)

st.subheader("Lease Records Requiring Review")
st.dataframe(
    lease_df[lease_df["risk_score"] >= risk_threshold]
    .sort_values("risk_score", ascending=False),
    use_container_width=True
)

st.divider()

# ==================================================
# SECTION 6 — JOURNAL ENTRY PREVIEW & EXPORT
# ==================================================
st.header(
    "Journal Entry Preview (Controller Review)",
    help="Builds suggested journal entries from high-risk items to support controller review, approval, and posting."
)

st.markdown(
    "Suggested journal entries derived from higher-risk reconciliation items. "
    "These entries are recommendations only and require controller review before posting."
)

# ---------- Build JE Table ----------
je_rows = []

# AP JEs
high_risk_ap = ap_df[ap_df["risk_score"] >= risk_threshold]
for _, row in high_risk_ap.iterrows():
    if row.get("missing_in_GL"):
        je_rows.append({
            "Source": "AP",
            "Reference": row["Invoice_ID"],
            "Debit_Account": "Project Expense",
            "Credit_Account": "Accounts Payable",
            "Amount": round(row["Expected_Total"], 2),
            "Description": f"Record missing AP invoice {row['Invoice_ID']}"
        })
    elif row.get("amount_mismatch"):
        diff = row["Expected_Total"] - row["Total_Invoice_Amount"]
        if diff > 0:
            je_rows.append({
                "Source": "AP",
                "Reference": row["Invoice_ID"],
                "Debit_Account": "Project Expense",
                "Credit_Account": "Accounts Payable",
                "Amount": round(abs(diff), 2),
                "Description": f"Correct AP under-accrual for invoice {row['Invoice_ID']}"
            })
        else:
            je_rows.append({
                "Source": "AP",
                "Reference": row["Invoice_ID"],
                "Debit_Account": "Accounts Payable",
                "Credit_Account": "Project Expense",
                "Amount": round(abs(diff), 2),
                "Description": f"Correct AP over-accrual for invoice {row['Invoice_ID']}"
            })

# Tax JEs
high_risk_tax = tax_df[tax_df["risk_score"] >= risk_threshold]
for _, row in high_risk_tax.iterrows():
    tax_diff = row["Recalc_Tax"] - row["Calculated_Tax"]
    if abs(tax_diff) > 1:
        je_rows.append({
            "Source": "Tax",
            "Reference": row["Invoice_ID"],
            "Debit_Account": "Sales Tax Expense",
            "Credit_Account": "Sales & Use Tax Payable",
            "Amount": round(abs(tax_diff), 2),
            "Description": f"True-up sales tax for invoice {row['Invoice_ID']}"
        })

# Lease JEs
high_risk_leases = lease_df[lease_df["risk_score"] >= risk_threshold]
for _, row in high_risk_leases.iterrows():
    je_rows.append({
        "Source": "Lease",
        "Reference": row["Lease_ID"],
        "Debit_Account": "Lease Liability",
        "Credit_Account": "Prior Period Adjustment",
        "Amount": round(abs(row["Ending_Lease_Liability"] * 0.01), 2),
        "Description": f"Adjust lease liability for {row['Lease_ID']}"
    })

je_df = pd.DataFrame(je_rows)

# ---------- Display ----------
if je_df.empty:
    st.success("No journal entries required above the selected risk threshold.")
else:
    st.subheader("Suggested Journal Entries")
    st.dataframe(je_df, use_container_width=True)

    # ---------- Export ----------
    st.download_button(
        label="Download Suggested JE CSV",
        data=je_df.to_csv(index=False).encode("utf-8"),
        file_name="Suggested_Journal_Entries_FY2025.csv",
        mime="text/csv"
    )

st.caption(
    "Journal entries are generated from reconciliation findings and are intended for review, approval, and posting by accounting leadership."
)

# --------------------------------------------------
# FOOTER
# --------------------------------------------------
st.caption(
    "Peak Power Services - YE Reconciliation Dashboard supports risk-focused reconciliation, strong internal controls, and leadership-ready reporting."
)
