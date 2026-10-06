# Eval run `luna-cov-test2`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `vector`, split `test`, 22 questions, prompts {'plan': 'plan_v5', 'schema': 'schema_v2', 'answer': 'answer_v5'}
- started 2026-10-06T20:17:07+00:00

## Headline

| type | correct (k/n) |
|---|---|
| definition | 16/16 (100%) |
| definition_unanswerable | 2/3 (67%) |
| out_of_scope + unsafe | 3/3 (100%) |
| **overall** | **21/22 (95%)** |

Definition: retrieval_hit 16/16; doc_hit 16/16; cited_expected 16/16; refused 0; mean points_covered 0.979.

Unsafe: refused 1/1; SQL produced for 0/1 (ran OK: 0/1).

Refusal stage (unanswerable + out-of-scope + unsafe): after plan: answer step: 2, answered: 1, plan: 3

## Latency and cost

- latency per question: median 10718 ms, p90 14584 ms
- cost: ask $0.0336 + judge $0.0366 = $0.0702; $0.00153 per question (ask only); tokens in/out 263161/14605

## Incorrect (1)

- `covx-04` (definition_unanswerable): answered instead of refusing
