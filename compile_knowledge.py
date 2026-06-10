"""Compile the supplier PO register into retrieval-ready knowledge documents.

Reads the raw purchase-order CSV and produces two markdown files that get
loaded into the Flowise document store alongside the governance policy PDF:

  knowledge/network_analytics.md   - network-level rollups, each one evaluated
                                     against the policy rule that governs it
  knowledge/supplier_profiles.md   - one profile card per supplier

Usage:
  python compile_knowledge.py [path/to/csv] [output_dir]

Re-run whenever the register changes, then re-upsert the document store.
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "supplier_performance_data.csv"
OUT_DIR = Path(sys.argv[2] if len(sys.argv) > 2 else "knowledge")

# Tier thresholds from the Supplier Governance & Compliance Policy v3.2
TIER_MIN_OTD = {"Tier-1": 93.0, "Tier-2": 84.0, "Tier-3": 75.0}          # §3.1
TIER_MAX_DEFECT = {"Tier-1": 0.99, "Tier-2": 2.50, "Tier-3": 4.00}       # §3.2
TIER_MIN_COMPLIANCE = {"Tier-1": 90, "Tier-2": 75, "Tier-3": 60}         # §2
TIER_MIN_SUSTAIN = {"Tier-1": 80, "Tier-2": 60, "Tier-3": 45}            # §6.1
AUDIT_OVERDUE_MONTHS = {"Tier-1": 14, "Tier-2": 7, "Tier-3": 4}          # §7.1
REGION_CAP_PCT = 45.0                                                     # §5.3
COUNTRY_CAP_PCT = 25.0                                                    # §5.3
SWL_COMPLIANCE_FLOOR = 60                                                 # §3.4
ELTRP_DAYS = 50                                                           # §3.3

# §9 mapping: risk level of a disrupted supplier -> response level
RESPONSE_BY_RISK = {"Low": "Level 1 - Monitor", "Medium": "Level 2 - Manage", "High": "Level 3 - Activate"}


def money(x):
    return f"${x:,.2f}"


def load(path):
    # 'NA' is the North America region code, don't let pandas eat it as NaN
    df = pd.read_csv(path, keep_default_na=False, na_values=[""])
    df["Last_Audit_Date"] = pd.to_datetime(df["Last_Audit_Date"])
    df["has_disruption"] = df["Active_Disruptions"].ne("None")
    qy = df["PO_Quarter"].str.extract(r"Q(\d)-(\d+)").astype(int)
    df["qkey"] = qy[1] * 4 + qy[0]
    return df


def supplier_rollup(df):
    def agg(g):
        risks = g["Risk_Level"].value_counts()
        disruptions = sorted(set(g.loc[g["has_disruption"], "Active_Disruptions"]))
        latest = g[g["qkey"] == g["qkey"].max()]
        current = sorted(set(latest.loc[latest["has_disruption"], "Active_Disruptions"]))
        return pd.Series({
            "name": g["Supplier_Name"].iloc[0],
            "tier": g["Contract_Tier"].iloc[0],
            "region": g["Region"].iloc[0],
            "country": g["Country"].iloc[0],
            "categories": ", ".join(sorted(set(g["Product_Category"]))),
            "otd": g["OTD_Rate_Pct"].mean(),
            "defect": g["Defect_Rate_Pct"].mean(),
            "compliance": g["Compliance_Score"].mean(),
            "sustainability": g["Sustainability_Score"].mean(),
            "min_compliance": g["Compliance_Score"].min(),
            "risk": risks.idxmax(),
            "risk_mix": ", ".join(f"{k} ({v} POs)" for k, v in risks.items()),
            "disruptions": "; ".join(disruptions) if disruptions else "None",
            "current_disruptions": "; ".join(current) if current else "None",
            "latest_quarter": latest["PO_Quarter"].iloc[0],
            "n_disruption_types": len(disruptions),
            "certs": g["Certifications"].iloc[0],
            "alt": g["Alt_Supplier_ID"].iloc[0],
            "lead_time": g["Lead_Time_Days"].mean(),
            "last_audit": g["Last_Audit_Date"].max(),
            "po_count": len(g),
            "po_value": g["PO_Value_USD"].sum(),
        })
    return df.groupby("Supplier_ID").apply(agg, include_groups=False).reset_index()


def response_level(row):
    # §9: two simultaneous disruption flags force Level 3 regardless of risk
    if row["n_disruption_types"] >= 2:
        return "Level 3 - Activate (multiple simultaneous disruption flags)"
    return RESPONSE_BY_RISK[row["risk"]]


def build_analytics(df, sup, as_of):
    total = df["PO_Value_USD"].sum()
    lines = []
    w = lines.append

    w("# BQBYTE Supplier Network - Computed Analytics Register")
    w("")
    w(f"Compiled from the supplier performance data register ({len(df):,} purchase orders, "
      f"{df['Supplier_ID'].nunique()} suppliers). Reference date for audit-age checks: {as_of:%d %b %Y} "
      f"(latest audit date present in the register). All figures below are computed directly from the "
      f"register and evaluated against Supplier Governance & Compliance Policy v3.2.")
    w("")
    w("This document is the authoritative source for network-level aggregate questions "
      "(totals, counts, averages, rankings, threshold breaches). Per-supplier detail lives in "
      "the supplier profile cards; rule definitions live in the policy document.")

    # ---- network overview ----
    w("")
    w("## 1. Network Overview")
    w("")
    w(f"- Total purchase orders: {len(df):,}")
    w(f"- Active suppliers: {df['Supplier_ID'].nunique()}")
    w(f"- Total PO value (network spend): {money(total)}")
    tiers = sup["tier"].value_counts()
    w(f"- Suppliers by tier: " + ", ".join(f"{t}: {tiers.get(t, 0)}" for t in ["Tier-1", "Tier-2", "Tier-3"]))
    w(f"- Regions: {', '.join(sorted(df['Region'].unique()))} | Countries: {df['Country'].nunique()}")
    w(f"- Product categories: {', '.join(sorted(df['Product_Category'].unique()))}")
    n_ever = int((sup["disruptions"] != "None").sum())
    n_now = int((sup["current_disruptions"] != "None").sum())
    w(f"- Suppliers with at least one disruption flag recorded in the register: {n_ever}; "
      f"suppliers still carrying a flag in their most recent quarter of activity: {n_now}")

    # ---- regional concentration §5.3 ----
    w("")
    w("## 2. Regional & Country Spend Concentration (Policy §5.3)")
    w("")
    w(f"Policy §5.3: no single region may exceed {REGION_CAP_PCT:.0f}% of total annual procurement spend; "
      f"no single country may exceed {COUNTRY_CAP_PCT:.0f}%. Breach requires a Diversification Plan within 60 days.")
    w("")
    w("Total spend by region (computed):")
    w("")
    reg = df.groupby("Region")["PO_Value_USD"].sum().sort_values(ascending=False)
    for r, v in reg.items():
        pct = v / total * 100
        flag = " - **BREACH of the 45% regional cap**" if pct > REGION_CAP_PCT else " (within the 45% cap)"
        w(f"- {r}: {money(v)} = {pct:.2f}% of total spend{flag}")
    top_r = reg.index[0]
    top_pct = reg.iloc[0] / total * 100
    verdict = ("breaches" if top_pct > REGION_CAP_PCT else "does NOT breach")
    w("")
    w(f"**The region with the highest total PO value is {top_r} at {money(reg.iloc[0])}, "
      f"which is {top_pct:.2f}% of total network spend ({money(total)}). This {verdict} the "
      f"{REGION_CAP_PCT:.0f}% regional concentration cap of Policy §5.3.**"
      + ("" if top_pct > REGION_CAP_PCT else " No Diversification Plan is triggered by regional concentration."))
    w("")
    w("Country concentration (top 5, vs the 25% country cap):")
    w("")
    cty = df.groupby("Country")["PO_Value_USD"].sum().sort_values(ascending=False)
    for c, v in cty.head(5).items():
        pct = v / total * 100
        flag = " - **BREACH of the 25% country cap (Diversification Plan required within 60 days)**" if pct > COUNTRY_CAP_PCT else " (within the 25% cap)"
        w(f"- {c}: {money(v)} = {pct:.2f}%{flag}")

    # ---- category defect rates §3.2 ----
    w("")
    w("## 3. Defect Rate by Product Category (Policy §3.2)")
    w("")
    w("Policy §3.2 defect ceilings: Tier-1 max 0.99%, Tier-2 max 2.50%, Tier-3 max 4.00%. "
      "Any single shipment above 8.0% triggers immediate hold + RCA in 5 business days.")
    w("")
    w("Average defect rate per category, computed across all POs in the register:")
    w("")
    cat = df.groupby("Product_Category")["Defect_Rate_Pct"].agg(["mean", "count"]).sort_values("mean", ascending=False)
    for c, row in cat.iterrows():
        w(f"- {c}: average {row['mean']:.2f}% across {int(row['count'])} POs")
    top_c = cat.index[0]
    top_def = cat.iloc[0]["mean"]
    vs_t2 = "exceeds" if top_def > TIER_MAX_DEFECT["Tier-2"] else "is below"
    w("")
    w(f"**The product category with the highest average defect rate is {top_c} at {top_def:.2f}% "
      f"(across {int(cat.iloc[0]['count'])} POs). This {vs_t2} the Tier-2 defect ceiling of "
      f"{TIER_MAX_DEFECT['Tier-2']:.2f}% defined in Policy §3.2.**")

    # ---- SWL §3.4 ----
    w("")
    w("## 4. Supplier Watch List - SWL (Policy §3.4)")
    w("")
    w(f"Policy §3.4: any supplier with a Compliance Score below {SWL_COMPLIANCE_FLOOR} is placed on "
      f"Supplier Watch List (SWL) status regardless of tier. SWL restricts new PO issuance to 20% of "
      f"prior quarter volume.")
    w("")
    swl = sup[sup["compliance"] < SWL_COMPLIANCE_FLOOR].sort_values("compliance")
    if len(swl):
        w(f"**{len(swl)} supplier(s) are on SWL status (average Compliance Score below {SWL_COMPLIANCE_FLOOR}):**")
        w("")
        for _, s in swl.iterrows():
            w(f"- {s['name']} ({s['Supplier_ID']}, {s['tier']}, {s['country']}) - average Compliance Score {s['compliance']:.1f}")
    else:
        w("**No supplier currently has an average Compliance Score below 60, so no supplier is on full SWL status.**")
    borderline = sup[(sup["compliance"] >= SWL_COMPLIANCE_FLOOR) & (sup["min_compliance"] < SWL_COMPLIANCE_FLOOR)]
    if len(borderline):
        w("")
        w(f"Borderline ({len(borderline)} suppliers recorded at least one PO with Compliance Score below 60 "
          f"although their average stays at or above 60 - candidates for provisional review):")
        w("")
        for _, s in borderline.sort_values("min_compliance").iterrows():
            w(f"- {s['name']} ({s['Supplier_ID']}, {s['tier']}) - average {s['compliance']:.1f}, lowest recorded {s['min_compliance']:.0f}")

    # ---- volume rebate §4.2 ----
    w("")
    w("## 5. Volume Rebate Program Qualification (Policy §4.2)")
    w("")
    w("Policy §4.2 criteria (Tier-1 only): OTD >= 93.0%, Defect Rate < 0.5%, Sustainability Score >= 85 "
      "for a full calendar year. Qualifying suppliers earn an annual rebate of 2.5% of total annual invoice value.")
    w("")
    t1 = sup[sup["tier"] == "Tier-1"]
    reb = t1[(t1["otd"] >= 93.0) & (t1["defect"] < 0.5) & (t1["sustainability"] >= 85)]
    if len(reb):
        w(f"**{len(reb)} Tier-1 supplier(s) qualify for the annual Volume Rebate Program:**")
        w("")
        for _, s in reb.sort_values("name").iterrows():
            w(f"- {s['name']} ({s['Supplier_ID']}) - OTD {s['otd']:.1f}%, defect {s['defect']:.2f}%, sustainability {s['sustainability']:.0f}")
    else:
        w("**Based on average metrics in the current register, NO Tier-1 supplier meets all three §4.2 "
          "criteria simultaneously, so no supplier currently qualifies for the Volume Rebate Program.**")
        w("")
        near = t1[(t1["otd"] >= 93.0) & (t1["sustainability"] >= 85)].sort_values("defect")
        if len(near):
            w("Closest candidates (meet the OTD and sustainability bars but miss the <0.5% defect bar):")
            w("")
            for _, s in near.head(8).iterrows():
                w(f"- {s['name']} ({s['Supplier_ID']}) - OTD {s['otd']:.1f}%, defect {s['defect']:.2f}%, sustainability {s['sustainability']:.0f}")

    # ---- disruption response §9 ----
    w("")
    w("## 6. Active Disruptions & Response Levels (Policy §9)")
    w("")
    w("Policy §9 response levels for suppliers with an active disruption flag: Low Risk -> Level 1 Monitor "
      "(+15% safety stock), Medium Risk -> Level 2 Manage (+30% safety stock, alternate on 48h notice), "
      "High Risk or two simultaneous flags -> Level 3 Activate (CPO escalation, alternate supplier activated "
      "for minimum 40% of volume within 10 business days, +50% safety stock, RCA within 15 business days). "
      "Export control restrictions, active labour strikes, regulatory enforcement actions and port closures "
      "over 72h force Level 3 regardless of risk level.")
    disrupted = sup[sup["disruptions"] != "None"].copy()
    disrupted["response"] = disrupted.apply(response_level, axis=1)
    for tier in ["Tier-1", "Tier-2", "Tier-3"]:
        block = disrupted[disrupted["tier"] == tier].sort_values("name")
        w("")
        w(f"### {tier} suppliers with an active disruption flag ({len(block)})")
        w("")
        if not len(block):
            w(f"No {tier} suppliers currently carry an active disruption flag.")
            continue
        for _, s in block.iterrows():
            still = (" [flag still present in its latest quarter, " + s["latest_quarter"] + "]"
                     if s["current_disruptions"] != "None" else " [no flag in its latest quarter]")
            w(f"- {s['name']} ({s['Supplier_ID']}, {s['country']}, predominant risk: {s['risk']}) - "
              f"disruption(s): {s['disruptions']} -> **{s['response']}**{still}")
        roster = ", ".join(block["name"])
        w("")
        w(f"**Full {tier} roster with an active disruption flag ({len(block)} suppliers): {roster}.**")
        if tier == "Tier-3":
            lvl3 = block[block["response"].str.startswith("Level 3")]
            w("")
            w(f"**Summary: {len(block)} Tier-3 suppliers carry an active disruption flag; "
              f"{len(lvl3)} of them require Level 3 - Activate per Policy §9 "
              f"(CPO escalation + alternate supplier at minimum 40% volume).**")

    # ---- audit overdue §7.1 ----
    w("")
    w("## 7. Audit Status (Policy §7.1)")
    w("")
    w(f"Overdue thresholds: Tier-1 > 14 months, Tier-2 > 7 months, Tier-3 > 4 months since last audit. "
      f"Overdue suppliers go on provisional SWL status. Ages computed as of {as_of:%d %b %Y}.")
    w("")
    sup2 = sup.copy()
    sup2["audit_months"] = (as_of - sup2["last_audit"]).dt.days / 30.44
    sup2["overdue_by"] = sup2.apply(lambda s: s["audit_months"] - AUDIT_OVERDUE_MONTHS[s["tier"]], axis=1)
    over = sup2[sup2["overdue_by"] > 0].sort_values("overdue_by", ascending=False)
    w(f"**{len(over)} of {len(sup2)} suppliers are Audit Overdue (provisional SWL per §7.1).** Worst 15:")
    w("")
    for _, s in over.head(15).iterrows():
        w(f"- {s['name']} ({s['Supplier_ID']}, {s['tier']}) - last audited {s['last_audit']:%Y-%m-%d}, "
          f"{s['audit_months']:.1f} months ago (threshold {AUDIT_OVERDUE_MONTHS[s['tier']]} months)")

    # ---- OTD penalty exposure §4.1 ----
    w("")
    w("## 8. OTD Performance & Penalty Exposure (Policy §4.1 / §3.1)")
    w("")
    w("Tier OTD floors (§3.1): Tier-1 >= 93%, Tier-2 >= 84%, Tier-3 >= 75%. Suppliers whose average OTD "
      "sits below their tier floor:")
    w("")
    below = sup[sup.apply(lambda s: s["otd"] < TIER_MIN_OTD[s["tier"]], axis=1)].sort_values("otd")
    w(f"**{len(below)} suppliers are below their tier OTD floor.** Worst 15:")
    w("")
    for _, s in below.head(15).iterrows():
        w(f"- {s['name']} ({s['Supplier_ID']}, {s['tier']}) - average OTD {s['otd']:.1f}% "
          f"(floor {TIER_MIN_OTD[s['tier']]:.0f}%)")
    w("")
    w("§4.1 penalty bands (quarterly, % of quarterly invoice): below 70% -> 8% all tiers + CAP; "
      "70-74.9% -> 5% (Tier-1); 75-79.9% -> 3.5% (Tier-1/2); 80-83.9% -> 2% (Tier-1); "
      "84-86.9% -> 1% (Tier-1); 87% and above -> no penalty.")

    # ---- lead time §3.3 ----
    w("")
    w("## 9. Extended Lead Times (Policy §3.3 - ELTRP)")
    w("")
    longest = sup.sort_values("lead_time", ascending=False).head(10)
    over50 = sup[sup["lead_time"] > ELTRP_DAYS]
    w(f"Lead times above {ELTRP_DAYS} calendar days fall under the Extended Lead Time Review Protocol. "
      f"**{len(over50)} suppliers exceed {ELTRP_DAYS} days on average.** Longest 10:")
    w("")
    for _, s in longest.iterrows():
        flag = " - **subject to ELTRP review**" if s["lead_time"] > ELTRP_DAYS else ""
        w(f"- {s['name']} ({s['Supplier_ID']}, {s['tier']}) - average lead time {s['lead_time']:.0f} days{flag}")

    # ---- spend by quarter / category ----
    w("")
    w("## 10. Spend Rollups")
    w("")
    w("Spend by quarter:")
    w("")
    q = df.groupby("PO_Quarter")["PO_Value_USD"].sum()
    for k, v in q.items():
        w(f"- {k}: {money(v)}")
    w("")
    w("Spend by product category:")
    w("")
    pc = df.groupby("Product_Category")["PO_Value_USD"].sum().sort_values(ascending=False)
    for k, v in pc.items():
        w(f"- {k}: {money(v)} ({v / total * 100:.1f}%)")
    w("")
    w("Top 10 suppliers by total PO value:")
    w("")
    for _, s in sup.sort_values("po_value", ascending=False).head(10).iterrows():
        w(f"- {s['name']} ({s['Supplier_ID']}, {s['tier']}, {s['region']}) - {money(s['po_value'])} across {s['po_count']} POs")

    return "\n".join(lines) + "\n"


def build_profiles(sup, as_of):
    lines = []
    w = lines.append
    w("# Supplier Profile Cards")
    w("")
    w(f"One card per supplier, aggregated from all purchase orders in the register (as of {as_of:%d %b %Y}). "
      f"Metric values are averages across the supplier's POs.")
    for _, s in sup.sort_values("name").iterrows():
        w("")
        w(f"## {s['name']} ({s['Supplier_ID']})")
        w("")
        w(f"{s['name']} is a {s['tier']} supplier based in {s['country']} ({s['region']} region), "
          f"supplying {s['categories']}. Across {s['po_count']} purchase orders totalling {money(s['po_value'])}, "
          f"it averages an on-time delivery rate of {s['otd']:.1f}%, a defect rate of {s['defect']:.2f}%, "
          f"a compliance score of {s['compliance']:.1f} and a sustainability score of {s['sustainability']:.1f}.")
        w("")
        w(f"- Risk level (predominant): {s['risk']} (history: {s['risk_mix']})")
        w(f"- Disruption flags recorded: {s['disruptions']}")
        w(f"- Disruption flags in most recent quarter ({s['latest_quarter']}): {s['current_disruptions']}")
        w(f"- Certifications: {s['certs'].replace(';', ', ')}")
        w(f"- Designated alternate supplier: {s['alt']}")
        w(f"- Average lead time: {s['lead_time']:.0f} days | Last audit: {s['last_audit']:%Y-%m-%d}")
    return "\n".join(lines) + "\n"


def main():
    df = load(CSV_PATH)
    sup = supplier_rollup(df)
    as_of = df["Last_Audit_Date"].max()

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "network_analytics.md").write_text(build_analytics(df, sup, as_of), encoding="utf-8")
    (OUT_DIR / "supplier_profiles.md").write_text(build_profiles(sup, as_of), encoding="utf-8")

    print(f"compiled {len(df):,} POs / {len(sup)} suppliers")
    print(f"wrote {OUT_DIR / 'network_analytics.md'}")
    print(f"wrote {OUT_DIR / 'supplier_profiles.md'}")


if __name__ == "__main__":
    main()
