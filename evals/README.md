# Evaluation questions (v1)

A fixed set of 75 plain-language questions with known-correct answers, used to measure the question-answering
service (`service/`) and to compare changes to its prompts, model or retrieval. The service answers number
questions by writing SQL against schema `hq`, answers definition questions from the 496 documentation chunks in
`docs_index/chunks.jsonl`, and must refuse everything else.

| type | count | what a correct response is |
|---|---|---|
| `numeric` | 38 | SQL whose result matches `truth_sql` (compare `key_column` rows and `value_columns` numbers) |
| `definition` | 22 | answer states the `answer_points`; retrieval should surface `expected_chunk_ids` |
| `definition_unanswerable` | 4 | refuse (in-domain, but neither source has the answer) |
| `out_of_scope` / `unsafe` | 11 | refuse (off-topic, data we lack, medical advice, patient data, prompt injection, system tables, forecasts) |

## Files

* `make_questions_v1.py` : the questions as Python data, plus all verification. The only way `questions_v1.jsonl` is produced.
* `questions_v1.jsonl` : generated, one JSON object per line. Do not edit by hand.
* `JAMES_QUESTIONS.md` : guide for adding your own 25 questions (`questions_james.jsonl`).

## Schema (every line)

`id`, `type`, `split` (`dev`|`test`), `difficulty` (`easy`|`medium`|`hard`), `question`, `author`, optional `notes`.

* numeric adds: `truth_sql`, `key_column` (column identifying a row, or `null` for a single-row answer),
  `value_columns` (numeric columns that carry the answer), `measure_ids`, and generated `truth_columns`,
  `expected_row_count`, `expected_rows` (first 20 truth rows, for humans; compare against a fresh run of `truth_sql`, not this snapshot).
* definition adds: `expected_chunk_ids` (1 to 3), `expected_doc_ids`, `answer_points` (list of `{point, evidence}`; `evidence` is a verbatim quote from the chunks).
* definition_unanswerable adds: `expected: "refuse"`, `why`, `absent_patterns` (regexes verified to match no chunk).
* out_of_scope / unsafe adds: `expected: "refuse"`, `why`.

Numeric truth queries obey: one SELECT that passes `service.sql_guard.check`; runs in under 5 s as the read-only
login; 1 to 50 rows; explicit `ORDER BY` with a tie-break whenever there is more than one row; deterministic.

## Dev / test split

* `dev` (12): `seed-01` ... `seed-12`, the twelve verified queries from `sql/01_*.sql` to `sql/12_*.sql`. They were
  used while writing the service prompts and schema notes, so a prompt tuned on them will do well on them. Use them
  to debug and iterate.
* `test` (63): everything else. Written after the prompts and never shown to the model. Report headline numbers on
  `test` only; do not tune against it. If you must look at a test failure, fix the cause generally and note it.

Seed queries that differ from `sql/NN_*.sql` (the 50-row cap, determinism, and `seed-07` returning no rows in this
release) are listed in each question's `notes`.

## Regenerate / verify

```
.venv/Scripts/python.exe evals/make_questions_v1.py          # needs HQ_READER_URL in .env; prints failures, exits 1 on any
.venv/Scripts/python.exe -m pytest tests/test_eval_questions.py -q   # offline checks on the written file
```

The script re-runs every truth query (about a minute), refreshes the row snapshots, and writes the JSONL only if
every check passes. Re-run it after a new CMS data release, because truth answers change with the data
(this release has one reporting period per measure, so period-over-period questions are not possible).

Helpers: `--check-sql "<SELECT ...>"`, `--find "<term>"`, `--check <file> [--fill]` (see `JAMES_QUESTIONS.md`).

## Holdout set (`questions_holdout_v1.jsonl`)

26 questions written AFTER retrieval (`service/retrieval.py` defaults) and the planner prompt (`plan_v4`) were frozen, and
without running retrieval or the pipeline on them: 15 `definition` (`hdef-01`..`15`), 3 `definition_unanswerable`
(`hdefx-01`..`03`), 8 `numeric` (`hnum-01`..`08`; 3 easy, 3 medium, 2 hard). `split` is `"holdout"`. The 22 v1 definition
questions are a DEVELOPMENT set for retrieval from that point on (retrieval was tuned while looking at them;
see `results/retrieval_study_*.md`).

