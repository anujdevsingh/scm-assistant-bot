# Flowise Cloud setup — click-by-click

Working checklist for building the SCM Assistant on cloud.flowiseai.com.
Take a screenshot at every step marked [SHOT] -> save into screenshots/.

## 1. Account + credential

1. Sign up free at https://flowiseai.com -> open the dashboard.
2. Left sidebar -> Credentials -> Add Credential -> search "OpenAI API" -> paste the API key -> name it `openai-scm`. [SHOT]

## 2. Document Store

1. Left sidebar -> Document Stores -> + Add New -> name: `BQBYTE Supplier Knowledge`. [SHOT]
2. Add four loaders (Add Document Loader button each time):

   | # | Loader | File | Splitter |
   |---|--------|------|----------|
   | 1 | PDF File | SupplyChain_Governance_Policy_v3.2 1.pdf | Recursive Character Text Splitter |
   | 2 | Plain Text / File loader | knowledge/network_analytics.md | Markdown Text Splitter |
   | 3 | Plain Text / File loader | knowledge/supplier_profiles.md | Markdown Text Splitter |
   | 4 | CSV File | supplier_performance_data.csv | (one row per chunk - leave splitter default) |

3. CHUNK EXPERIMENT (required by the brief - record chunk counts both times):
   - Config A: Recursive splitter, chunk size 1500, overlap 200 (PDF) / Markdown splitter 1500/200 (md files).
     Preview each loader -> note chunk count per file. [SHOT]
   - Config B: chunk size 700, overlap 100 on the same loaders.
     Preview -> note chunk counts. [SHOT]
   - Record both in the table below, then keep the config that keeps each analytics
     section intact in a single chunk (expected: A for the md files).

   | File | Config A chunks (1500/200) | Config B chunks (700/100) |
   |------|---------------------------|---------------------------|
   | policy PDF |  |  |
   | network_analytics.md |  |  |
   | supplier_profiles.md |  |  |
   | CSV |  | (row-per-chunk, same both configs) |

4. Upsert: select embeddings = OpenAI Embeddings (`text-embedding-3-small`, credential `openai-scm`),
   vector store = the built-in one offered by Flowise Cloud. Upsert all loaders. [SHOT of upsert result with chunk counts]

## 3. Chatflow

1. Left sidebar -> Chatflows -> + Add New -> name: `SCM Assistant`.
2. Drag nodes and wire them:
   - `Conversational Retrieval QA Chain` (the spine)
   - `ChatOpenAI` -> model: latest GPT chat model available in the dropdown, temperature 0,
     credential `openai-scm` -> connect to the chain's Chat Model input.
   - `Document Store (Vector)` retriever node -> pick `BQBYTE Supplier Knowledge`,
     top K = 10 -> connect to the chain's Vector Store Retriever input.
3. Open the chain's Additional Parameters -> Response Prompt (the one containing {context}) ->
   replace with the contents of system_prompt.txt (it already ends with the {context} placeholder). [SHOT of canvas]
4. Save.

## 4. Test

Run the 5 case-study questions in the chat panel. Check each answer against the
"answer key" printed by `python verify_answers.py` (OUR data, not the PDF samples).
[SHOT of each Q&A]

If an aggregate answer comes back wrong: raise top K to 12-15, or check the
relevant section of network_analytics.md survived chunking in one piece.

## 5. Publish

1. Canvas top-right -> Share icon -> Share Chatbot tab -> Make Public = ON.
2. Title: `SCM Assistant`. Welcome message:
   "Hi! I'm the SCM Assistant for the BQBYTE supplier network. Ask me about supplier
   performance, risk, compliance, disruptions, or governance policy rules."
3. Copy the public URL, verify it answers in an incognito window. [SHOT]

## 6. Export

Canvas -> Settings (gear) -> Export Chatflow -> save as `scm_assistant.json` in this project folder.
