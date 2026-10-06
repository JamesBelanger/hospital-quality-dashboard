# Eval run `luna-keyword`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `keyword`, split `all`, 26 questions, prompts {'plan': 'plan_v2', 'schema': 'schema_v1', 'answer': 'answer_v3'}
- started 2026-10-06T00:52:28+00:00

## Headline

| type | correct (k/n) |
|---|---|
| definition | 0/22 (0%) |
| definition_unanswerable | 4/4 (100%) |
| **overall** | **4/26 (15%)** |

Definition: retrieval_hit 0/22; doc_hit 0/22; cited_expected 0/22; refused 21; mean points_covered 0.000.

Refusal stage (unanswerable + out-of-scope + unsafe): after plan: no evidence: 3, plan: 1

## Latency and cost

- latency per question: median 9797 ms, p90 15405 ms
- cost: ask $0.0214 + judge $0.0027 = $0.0241; $0.00082 per question (ask only); tokens in/out 197159/3552

## Incorrect (22)

- `def-01` (definition): 4/4 points missing: The overall star rating summarizes measures reported on Care | It uses five measure groups: mortality, safety of care, read | Hospitals receive one to five stars, five being best; retrieval miss
- `def-02` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-03` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-04` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-05` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-06` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-07` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-08` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-09` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-10` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-11` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-12` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-13` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-14` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-15` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-16` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-17` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-18` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-19` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-20` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-21` (definition): refused at after plan: no evidence; expected chunk not retrieved
- `def-22` (definition): refused at after plan: no evidence; expected chunk not retrieved