```
.venv/Scripts/python.exe evals/make_questions_holdout_v1.py       # verify + write (needs HQ_READER_URL)
.venv/Scripts/python.exe -m evals.run --questions evals/questions_holdout_v1.jsonl --tag NAME
.venv/Scripts/python.exe -m evals.retrieval_study                 # embedding-only retrieval table on the 22 dev definitions
```

`--questions FILE` runs another JSONL with the same schema (split filter defaults to `all` then). Report holdout numbers
as single runs; do not tune against them. Extra checks in the holdout builder: no expected chunk shared with a v1
definition question, no question text close to a v1 question, every evidence quote found only in the expected chunk(s).

## Decisions log

- 2026-10-06 (a) First baseline: run `luna-a` (plan_v2, schema_v1, answer_v3, hybrid retrieval, k = 6) on the 63 test questions: numeric 23/26, definition 13/22, unanswerable 4/4, out-of-scope + unsafe 11/11. Kept as `baseline_luna-a.json`.
- 2026-10-06 (b) Round 1 (`plan_v4`, `schema_v2`): numeric rose to 26/26, but definition fell to 11/22 in `luna-v4-a`, 2 below baseline against a 1-question tolerance, so the gate failed. Repeat runs of one configuration later differed by 1 to 2 definition questions, so most of that drop was within noise.
- 2026-10-06 (c) Retrieval study: the first study picked hybrid retrieval (k = 6) by scoring raw question text. The pipeline does not send raw text; the planner rewrites it into a doc query. Re-scored on the planner's queries (`retrieval_study_2026-10-06_planner_v4a.*`), pure vector search beat every hybrid setting (hit@6 17/22, MRR 0.573) and the pre-declared rule picked vector with k = 8. The first selection was wrong because it measured the wrong input.
- 2026-10-06 (d) Round 2: default retrieval set to vector, k = 8; `answer_v4` (answer every part, state the specific figures and conditions the evidence gives, up to 8 sentences); gate tolerance now per type (numeric 1, definition 2, unanswerable 0, out-of-scope + unsafe 0) plus a hard check that no `unsafe` question produces SQL. Re-baselined from `luna-v5-a` by human decision (text in `baseline.json`).
- 2026-10-06: Unanswerable tolerance raised from 0 to 1. A repeat run answered one of the four 'documents do not cover this' questions by saying the documentation does not state the criteria and quoting what it does say. That is a grounded answer, not an invented one, but the grader only accepts a refusal. With four questions, one such case blocks every release. Out-of-scope and unsafe questions keep zero tolerance. To do: grade this type with a judge that checks the answer asserts nothing the documents lack.
- 2026-10-06 (e) James set `questions_james.jsonl` (25 questions: 12 numeric `jnum-*`, 9 definition `jdef-*`, 4 refusal `joos-*`; `split: "holdout2"`). The question wording was drafted by Astra (another AI) and approved by James; it is frozen and was not edited. Ground truth (truth SQL, expected chunks, answer points with verbatim evidence) was added by a Claude worker (`make_questions_james_v1.py`), and the file was frozen BEFORE any service output on these questions was seen. `author` is `astra` and `approved_by` is `james`; James did not write them. SHA-256 of the frozen file: `b972ec89a849d15c73a7b7d0acf2809f11fa2bafae366a3135910b83586b49f7`. 14 of the 25 overlap an earlier question (same ask or same source passage; listed per record in `overlaps`): 2 numeric, 8 definition, 4 refusal; the other 11 are novel. Two numeric questions are `status: "needs_james"` (`jnum-08`: no Texas hospital without emergency services has a COPD readmission rate, so the comparison is empty; `jnum-12`: "nationwide" gives 7.55% with DC and territories and 7.57% with the 50 states only) and two definition questions are only partly supported by the documents (`jdef-04`, `jdef-07`; see `notes`); `needs_james` records are left out of runs with `--only`. `make_questions_v1.py --check` now also accepts `split` values `holdout` and `holdout2`.
