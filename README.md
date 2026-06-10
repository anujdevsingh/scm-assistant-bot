# SCM Assistant — Supply Chain RAG Chatbot (Flowise)

Trinamix Junior AI Engineer hiring task (Ref: TX-JrAI-003).

A RAG chatbot built on Flowise Cloud that answers questions about the BQBYTE supplier network using the two provided files: a 2,000-row purchase order register (116 suppliers) and the Supplier Governance & Compliance Policy v3.2.

**Public chatbot URL:** https://cloud.flowiseai.com/chatbot/7d1943bf-d0a0-4910-879c-6331fe830b26

---

## The problem with the obvious approach

I started by testing the straightforward build: load the CSV and PDF into a document store, chunk, embed, retrieve, answer. It worked for lookups ("tell me about Orrentek Precision Mfg") and policy questions, but it failed exactly where the sample questions live: aggregations. "Which region has the highest total PO value?" can't be answered by retrieving 10 chunks out of 2,000 rows — no chunk contains the sum. The LLM either refuses or, worse, makes up a plausible number.

So I added a compile step before the document store — the same pattern I'd used in a previous legal-RAG project (precompute what retrieval can't derive, keep the LLM grounded in retrievable facts):

```
supplier_performance_data.csv
        |
        v
compile_knowledge.py  (pandas; runs locally, deterministic)
        |
        +--> knowledge/network_analytics.md    regional spend vs the 45% cap (5.3),
        |                                      category defect averages vs tier ceilings (3.2),
        |                                      SWL list (3.4), rebate qualifiers (4.2),
        |                                      disruption x response-level matrix (9),
        |                                      audit overdue (7.1), OTD penalty exposure (4.1)...
        |
        +--> knowledge/supplier_profiles.md    one prose card per supplier (116 cards)

Document Store (4 lanes):  policy PDF | analytics register | profile cards | raw CSV rows
        |
        v
OpenAI text-embedding-3-small  ->  Pinecone (serverless, cosine, 1536-dim)
        |
        v
Conversational Retrieval QA Chain  ->  gpt-5.5, temperature 0
```

Every analytics section names the policy rule it was evaluated against, so a single retrieved chunk carries the figure *and* the citation. The raw CSV rows stay in the store as their own lane, so row-level questions still answer from the actual data. Nothing is hardcoded: `compile_knowledge.py` takes the CSV path as an argument — new data cut, re-run, re-upsert, done. `verify_answers.py` recomputes the five case-study answers independently and asserts they appear in the generated markdown before anything gets uploaded.

## A note on the sample answers in the brief

The expected answers printed in the case study PDF do not match the CSV I was given. The same supplier names exist in both, but every numeric value differs — the brief says EMEA leads at $193.9M of a $399.5M total and breaches the 45% cap; my register sums to $356,045,248.18 total with APAC leading at 36.97% and no breach. A raw column sum has no definitional wiggle room, so I treated the provided CSV as the authoritative source (the policy document itself says the data register is authoritative for quantitative metrics), computed the real answers from it, and validated the bot against those. The chatbot's answers below are correct for the data provided to me.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Platform | Flowise Cloud | required by the brief |
| LLM | `gpt-5.5`, temperature 0 | latest OpenAI flagship at submission time; temp 0 for reproducible, audit-friendly answers |
| Embeddings | `text-embedding-3-small` (1536-dim) | current OpenAI embedding generation; the corpus is written to match query phrasing, so 3-large buys nothing here |
| Vector store | Pinecone serverless (cosine) | free tier, zero infra to keep alive during evaluation, persists indefinitely |
| Retrieval | similarity, top K 15 | corpus is curated and deduplicated by construction, so MMR diversity would only displace needed chunks |
| Data pipeline | pandas (`compile_knowledge.py`) | deterministic offline aggregation; LLMs shouldn't do arithmetic in front of users |

## Chunk configuration experiments

The brief asks for two configurations. I measured both on every file:

| File | Splitter | Config A: 1500 chars / 200 overlap | Config B: 700 chars / 100 overlap |
|---|---|---|---|
| Policy PDF | Recursive Character | **13 chunks** | 24 chunks |
| network_analytics.md | Markdown | **43 chunks** | 110 chunks |
| supplier_profiles.md | Markdown | **108 chunks** | 229 chunks |
| supplier CSV | none (row per chunk) | 2,000 | 2,000 |

**Config A won, and the 700/100 preview showed exactly why:** at 700 characters the supplier profile cards get severed from their headings — chunks of orphaned bullets ("Certifications: ... Designated alternate supplier: ...") with no supplier name attached. A retriever that fetches that chunk hands the LLM facts it cannot attribute. At 1500/200, every policy rule, every analytics section, and every profile card survives as one self-contained retrievable unit. For structured documents the deciding question isn't "big or small chunks" — it's "does one chunk hold one complete unit of meaning."

(I also considered 1000/200 as a middle ground and rejected it on the same evidence: the larger profile cards exceed 1,000 characters.)

One retrieval lesson worth recording: my first pass at the Tier-3 disruption question returned the correct count but only a partial name list — the 24-supplier list spanned three chunks and top-K retrieval fetched only part of it. Rather than inflating top K further, I changed the data: the compiler now emits a one-paragraph full roster inside the section summary, so the #1-ranked chunk alone carries the complete answer. When retrieval misses, fix the corpus before tuning the knobs.

