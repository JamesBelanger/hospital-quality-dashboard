# Eval run `luna-v3-keyword`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `keyword`, split `test`, 26 questions, prompts {'plan': 'plan_v3', 'schema': 'schema_v2', 'answer': 'answer_v3'}
- started 2026-10-06T01:33:55+00:00

## Headline

| type | correct (k/n) |
|---|---|
| definition | 5/22 (23%) |
| definition_unanswerable | 4/4 (100%) |
| **overall** | **9/26 (35%)** |

Definition: retrieval_hit 12/17; doc_hit 17/17; cited_expected 12/17; refused 1; mean points_covered 0.456.

Refusal stage (unanswerable + out-of-scope + unsafe): after plan: answer step: 3, plan: 1

## Latency and cost

- latency per question: median 24824 ms, p90 31689 ms
- cost: ask $0.0290 + judge $0.0363 = $0.0653; $0.00112 per question (ask only); tokens in/out 243860/9324

## Incorrect (17)

- `def-01` (definition): 2/4 points missing: The overall star rating summarizes measures reported on Care | Most hospitals display three stars
- `def-02` (definition): 2/4 points missing: SIRs are calculated for the hospital, the state and the nati | Infection types include central line bloodstream infections 
- `def-03` (definition): 2/3 points missing: EDAC is shown as days per 100 discharges and can be negative | An EDAC of zero means the hospital performs exactly as expec
- `def-04` (definition): 2/4 points missing: In the value-based purchasing dataset the mortality figures  | CMS chose 30-day death over inpatient death for a consistent
- `def-06` (definition): 2/4 points missing: Patients must be enrolled in Medicare fee-for-service | Discharges must be from non-federal acute care hospitals; retrieval miss
- `def-07` (definition): 3/4 points missing: Admissions to PPS-exempt cancer hospitals are excluded | Patients discharged against medical advice are excluded | Admissions for primary psychiatric diagnoses and for rehabil; retrieval miss
- `def-08` (definition): 2/4 points missing: It links patient-level EHR data to CMS claims data for risk  | Cohort and outcome follow the original HWR methodology
- `def-09` (definition): 2/4 points missing: Public reporting uses a cutoff of 25 or more eligible admiss | Test-retest reliability rose from 0.725 to 0.780
- `def-10` (definition): 3/3 points missing: To broadly measure quality of care across hospitals, includi | To provide information that facilitates targeted quality imp | To minimize provider burden while improving case-mix adjustm; retrieval miss
- `def-14` (definition): 2/3 points missing: Claims data give the cohort, outcome and comorbidities; EHR  | National observed mortality rate is included hospitalization; retrieval miss
- `def-15` (definition): judge failed
- `def-16` (definition): pipeline raised: APIConnectionError
- `def-17` (definition): pipeline raised: APIConnectionError
- `def-18` (definition): pipeline raised: APIConnectionError
- `def-19` (definition): pipeline raised: APIConnectionError
- `def-20` (definition): pipeline raised: APIConnectionError
- `def-22` (definition): refused at after plan: answer step; expected chunk not retrieved

Pipeline errors: def-16, def-17, def-18, def-19, def-20
