"""Sanity-check the compiled knowledge against independent recomputation.

Recomputes the answer to each of the five case-study questions straight from
the CSV (separately from compile_knowledge.py) and asserts the figures appear
in knowledge/network_analytics.md. Prints the answer key for this data cut.

Note: the sample answers printed in the case-study PDF were computed from a
different cut of the data (different totals, different rankings). The provided
CSV is the authoritative source here, so the bot is validated against it.
"""

from pathlib import Path

import pandas as pd

df = pd.read_csv("supplier_performance_data.csv", keep_default_na=False, na_values=[""])
md = Path("knowledge/network_analytics.md").read_text(encoding="utf-8")

failures = []


def check(label, fragment):
    ok = fragment in md
    print(f"  [{'OK' if ok else 'MISSING'}] {fragment}")
    if not ok:
        failures.append(f"{label}: {fragment}")


# Q1 - Tier-3 suppliers with an active disruption flag -> §9 response level
disrupted = df[df["Active_Disruptions"] != "None"]
t3 = sorted(disrupted.loc[disrupted["Contract_Tier"] == "Tier-3", "Supplier_Name"].unique())
print(f"\nQ1: {len(t3)} Tier-3 suppliers with an active disruption flag:")
print("    " + ", ".join(t3))
check("Q1", f"### Tier-3 suppliers with an active disruption flag ({len(t3)})")
for name in t3:
    check("Q1", name)

# Q2 - Volume Rebate qualifiers (§4.2): Tier-1, OTD>=93, defect<0.5, sustainability>=85
sup = df.groupby(["Supplier_ID", "Supplier_Name", "Contract_Tier"]).agg(
    otd=("OTD_Rate_Pct", "mean"),
    defect=("Defect_Rate_Pct", "mean"),
    sust=("Sustainability_Score", "mean"),
    comp=("Compliance_Score", "mean"),
).reset_index()
reb = sup[(sup["Contract_Tier"] == "Tier-1") & (sup["otd"] >= 93) & (sup["defect"] < 0.5) & (sup["sust"] >= 85)]
print(f"\nQ2: {len(reb)} suppliers qualify for the Volume Rebate Program")
if len(reb):
    print("    " + ", ".join(sorted(reb["Supplier_Name"])))
    check("Q2", f"{len(reb)} Tier-1 supplier(s) qualify")
else:
    check("Q2", "NO Tier-1 supplier meets all three")

# Q3 - region with highest total PO value vs the 45% cap (§5.3)
total = df["PO_Value_USD"].sum()
reg = df.groupby("Region")["PO_Value_USD"].sum().sort_values(ascending=False)
top_region, top_value = reg.index[0], reg.iloc[0]
pct = top_value / total * 100
breach = "BREACHES" if pct > 45 else "does NOT breach"
print(f"\nQ3: {top_region} at ${top_value:,.2f} = {pct:.2f}% of ${total:,.2f} -> {breach} the 45% cap")
check("Q3", f"{top_region} at ${top_value:,.2f}")
check("Q3", f"{pct:.2f}% of total network spend (${total:,.2f})")

# Q4 - SWL suppliers (§3.4): average Compliance Score below 60
swl = sup[sup["comp"] < 60]
print(f"\nQ4: {len(swl)} suppliers on SWL (avg Compliance Score < 60)")
if len(swl):
    print("    " + ", ".join(sorted(swl["Supplier_Name"])))
    check("Q4", f"{len(swl)} supplier(s) are on SWL status")
    for name in sorted(swl["Supplier_Name"]):
        check("Q4", name)
else:
    check("Q4", "no supplier is on full SWL status")

# Q5 - category with highest average defect rate vs Tier-2 ceiling (§3.2)
cat = df.groupby("Product_Category")["Defect_Rate_Pct"].agg(["mean", "count"]).sort_values("mean", ascending=False)
top_cat, top_def, n = cat.index[0], cat.iloc[0]["mean"], int(cat.iloc[0]["count"])
verdict = "exceeds" if top_def > 2.5 else "is below"
print(f"\nQ5: {top_cat} at {top_def:.2f}% across {n} POs -> {verdict} the 2.50% Tier-2 ceiling")
check("Q5", f"{top_cat} at {top_def:.2f}%")
check("Q5", f"across {n} POs")

print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILURES:"))
for f in failures:
    print("  - " + f)
raise SystemExit(1 if failures else 0)
