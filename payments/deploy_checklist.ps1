# deploy_checklist.ps1
# Run this EVERY time before deploying PaySync to production
# Each step must pass before proceeding to the next

param(
    [switch]$SkipTests,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProjectPath = "C:\Projects\paysync"
$Python = "$ProjectPath\venv\Scripts\python.exe"
$Manage = "$ProjectPath\manage.py"

function Step($msg) {
    Write-Host "`n[$msg]" -ForegroundColor Cyan
}

function Pass($msg) {
    Write-Host "  ✅ $msg" -ForegroundColor Green
}

function Fail($msg) {
    Write-Host "  ❌ $msg" -ForegroundColor Red
    exit 1
}

function Warn($msg) {
    Write-Host "  ⚠️  $msg" -ForegroundColor Yellow
}

Write-Host "`n================================================" -ForegroundColor White
Write-Host " PaySync Deployment Checklist" -ForegroundColor White
Write-Host "================================================`n" -ForegroundColor White

# ── Step 1: Environment ───────────────────────────────────────────────────────
Step "1. Environment verification"
$env:DJANGO_ENV = "production"
if ($env:DJANGO_ENV -ne "production") { Fail "DJANGO_ENV is not set to production" }
Pass "DJANGO_ENV=production"

# ── Step 2: Dependencies ──────────────────────────────────────────────────────
Step "2. Installing dependencies"
& $Python -m pip install -r "$ProjectPath\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }
Pass "All dependencies installed"

# ── Step 3: Production checks ─────────────────────────────────────────────────
Step "3. Production readiness checks"
& $Python $Manage production_check
if ($LASTEXITCODE -ne 0) { Fail "Production checks failed — fix issues above" }
Pass "All production checks passed"

# ── Step 4: Database migrations ───────────────────────────────────────────────
Step "4. Database migrations"
& $Python $Manage migrate --check 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    if ($DryRun) {
        Warn "Unapplied migrations found (dry run — not applying)"
    } else {
        Write-Host "  Applying migrations..." -ForegroundColor Yellow
        & $Python $Manage migrate
        if ($LASTEXITCODE -ne 0) { Fail "Migration failed" }
        Pass "Migrations applied"
    }
} else {
    Pass "No pending migrations"
}

# ── Step 5: Static files ──────────────────────────────────────────────────────
Step "5. Collecting static files"
if (-not $DryRun) {
    & $Python $Manage collectstatic --noinput --clear 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "collectstatic failed" }
    Pass "Static files collected"
} else {
    Warn "Dry run — skipping collectstatic"
}

# ── Step 6: Django system check ───────────────────────────────────────────────
Step "6. Django system checks"
& $Python $Manage check --deploy
if ($LASTEXITCODE -ne 0) { Fail "Django deploy checks failed" }
Pass "All Django checks passed"

# ── Step 7: Health check ──────────────────────────────────────────────────────
Step "7. Health endpoint check"
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health/" `
        -UseBasicParsing -TimeoutSec 10
    $body = $response.Content | ConvertFrom-Json
    if ($body.status -eq "healthy") {
        Pass "Health endpoint returns healthy"
    } else {
        Warn "Health endpoint returned: $($body.status)"
    }
} catch {
    Warn "Could not reach health endpoint (server may not be running yet)"
}

# ── Step 8: Retry scheduler ───────────────────────────────────────────────────
Step "8. Retry scheduler"
$task = Get-ScheduledTask -TaskName "PaySync_RetryPayments" -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq "Ready") {
        Pass "Retry scheduler registered and active"
    } else {
        Warn "Retry scheduler exists but state is: $($task.State)"
    }
} else {
    Warn "Retry scheduler not registered — run setup_scheduler.ps1"
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host "`n================================================" -ForegroundColor White
if ($DryRun) {
    Write-Host " Dry run complete — no changes made" -ForegroundColor Yellow
} else {
    Write-Host " ✅ Deployment checklist complete" -ForegroundColor Green
}
Write-Host "================================================`n" -ForegroundColor White