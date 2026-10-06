# Deploying the "Ask the data" service

Status: **live since 2026-10-06** at https://hq-ask.victoriousdesert-e769edf4.southcentralus.azurecontainerapps.io (first release `924c9e9`).

## What broke on the first deploy
| Symptom | Cause | Fix |
|---|---|---|
| `azure_bootstrap.ps1` stopped at "container app" | `az containerapp show` on a missing app writes to stderr, which Windows PowerShell treats as fatal | Use `containerapp list` for the existence check |
| Evaluation gate scored 0/63, every question raised `UnicodeEncodeError` in milliseconds | Secrets were piped into `gh secret set`; Windows PowerShell prepends a byte-order mark and appends CRLF, so every secret was corrupted | Pass the value with `--body` |
| `azure/login` failed with AADSTS700213 | GitHub's OIDC subject now carries ids: `repo:Owner@<id>/name@<id>:ref:...`; the federated credential used the name-only form | Build the subject from `gh api repos/<repo>` ids |

The gate did its job in the second case: a broken configuration could not ship.

## Shape
- **Azure Container Apps**, resource group `rg-hq-ask`, South Central US. One app, `hq-ask`.
- **Image** on GitHub Container Registry: `ghcr.io/jamesbelanger/hospital-quality-ask:<commit>`.
- **Database** stays on Supabase. The app holds three database logins (`hq_reader`, `hq_service`, `hq_logger`) and the model key as Container Apps secrets.
- **Pipeline** (`.github/workflows/deploy.yml`): tests → evaluation gate against `evals/baseline.json` → build → deploy → smoke test.

## Cost design
| Choice | Why |
|---|---|
| `min-replicas 0`, `max-replicas 1`, 0.25 vCPU / 0.5 GiB | Nothing is billed while idle; usage stays inside the monthly free grant (180,000 vCPU-seconds, 360,000 GiB-seconds, 2M requests per subscription). |
| Environment logs destination `none` | No Log Analytics workspace. Live logs: `az containerapp logs show -n hq-ask -g rg-hq-ask --follow`. |
| GitHub Container Registry | Free for public images; Azure Container Registry has a monthly fee. |
| Budget `monthly-5usd-alert` | Emails at 50% and 100% of $5. It is an alert, not a cap. |
| Evaluation gate in CI | About $0.13 of model spend per run; it runs only when `service/` or `evals/` change. |

## First deploy (once)
1. `.\infra\azure_bootstrap.ps1 -GitHub` — creates the Azure resources, the GitHub sign-in identity (scoped to the one resource group) and the repository secrets. Needs `az login` and `gh auth login` done first.
2. Merge `ask-service` into `master` and push. The workflow builds and deploys.
3. On GitHub: the package `hospital-quality-ask` → Package settings → change visibility to **Public** (the app pulls the image without a registry password). If the first deploy fails with an image-pull error, this is why; re-run the workflow after changing it.
4. Open `https://<service URL>/health`; it should show the commit as `release`.

## Roll back
Every deploy is a new revision tagged with its commit.
- Fastest: `az containerapp update -n hq-ask -g rg-hq-ask --image ghcr.io/jamesbelanger/hospital-quality-ask:<previous commit>`
- Or revert the commit and push; the workflow redeploys (use `workflow_dispatch` with `skip_eval` only for a rollback).

## Tear down
`az group delete --name rg-hq-ask` removes everything Azure-side. Delete the app registration `github-hq-ask-deploy` separately.

## Operating it
`/health`, `/ask` and `/status` are verified on the live service. The `az containerapp update --set-env-vars` commands below (prompt roll-back, limits) are written from the CLI reference and have **not** been run yet.

The container keeps no state, so everything it needs to remember is a row in `hq_app.request_log` (Supabase). The daily budget, the per-client and global rate limits and `/status` are all computed from that table. If the table cannot be read, `/ask` answers 503 and does not call the model (it will not run unmetered).

### Look at it
- `GET https://<service URL>/status`: for the last 24 hours and 7 days, request count, refusal rate, error count, median and p90 latency, total cost, overall and per release; plus today's budget used and limit. No question text.
- `GET /health`: release, model and the three prompt versions in use. Never touches the database or the model.
- Raw rows: Supabase SQL editor, as the owner: `select ts, release, question, route, refused, cost_usd, latency_ms, error from hq_app.request_log order by ts desc limit 50;`. Questions are stored as typed; client IPs are not (only a salted SHA-256).
- Live container output: `az containerapp logs show -n hq-ask -g rg-hq-ask --follow`.

### Roll back a prompt or model (no rebuild)
Each env var is read when a request arrives, so a new revision with different values is all it takes. Prompt files are versioned in `service/prompts/`; a name that has no file makes every `/ask` fail (502, logged with the error).
```
az containerapp update -n hq-ask -g rg-hq-ask --set-env-vars HQ_PLAN_PROMPT=plan_v3 HQ_ANSWER_PROMPT=answer_v3 HQ_SCHEMA_PROMPT=schema_v1 HQ_MODEL=gpt-6-luna
```
Check `/health` afterwards. To go back to the defaults baked into the image, remove the override: `az containerapp update -n hq-ask -g rg-hq-ask --remove-env-vars HQ_PLAN_PROMPT HQ_ANSWER_PROMPT HQ_SCHEMA_PROMPT`. To roll back the code instead, see "Roll back" above.

### Change the limits
```
az containerapp update -n hq-ask -g rg-hq-ask --set-env-vars HQ_DAILY_BUDGET_USD=1.00 HQ_CLIENT_PER_HOUR=20 HQ_GLOBAL_PER_MINUTE=30
```
Defaults: 0.50 USD per UTC day, 20 questions per client per hour, 30 per minute overall. The budget counts the logged cost of answered requests since 00:00 UTC. Set your own `HQ_HASH_SALT` (any long random string; changing it makes every client look new): `az containerapp update -n hq-ask -g rg-hq-ask --set-env-vars HQ_HASH_SALT=<random>`.

### Database logins
Created by `infra/setup_reader_role.py` (re-running it rotates all three passwords and rewrites `.env`; push the new URLs to Azure with `azure_bootstrap.ps1`).

| Login | Env var | Can | Cannot | Timeout |
|---|---|---|---|---|
| `hq_reader` | `HQ_READER_URL` | SELECT on schema `hq` (model-written SQL runs here; read-only transactions) | write anything; read `hq_docs`, `hq_app`, other schemas | 5 s |
| `hq_service` | `HQ_SERVICE_URL` | SELECT on `hq_docs.chunks` (documentation retrieval, pgvector) | write anything; read `hq` or `hq_app` | 10 s |
| `hq_logger` | `HQ_LOG_URL` | INSERT and SELECT on `hq_app.request_log` | UPDATE, DELETE, TRUNCATE, create or drop; read `hq` or `hq_docs` | 5 s |

Not yet covered: alerts. Nothing pages anyone when the budget is hit or the error rate rises; `/status` has to be looked at.
