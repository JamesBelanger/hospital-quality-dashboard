# Eval run `luna-james-a`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `vector`, split `all`, 23 questions, prompts {'plan': 'plan_v4', 'schema': 'schema_v2', 'answer': 'answer_v4'}
- started 2026-10-06T18:57:22+00:00

## Headline

| type | correct (k/n) |
|---|---|
| numeric | 10/10 (100%) |
| definition | 7/9 (78%) |
| out_of_scope + unsafe | 4/4 (100%) |
| **overall** | **21/23 (91%)** |

Numeric: row_recall mean 1.000; order_ok 5/5; answer_states_value 5/5; refused 0, SQL error 0, repaired 0.

Definition: retrieval_hit 8/9; doc_hit 9/9; cited_expected 8/9; refused 0; mean points_covered 0.833.

Unsafe: refused 2/2; SQL produced for 0/2 (ran OK: 0/2).

Refusal stage (unanswerable + out-of-scope + unsafe): plan: 4

## Latency and cost

- latency per question: median 9704 ms, p90 11935 ms
- cost: ask $0.0281 + judge $0.0214 = $0.0494; $0.00122 per question (ask only); tokens in/out 233679/9449

## Incorrect (2)

- `jdef-02` (definition): 2/3 points missing: The Overall Star Rating summarizes measures from five groups | The HCAHPS Summary Star Rating combines only the HCAHPS (pat
- `jdef-07` (definition): 1/2 points missing: It summarizes serious but potentially preventable complicati
