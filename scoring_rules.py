# scoring_rules.py

import numpy as np

# -------------------------
# Generic risk band mapper
# -------------------------
def classify_risk(score: float) -> str:
    if score <= 20:
        return "Low (5–15%)"
    elif score <= 40:
        return "Medium (20–40%)"
    elif score <= 70:
        return "High (50–80%)"
    else:
        return "Critical (85–99%)"


# ============================================================
# MODEL A – AP ↔ GL discrepancy risk (per INVOICE)
# ============================================================
def score_ap_row(row) -> tuple[float, str]:
    """
    Expects flags pre-computed in the row:
      - missing_in_GL (bool)
      - amount_mismatch (bool)
      - late_posting (bool)
      - duplicate_invoice_number (bool)
      - unusual_GL_account (bool)
    """
    score = 5  # base risk

    missing_in_GL = bool(row.get("missing_in_GL", False))
    amount_mismatch = bool(row.get("amount_mismatch", False))
    late_posting = bool(row.get("late_posting", False))
    duplicate = bool(row.get("duplicate_invoice_number", False))
    unusual_gl = bool(row.get("unusual_GL_account", False))

    if late_posting:
        score += 10          # late_posting only → 10

    if amount_mismatch:
        score += 30          # amount_mismatch only → 30

    if unusual_gl:
        score += 25          # unusual_GL_account only → 25

    if duplicate:
        score += 40          # duplicate_invoice_number only → 40

    if missing_in_GL:
        score += 60          # missing_in_GL only → 60

        # missing_in_GL + any other flag → bump
        if amount_mismatch or duplicate or late_posting or unusual_gl:
            score += 20      # pushes to 80+

    # 3 or more flags (any combo) → 90+
    flags = sum([missing_in_GL, amount_mismatch, late_posting, duplicate, unusual_gl])
    if flags >= 3:
        score = max(score, 90)

    score = min(score, 100)
    return score, classify_risk(score)


# ============================================================
# MODEL B – Bank ↔ AP/Cash discrepancy risk (per PAYMENT)
# ============================================================
def score_bank_row(row) -> tuple[float, str]:
    """
    Expects flags:
      - no_matching_invoice (bool)
      - invoice_marked_paid_but_no_bank_txn (bool)  [optional]
      - duplicate_payment (bool)
      - amount_mismatch (bool)
      - unusual_vendor_payment (bool)
    """
    score = 5

    no_match = bool(row.get("no_matching_invoice", False))
    inv_paid_no_bank = bool(row.get("invoice_marked_paid_but_no_bank_txn", False))
    duplicate_payment = bool(row.get("duplicate_payment", False))
    amount_mismatch = bool(row.get("amount_mismatch", False))
    unusual_vendor = bool(row.get("unusual_vendor_payment", False))

    if unusual_vendor:
        score += 10

    if amount_mismatch:
        score += 25

    if inv_paid_no_bank:
        score += 40

    if no_match:
        score += 50

    if duplicate_payment:
        score += 60

    # duplicate_payment + amount_mismatch
    if duplicate_payment and amount_mismatch:
        score += 15  # bump to ~75 total

    # no_matching_invoice + any other flag
    if no_match and (duplicate_payment or amount_mismatch or unusual_vendor or inv_paid_no_bank):
        score += 20

    flags = sum([no_match, inv_paid_no_bank, duplicate_payment, amount_mismatch, unusual_vendor])
    if flags >= 3:
        score = max(score, 90)

    score = min(score, 100)
    return score, classify_risk(score)


# ============================================================
# MODEL C – Sales & Use Tax discrepancy risk (per INVOICE)
# ============================================================
def score_tax_row(row) -> tuple[float, str]:
    """
    Expects flags:
      - rate_mismatch (bool)
      - tax_missing (bool)
      - tax_on_nontaxable_item (bool)
      - jurisdiction_missing (bool)
      - gl_tax_diff_flag (bool)   [period-level GL vs invoices diff]
    And numeric:
      - tax_diff_abs (float)
    """
    score = 5

    rate_mismatch = bool(row.get("rate_mismatch", False))
    tax_missing = bool(row.get("tax_missing", False))
    tax_on_non_taxable = bool(row.get("tax_on_nontaxable_item", False))
    jurisdiction_missing = bool(row.get("jurisdiction_missing", False))
    gl_tax_diff_flag = bool(row.get("gl_tax_diff_flag", False))
    tax_diff_abs = float(row.get("tax_diff_abs", 0.0))

    if jurisdiction_missing:
        score += 15

    if rate_mismatch:
        score += 30

    if tax_missing:
        score += 40

    if tax_on_non_taxable:
        score += 35

    # GL tax diff at period level
    if gl_tax_diff_flag:
        score += 25

    # If per-invoice dollar diff is also large, bump
    if tax_diff_abs > 5:
        score += 10

    # combos
    if tax_missing and rate_mismatch:
        score += 65

    if tax_missing and gl_tax_diff_flag:
        score += 70

    if tax_on_non_taxable and rate_mismatch:
        score += 60

    flags = sum([
        rate_mismatch,
        tax_missing,
        tax_on_non_taxable,
        jurisdiction_missing,
        gl_tax_diff_flag,
    ])
    if flags >= 3:
        score = max(score, 85)

    score = min(score, 100)
    return score, classify_risk(score)


# ============================================================
# MODEL D – Lease (ASC 842) discrepancy risk (per LEASE LINE)
# ============================================================
def score_lease_row(row) -> tuple[float, str]:
    """
    Expects flags:
      - schedule_to_GL_liability_diff_flag (bool)
      - schedule_to_GL_ROU_diff_flag (bool)
      - missing_periods (bool)
      - incorrect_opening_entry (bool)  [optional, if modeled]
      - classification_flag (bool)      [optional, if modeled]
      - ip_sum_mismatch (bool)
    """
    score = 5

    liab_diff_flag = bool(row.get("schedule_to_GL_liability_diff_flag", False))
    rou_diff_flag = bool(row.get("schedule_to_GL_ROU_diff_flag", False))
    missing_periods = bool(row.get("missing_periods", False))
    incorrect_opening = bool(row.get("incorrect_opening_entry", False))
    classification_flag = bool(row.get("classification_flag", False))
    ip_mismatch = bool(row.get("ip_sum_mismatch", False))

    # small differences <2% would get 20, but we don't have per-lease % here,
    # so we treat our boolean flags as "material enough to look at"
    if liab_diff_flag:
        score += 20

    if rou_diff_flag:
        score += 20

    if missing_periods:
        score += 40

    if incorrect_opening:
        score += 50

    if classification_flag:
        score += 45

    if ip_mismatch:
        score += 50

    # combos
    if liab_diff_flag and missing_periods:
        score += 30  # pushes toward 70+

    if rou_diff_flag and incorrect_opening:
        score += 35

    flags = sum([
        liab_diff_flag,
        rou_diff_flag,
        missing_periods,
        incorrect_opening,
        classification_flag,
        ip_mismatch,
    ])
    if flags >= 3:
        score = max(score, 90)

    score = min(score, 100)
    return score, classify_risk(score)
