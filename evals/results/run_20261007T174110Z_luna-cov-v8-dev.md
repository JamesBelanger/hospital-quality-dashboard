# Eval run `luna-cov-v8-dev`

- model `gpt-6-luna`, judge `gpt-6-sol`, retrieval `vector`, split `dev`, 8 questions, prompts {'plan': 'plan_v6', 'schema': 'schema_v2', 'answer': 'answer_v6'}
- started 2026-10-07T17:41:10+00:00

## Headline

| type | correct (k/n) |
|---|---|
| definition | 6/6 (100%) |
| definition_unanswerable | 1/1 (100%) |
| out_of_scope + unsafe | 1/1 (100%) |
| **overall** | **8/8 (100%)** |

Definition: retrieval_hit 6/6; doc_hit 6/6; cited_expected 6/6; refused 0; mean points_covered 1.000.

Refusal stage (unanswerable + out-of-scope + unsafe): after plan: answer step: 1, plan: 1

## Latency and cost

- latency per question: median 10212 ms, p90 14710 ms
- cost: ask $0.0119 + judge $0.0124 = $0.0244; $0.00149 per question (ask only); tokens in/out 95196/4787

## Incorrect (0)

