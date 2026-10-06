# Eval run `luna-v4-holdout`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `hybrid`, split `all`, 26 questions, prompts {'plan': 'plan_v4', 'schema': 'schema_v2', 'answer': 'answer_v3'}
- started 2026-10-06T02:12:47+00:00

## Headline

| type | correct (k/n) |
|---|---|
| numeric | 7/8 (88%) |
| definition | 10/15 (67%) |
| definition_unanswerable | 3/3 (100%) |
| **overall** | **20/26 (77%)** |

Numeric: row_recall mean 0.875; order_ok 5/5; answer_states_value 2/3; refused 0, SQL error 0, repaired 0.

Definition: retrieval_hit 13/15; doc_hit 14/15; cited_expected 13/15; refused 1; mean points_covered 0.778.

Refusal stage (unanswerable + out-of-scope + unsafe): plan: 2, after plan: answer step: 1

## Latency and cost

- latency per question: median 9962 ms, p90 16092 ms
- cost: ask $0.0340 + judge $0.0314 = $0.0653; $0.00131 per question (ask only); tokens in/out 275502/12874

## Incorrect (6)

- `hnum-02` (numeric): value(s) [56.0] not in the first generated row
- `hdef-01` (definition): 2/3 points missing: One part is the HCAHPS Base Score, worth 0 to 80 points | The other part is the HCAHPS Consistency Score, worth 0 to 2
- `hdef-07` (definition): refused at plan; expected chunk not retrieved
- `hdef-08` (definition): 1/2 points missing: The measure estimates the likelihood that at least 1 of 8 co
- `hdef-10` (definition): 1/2 points missing: The datasets cover admissions between January 1, 2009 and Ja; retrieval miss
- `hdef-13` (definition): 2/3 points missing: More than 400,000 patients die each year from preventable ha | They also do not meaningfully capture performance for smalle
