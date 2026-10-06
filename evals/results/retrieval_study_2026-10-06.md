# Retrieval study (2026-10-06)

22 `definition` questions (development set for retrieval). Query = question text.

| configuration | hit@3 | hit@6 | hit@8 | hit@10 | MRR |
|---|---|---|---|---|---|
| vector | 15/22 | 17/22 | 18/22 | 19/22 | 0.528 |
| hybrid_or | 12/22 | 16/22 | 18/22 | 19/22 | 0.480 |
| hybrid_or_w0.5 | 13/22 | 17/22 | 18/22 | 19/22 | 0.515 |
| hybrid_or_w0.25 | 13/22 | 15/22 | 17/22 | 20/22 | 0.523 |
| hybrid_and_first | 13/22 | 17/22 | 19/22 | 20/22 | 0.526 |
| hybrid_and_first_w0.5 | 14/22 | 18/22 | 19/22 | 20/22 | 0.560 |

Selected by the fixed rule: **hybrid_and_first_w0.5**, k = **6** (hit@6=18, mrr=0.560, hit@8-hit@6=1).

First-expected-chunk rank per question (None = not in top 10):

| id | vector | hybrid_or | hybrid_or_w0.5 | hybrid_or_w0.25 | hybrid_and_first | hybrid_and_first_w0.5 |
|---|---|---|---|---|---|---|
| def-01 | 2 | 2 | 2 | 2 | 2 | 2 |
| def-02 | 1 | 1 | 1 | 1 | 1 | 1 |
| def-03 | 1 | 1 | 1 | 1 | 1 | 1 |
| def-04 | 1 | 1 | 1 | 1 | 1 | 1 |
| def-05 | 1 | 1 | 1 | 1 | 1 | 1 |
| def-06 | None | None | None | None | None | None |
| def-07 | 10 | None | None | None | None | None |
| def-08 | None | 8 | 9 | 10 | 8 | 9 |
| def-09 | 3 | 1 | 2 | 2 | 1 | 2 |
| def-10 | 1 | None | None | 9 | 1 | 1 |
| def-11 | None | 4 | 6 | 9 | 4 | 6 |
| def-12 | 1 | 1 | 1 | 1 | 1 | 1 |
| def-13 | 2 | 4 | 3 | 2 | 4 | 3 |
| def-14 | 3 | 9 | 8 | 8 | 9 | 8 |
| def-15 | 2 | 3 | 1 | 1 | 3 | 1 |
| def-16 | 2 | 2 | 2 | 2 | 2 | 2 |
| def-17 | 1 | 1 | 1 | 1 | 1 | 1 |
| def-18 | 1 | 2 | 1 | 1 | 2 | 1 |
| def-19 | 3 | 2 | 2 | 2 | 2 | 2 |
| def-20 | 5 | 8 | 6 | 6 | 8 | 6 |
| def-21 | 8 | 5 | 6 | 7 | 5 | 6 |
| def-22 | 5 | 6 | 4 | 4 | 6 | 4 |
