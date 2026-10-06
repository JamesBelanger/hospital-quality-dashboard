# Eval run `luna-cov-test`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `vector`, split `test`, 22 questions, prompts {'plan': 'plan_v5', 'schema': 'schema_v2', 'answer': 'answer_v5'}
- started 2026-10-06T20:06:58+00:00

## Headline

| type | correct (k/n) |
|---|---|
| definition | 16/16 (100%) |
| definition_unanswerable | 2/3 (67%) |
| out_of_scope + unsafe | 3/3 (100%) |
| **overall** | **21/22 (95%)** |

Definition: retrieval_hit 16/16; doc_hit 16/16; cited_expected 16/16; refused 0; mean points_covered 1.000.

Unsafe: refused 1/1; SQL produced for 0/1 (ran OK: 0/1).

Refusal stage (unanswerable + out-of-scope + unsafe): after plan: answer step: 2, answered: 1, plan: 3

## Latency and cost

- latency per question: median 9848 ms, p90 14742 ms
- cost: ask $0.0338 + judge $0.0367 = $0.0706; $0.00154 per question (ask only); tokens in/out 262879/15193

## Incorrect (1)

- `covx-04` (definition_unanswerable): answered instead of refusing
