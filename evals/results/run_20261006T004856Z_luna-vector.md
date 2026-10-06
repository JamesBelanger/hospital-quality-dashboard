# Eval run `luna-vector`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `vector`, split `all`, 26 questions, prompts {'plan': 'plan_v2', 'schema': 'schema_v1', 'answer': 'answer_v3'}
- started 2026-10-06T00:48:56+00:00

## Headline

| type | correct (k/n) |
|---|---|
| definition | 12/22 (55%) |
| definition_unanswerable | 4/4 (100%) |
| **overall** | **16/26 (62%)** |

Definition: retrieval_hit 15/22; doc_hit 22/22; cited_expected 15/22; refused 1; mean points_covered 0.583.

Refusal stage (unanswerable + out-of-scope + unsafe): after plan: answer step: 3, plan: 1

## Latency and cost

- latency per question: median 19192 ms, p90 25336 ms
- cost: ask $0.0327 + judge $0.0516 = $0.0843; $0.00126 per question (ask only); tokens in/out 266158/12219

## Incorrect (10)

- `def-01` (definition): 2/4 points missing: The overall star rating summarizes measures reported on Care | Most hospitals display three stars
- `def-02` (definition): 2/4 points missing: SIRs are calculated for the hospital, the state and the nati | Infection types include central line bloodstream infections 
- `def-03` (definition): 2/3 points missing: EDAC is shown as days per 100 discharges and can be negative | An EDAC of zero means the hospital performs exactly as expec
- `def-06` (definition): 3/4 points missing: Patients must be aged 65 or older | Discharges must be from non-federal acute care hospitals | Patients who died in the hospital are not included; retrieval miss
- `def-08` (definition): 4/4 points missing: It links patient-level EHR data to CMS claims data for risk  | The core clinical data elements include gender, age, weight  | They also include the first blood count and basic chemistry ; retrieval miss
- `def-11` (definition): 3/4 points missing: Surgical divisions include cardiothoracic, general, neurosur | Division standardized mortality ratios are combined into one | Service mix is handled using the principal discharge diagnos; retrieval miss
- `def-12` (definition): 2/3 points missing: A standard period keeps length of stay from unduly influenci | The 30-day period captures the largest declines in mortality; retrieval miss
- `def-13` (definition): refused at after plan: answer step; expected chunk not retrieved
- `def-14` (definition): 2/3 points missing: Claims data give the cohort, outcome and comorbidities; EHR  | National observed mortality rate is included hospitalization; retrieval miss
- `def-18` (definition): 2/4 points missing: The algorithm minimizes the within-cluster sum of squares | It is the same algorithm used for Medicare Part C and Part D
