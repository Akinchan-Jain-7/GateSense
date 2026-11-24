<#
.SYNOPSIS
  Start the laptop webcam as a GateSense gate camera, with the live preview page.

.DESCRIPTION
  One command for a demo on your own laptop (docs/webcam-demo.md has the full walkthrough):

    .\scripts\webcam-demo.ps1

  It checks that the API is up, puts the plate detector model in place (from your
  Downloads folder or the models-v1 release, hash-checked), installs the camera program's
  packages, gives the webcam fresh device keys (entry + exit), opens the guard console and
  starts the camera with its preview page. Ctrl+C stops the camera.

  Start these first, each in its own terminal (CONTRIBUTING.md has the details):
    docker compose up postgres redis mailpit storage
    cd backend; uv run uvicorn app.main:app --reload
    cd backend; uv run celery -A app.workers.celery_app worker --pool=solo --loglevel=info
    cd frontend; npm run dev

.PARAMETER Camera
  Which camera: 0 is the built-in webcam, 1 the next one (an external USB camera). A video
  file path also works, for a rehearsal without holding anything up.

.PARAMETER NoBrowser
  Don't open the preview page and the guard console in the browser.
#>
param(
    [string]$Camera = "0",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Anpr = Join-Path $Root "anpr"
$Backend = Join-Path $Root "backend"
$Model = Join-Path $Anpr "models\plate_detector.onnx"
# SHA-256 of the models-v1 plate detector (anpr/gatesense_anpr/download_model.py).
$ModelSha256 = "63e5d3e155b1456076c1438c82f969eab25b517b53c42a62dd384ad94de6a977"
$ApiUrl = "http://127.0.0.1:8000"
$ConsoleUrl = "http://localhost:5173"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`n$text" -ForegroundColor Red; exit 1 }
function Run($what) {
    # Native commands don't throw on failure: check their exit code.
    & $what
    if ($LASTEXITCODE -ne 0) { Fail "That step failed (exit code $LASTEXITCODE); see the messages above." }
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv isn't installed. Install it with:  pip install uv   (then open a new terminal)"
}

Step "Checking the API at $ApiUrl"
try {
    $ready = Invoke-RestMethod -Uri "$ApiUrl/ready" -TimeoutSec 5
    if ($ready.status -ne "ready") { throw "not ready" }
    Write-Host "API is up (database and Redis OK)."
} catch {
    Fail @"
The API isn't running. Start these first, each in its own terminal:
  docker compose up postgres redis mailpit storage
  cd backend; uv run uvicorn app.main:app --reload
  cd backend; uv run celery -A app.workers.celery_app worker --pool=solo --loglevel=info
  cd frontend; npm run dev
(First time only: cd backend; uv run alembic upgrade head; uv run python -m app.seed)
"@
}

Step "Plate detector model"
if (Test-Path $Model) {
    Write-Host "Found $Model"
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $Model) | Out-Null
    $downloads = Join-Path $HOME "Downloads"
    $candidates = @(
        (Join-Path $downloads "plate_detector.onnx"),
        (Join-Path $downloads "gatesense_results\plate_detector.onnx")
    ) | Where-Object { Test-Path $_ }
    $copied = $false
    foreach ($file in $candidates) {
        $hash = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
        if ($hash -eq $ModelSha256) {
            Copy-Item $file $Model
            Write-Host "Copied the trained model from $file (SHA-256 matches)."
            $copied = $true
            break
        }
        Write-Host "Skipping $file : its SHA-256 doesn't match the trained model." -ForegroundColor Yellow
    }
    if (-not $copied) {
        Write-Host "Not in Downloads; trying the models-v1 GitHub release..."
        Push-Location $Anpr
        try { & uv run python -m gatesense_anpr.download_model } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Model)) {
            Fail @"
No plate detector model. Either:
  - put plate_detector.onnx (from the Kaggle run's output) in your Downloads folder, or
  - publish the models-v1 release (docs/PROGRESS.md, "Pick up here"),
then run this script again.
"@
        }
    }
}

Step "Camera program packages (the first time downloads EasyOCR, about 1 GB)"
Push-Location $Anpr
try { Run { uv sync --extra easyocr } } finally { Pop-Location }

Step "Fresh device keys for the webcam (entry + exit lanes)"
Push-Location $Backend
try { Run { uv run python -m app.webcam_devices } } finally { Pop-Location }

if (-not $NoBrowser) {
    try {
        Invoke-WebRequest -Uri $ConsoleUrl -UseBasicParsing -TimeoutSec 3 | Out-Null
        Start-Process "$ConsoleUrl/login?next=/guard"
        Write-Host "Opened the guard console (sign in with the guard demo login)."
    } catch {
        Write-Host "The web app isn't running at $ConsoleUrl (cd frontend; npm run dev)." -ForegroundColor Yellow
    }
}

Step "Starting the camera (Ctrl+C to stop)"
Write-Host "Hold a plate up to the camera: a photo on your phone, or a printout of"
Write-Host "anpr\data\demo-plates.html. Keys: E = entry lane, X = exit lane, Space = scan again."
Push-Location $Anpr
try {
    $cameraArgs = @("run", "gatesense-anpr", "--source", $Camera, "--preview")
    if ($NoBrowser) { $cameraArgs += "--no-browser" }
    & uv @cameraArgs
} finally {
    Pop-Location
}
