# Rollback drill

Two short exercises that prove the safety net works. Do them once yourself; they are the first-hand
answer to "what happens when a change makes the system worse?"

Each takes about 15 minutes. Drill 1 costs about $0.13 of model spend; Drill 2 costs under a cent.

## Drill 1 — the gate stops a bad change before it ships

A branch is already prepared: `drill/terse-answer`. It adds one prompt file
(`service/prompts/answer_v5_drill.md`) that tells the model to answer in eight words or fewer,
and points the service at it. Short answers drop the specifics the definition questions need.

1. Publish the branch and open a pull request:
   ```
   cd C:\Users\james\projects\hospital-quality-dashboard
   git push origin drill/terse-answer
   gh pr create --base master --head drill/terse-answer --title "Drill: terse answers" --body "Deliberately worse prompt. Expect the evaluation gate to fail. Do not merge."
   ```
2. Watch the check run (about 8 minutes): `gh pr checks --watch`
3. Expected: **Evaluation gate** fails with a line like `definition: N/22 vs baseline 13/22 (tolerance 2)`.
   Number questions should be unaffected (they are graded on the query result, not the wording).
   Nothing is built or deployed from a pull request.
4. Read the report: `gh run view --log-failed`, or download the `eval-report-…` artifact from the run page.
5. Close it without merging: `gh pr close drill/terse-answer --delete-branch`
6. Write down in two sentences: what the gate reported, and what would have happened without it.

If the gate does NOT fail, that is a finding, not a mistake in the drill: record the scores and tell Claude.

## Drill 2 — roll back a live prompt with one command

This changes the running service without a rebuild, then puts it back.

1. See what is running: open `/health` (note `prompt_versions.answer`, currently `answer_v4`).
2. Switch the live service to the previous answer prompt:
   ```
   az containerapp update -n hq-ask -g rg-hq-ask --set-env-vars HQ_ANSWER_PROMPT=answer_v3
   ```
3. Open `/health` again: `answer` now reads `answer_v3`. Ask one definition question on the Ask page and
   note that the answer is shorter.
4. Undo it:
   ```
   az containerapp update -n hq-ask -g rg-hq-ask --remove-env-vars HQ_ANSWER_PROMPT
   ```
5. Open `/health` once more: back to `answer_v4`.
6. Open `/status`: both periods are in the log under the same release, and every row records the
   prompt versions that produced it.

Note that step 2 bypasses the evaluation gate. That is deliberate (a rollback has to be fast), and it
is why the override is visible in `/health` and recorded on every request.

## Afterwards
Tell Claude the two results so they go into the case study under "What broke".