## The five validation questions, answered verbatim by the deployed bot

**Q1 — Which Tier-3 suppliers have an active disruption flag, and what response level applies per policy?**

> 24 Tier-3 suppliers have an active disruption flag, and all 24 require "Level 3 - Activate" per Policy §9.
>
> - Archipelago PCB Corp — Level 3 - Activate
> - Bogota Pack Ltda — Level 3 - Activate
> - Bohai Electronics — Level 3 - Activate
> - Buenos Aires Pack — Level 3 - Activate
> - Cerromax Mineria — Level 3 - Activate
> - DaNang Metal Works — Level 3 - Activate
> - Deccan Polymer Mfg — Level 3 - Activate
> - Deltaforge Vietnam — Level 3 - Activate
> - Dravex Components India — Level 3 - Activate
> - Helios Pack Greece — Level 3 - Activate
> - Lima Polymer SA — Level 3 - Activate
> - Longhua Polymer Works — Level 3 - Activate
> - Maghreb Castworks — Level 3 - Activate
> - MeKong Pack Co — Level 3 - Activate
> - Orinoco Pack SAPI — Level 3 - Activate
> - Patagonia Alloys SRL — Level 3 - Activate
> - Plataforma Metales SA — Level 3 - Activate
> - Quetzal Textiles — Level 3 - Activate
> - Sahyadri Alloy Tech — Level 3 - Activate
> - Sibertek Molding — Level 3 - Activate
> - Varna Electronics EAD — Level 3 - Activate
> - Visayas Textile Co — Level 3 - Activate
> - Vistula Pack Sp — Level 3 - Activate
> - Yucatan Polymer Mfg — Level 3 - Activate
>
> Per Policy §9, Level 3 requires CPO escalation, alternate supplier activated for minimum 40% of volume within 10 business days, +50% safety stock, and full RCA within 15 business days.

**Q2 — Which suppliers qualify for the annual Volume Rebate Program and how many are there?**

> No suppliers currently qualify for the annual Volume Rebate Program — 0 suppliers.
>
> Per Policy §4.2, eligibility is Tier-1 only and requires OTD at or above 93.0%, Defect Rate below 0.5%, and Sustainability Score at or above 85 for a full calendar year. The computed register states that no Tier-1 supplier meets all three §4.2 criteria simultaneously, so no supplier currently qualifies.

**Q3 — Which region has the highest total PO value, and does it breach the concentration limit?**

> APAC has the highest total PO value at $131,620,356.14, and it does not breach the concentration limit.
>
> Supporting detail:
> - APAC: $131,620,356.14 = 36.97% of total network spend
> - Total network spend: $356,045,248.18
> - Policy §5.3 cap: no single region may exceed 45% of total annual procurement spend
> - Result: 36.97% is within the 45% cap, so no Diversification Plan is triggered per Policy §5.3.

**Q4 — Which suppliers are on Supplier Watch List (SWL) status and what does it restrict?**

> 2 suppliers are on SWL status: Buenos Aires Pack and Maghreb Castworks.
>
> Per Policy §3.4, any supplier with a Compliance Score below 60 is placed on Supplier Watch List (SWL) status regardless of tier, and SWL restricts new PO issuance to 20% of prior quarter volume.
>
> - Buenos Aires Pack (SUP-092, Tier-3, Argentina) — average Compliance Score 59.2
> - Maghreb Castworks (SUP-080, Tier-3, Morocco) — average Compliance Score 59.9

**Q5 — Which product category has the highest average defect rate and does it exceed the Tier-2 limit?**

> Packaging Materials has the highest average defect rate at 1.91%, and it does not exceed the Tier-2 limit.
>
> - Packaging Materials: average defect rate 1.91% across 429 POs
> - Tier-2 defect ceiling: 2.50% per Policy §3.2
> - Result: 1.91% is below 2.50%, so it does not exceed the Tier-2 limit.

## Repo contents

```
scm_assistant.json        exported Flowise chatflow
compile_knowledge.py      CSV -> knowledge markdown pipeline
verify_answers.py         independent recomputation + assertion of the 5 answers
knowledge/                generated analytics register + supplier profile cards
flowise/system_prompt.txt the response prompt used in the chain
screenshots/              every build step, chunk experiments, and all 5 answers
```

To regenerate the knowledge layer against a different data cut:

```
python compile_knowledge.py path/to/register.csv knowledge
python verify_answers.py
```

## What I'd improve with more time

- **Agent flow with a code/SQL tool** over the PO register for unbounded ad-hoc analytics (the compile step covers the governed metrics; a sandboxed compute tool would cover the long tail). I kept the scripted-pipeline architecture for this submission because a public demo graded asynchronously should have zero runtime failure modes.
- **Evaluation harness** — a golden question set run on every knowledge recompile (RAGAS-style faithfulness/answer-correctness), instead of my manual 5-question validation lap.
- **Record Manager** on the document store so scheduled recompiles only re-embed changed chunks (I hit exactly the duplicate-vector problem it solves when I re-upserted the updated analytics file, and cleaned it by wiping the namespace and re-upserting once).
- **Reranker** (cross-encoder) between Pinecone and the LLM if the corpus grows beyond the curated stage where similarity alone is reliable.
- **Production hardening**: external memory backend for multi-server session persistence, input moderation, and per-question retrieval logging for auditability.
