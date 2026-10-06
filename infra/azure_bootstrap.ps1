<#
One-time Azure setup for the "Ask the data" service. Run from the repo root in PowerShell:

    .\infra\azure_bootstrap.ps1            # creates the resource group, environment and container app
    .\infra\azure_bootstrap.ps1 -GitHub    # also lets GitHub Actions deploy, and stores the CI secrets

What it creates (all in resource group rg-hq-ask, region South Central US):
  * a Container Apps environment with log storage turned off (no Log Analytics bill),
  * one container app that scales to zero when idle and never runs more than one replica.
Cost design: inside the monthly free grant; see infra/DEPLOY.md.

Secrets are read from .env and handed straight to Azure / GitHub. Nothing is printed.
Safe to re-run: existing resources are updated, not duplicated.
#>
param(
    [string]$ResourceGroup = "rg-hq-ask",
    [string]$Location = "southcentralus",
    [string]$Environment = "hq-ask-env",
    [string]$App = "hq-ask",
    [string]$Repo = "JamesBelanger/hospital-quality-dashboard",
    [string]$Branch = "master",
    [switch]$GitHub
)
$ErrorActionPreference = "Stop"

# az.cmd passes arguments through cmd.exe, which mangles "&", "(" and "%" in connection strings.
# Calling the CLI's own Python avoids that.
$AzPy = "C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"
function Az { & $AzPy -IBm azure.cli @args; if ($LASTEXITCODE -ne 0) { throw "az $($args[0]) $($args[1]) failed" } }

function Read-DotEnv([string]$Path) {
    $h = @{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { $h[$Matches[1]] = $Matches[2].Trim('"').Trim("'") }
    }
    return $h
}

$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$cfg = Read-DotEnv $envFile
foreach ($k in "OPENAI_API_KEY", "HQ_READER_URL", "HQ_SERVICE_URL", "HQ_LOG_URL") {
    if (-not $cfg[$k]) { throw "$k is missing from .env" }
}

# Salt for hashing client addresses in the request log; random per deployment, never written to disk.
$salt = -join ((1..48) | ForEach-Object { "{0:x}" -f (Get-Random -Maximum 16) })

Write-Host "1/3 resource group $ResourceGroup"
Az group create --name $ResourceGroup --location $Location --only-show-errors --output none

Write-Host "2/3 environment $Environment (logs destination: none)"
Az containerapp env create --name $Environment --resource-group $ResourceGroup --location $Location `
    --logs-destination none --only-show-errors --output none

Write-Host "3/3 container app $App (0 to 1 replicas, 0.25 vCPU, 0.5 GiB)"
$exists = & $AzPy -IBm azure.cli containerapp list --resource-group $ResourceGroup --query "[?name=='$App'].name" -o tsv
if (-not $exists) {
    # First creation uses a public placeholder image; the first GitHub deploy replaces it.
    Az containerapp create --name $App --resource-group $ResourceGroup --environment $Environment `
        --image "mcr.microsoft.com/k8se/quickstart:latest" --ingress external --target-port 8000 `
        --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi `
        --secrets "openai-key=$($cfg.OPENAI_API_KEY)" "reader-url=$($cfg.HQ_READER_URL)" "service-url=$($cfg.HQ_SERVICE_URL)" "log-url=$($cfg.HQ_LOG_URL)" "hash-salt=$salt" `
        --env-vars "OPENAI_API_KEY=secretref:openai-key" "HQ_READER_URL=secretref:reader-url" `
                   "HQ_SERVICE_URL=secretref:service-url" "HQ_LOG_URL=secretref:log-url" "HQ_HASH_SALT=secretref:hash-salt" `
                   "HQ_MODEL=gpt-6-luna" "HQ_RELEASE=bootstrap" `
        --only-show-errors --output none
} else {
    Az containerapp secret set --name $App --resource-group $ResourceGroup `
        --secrets "openai-key=$($cfg.OPENAI_API_KEY)" "reader-url=$($cfg.HQ_READER_URL)" "service-url=$($cfg.HQ_SERVICE_URL)" "log-url=$($cfg.HQ_LOG_URL)" `
        --only-show-errors --output none
}
$fqdn = & $AzPy -IBm azure.cli containerapp show --name $App --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv
Write-Host "service URL: https://$fqdn"

if ($GitHub) {
    # GitHub Actions signs in with a short-lived token (OpenID Connect); no Azure password is stored in GitHub.
    Write-Host "GitHub: identity for $Repo ($Branch)"
    $sub = & $AzPy -IBm azure.cli account show --query id -o tsv
    $tenant = & $AzPy -IBm azure.cli account show --query tenantId -o tsv
    $appName = "github-$App-deploy"
    $clientId = & $AzPy -IBm azure.cli ad app list --display-name $appName --query "[0].appId" -o tsv
    if (-not $clientId) {
        $clientId = & $AzPy -IBm azure.cli ad app create --display-name $appName --query appId -o tsv
        Az ad sp create --id $clientId --only-show-errors --output none
    }
    $scope = "/subscriptions/$sub/resourceGroups/$ResourceGroup"   # this resource group only
    Az role assignment create --assignee $clientId --role Contributor --scope $scope --only-show-errors --output none
    # GitHub's sign-in token names the repository with its permanent ids as well as its name
    # ("repo:Owner@123/name@456:ref:..."). The first deploy was refused because this used the name-only form.
    $ownerId = gh api "repos/$Repo" --jq .owner.id
    $repoId = gh api "repos/$Repo" --jq .id
    $owner, $name = $Repo.Split("/")
    $cred = @{ name = "github-$Branch-ids"; issuer = "https://token.actions.githubusercontent.com"
               subject = "repo:${owner}@${ownerId}/${name}@${repoId}:ref:refs/heads/$Branch"; audiences = @("api://AzureADTokenExchange") }
    $credFile = Join-Path $env:TEMP "hq-ask-federated.json"
    $cred | ConvertTo-Json | Set-Content -Encoding ascii $credFile
    $have = & $AzPy -IBm azure.cli ad app federated-credential list --id $clientId --query "[?name=='github-$Branch-ids'].name" -o tsv
    if (-not $have) { Az ad app federated-credential create --id $clientId --parameters "@$credFile" --only-show-errors --output none }
    Remove-Item $credFile

    Write-Host "GitHub: repository secrets and variables"
    $secrets = @{ AZURE_CLIENT_ID = $clientId; AZURE_TENANT_ID = $tenant; AZURE_SUBSCRIPTION_ID = $sub
                  OPENAI_API_KEY = $cfg.OPENAI_API_KEY; HQ_READER_URL = $cfg.HQ_READER_URL; HQ_SERVICE_URL = $cfg.HQ_SERVICE_URL }
    # Pass each value as an argument. Piping it in (`$value | gh secret set`) makes Windows PowerShell prepend a
    # byte-order mark and append a line break, which corrupts the secret: the first deploy failed on exactly that.
    foreach ($k in $secrets.Keys) { gh secret set $k --repo $Repo --body $secrets[$k] | Out-Null }
    gh variable set HQ_SERVICE_FQDN --repo $Repo --body $fqdn | Out-Null
    Write-Host "GitHub is ready. A push to $Branch that touches service/ or evals/ will test, evaluate, build and deploy."
}
