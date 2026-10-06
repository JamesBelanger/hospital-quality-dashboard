# Eval run `luna-v5-holdout`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `vector`, split `all`, 26 questions, prompts {'plan': 'plan_v4', 'schema': 'schema_v2', 'answer': 'answer_v4'}
- started 2026-10-06T02:28:03+00:00

## Headline

| type | correct (k/n) |
|---|---|
| numeric | 8/8 (100%) |
| definition | 11/15 (73%) |
| definition_unanswerable | 3/3 (100%) |
| **overall** | **22/26 (85%)** |

Numeric: row_recall mean 1.000; order_ok 5/5; answer_states_value 3/3; refused 0, SQL error 0, repaired 0.

Definition: retrieval_hit 12/15; doc_hit 13/15; cited_expected 12/15; refused 2; mean points_covered 0.778.

Refusal stage (unanswerable + out-of-scope + unsafe): plan: 2, after plan: answer step: 1

## Latency and cost

- latency per question: median 8924 ms, p90 15137 ms
- cost: ask $0.0338 + judge $0.0239 = $0.0578; $0.00130 per question (ask only); tokens in/out 276092/12542

## Incorrect (4)

- `hdef-07` (definition): refused at plan; expected chunk not retrieved
- `hdef-08` (definition): 1/2 points missing: The measure estimates the likelihood that at least 1 of 8 co
- `hdef-10` (definition): 1/2 points missing: The datasets cover admissions between January 1, 2009 and Ja; retrieval miss
- `hdef-14` (definition): refused at plan; expected chunk not retrieved
