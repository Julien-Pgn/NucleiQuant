# NucleiQuant launcher for Windows (called by "Start NucleiQuant.bat").
# Checks Docker Desktop, prepares the app the first time, starts it and opens the browser.

$ErrorActionPreference = "Stop"
$AppName = "NucleiQuant"
$ImageLocal = "nucleiquant:v2"
$ImageRemote = "ghcr.io/julien-pgn/nucleiquant:2.0"
$Container = "nucleiquant-app"
$Port = if ($env:NQ_PORT) { $env:NQ_PORT } else { "8765" }
$Url = "http://localhost:$Port"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Say($m) { Write-Host "`n$m" -ForegroundColor White }
function Info($m) { Write-Host "  $m" }
function Fail($m) { Write-Host "`n$m" -ForegroundColor Red; Read-Host "Press Enter to close this window"; exit 1 }
function DockerOk { docker info *> $null; return ($LASTEXITCODE -eq 0) }

Say "Starting $AppName"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker is not installed. Install Docker Desktop (https://www.docker.com/products/docker-desktop/), start it, then run this again."
}
if (-not (DockerOk)) {
    $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dd) { Info "Starting Docker Desktop..."; Start-Process $dd }
    for ($i = 0; $i -lt 60 -and -not (DockerOk); $i++) { Start-Sleep 2 }
    if (-not (DockerOk)) { Fail "Docker Desktop is not running. Start it, wait until it's ready, then run this again." }
}

$running = docker ps --format "{{.Names}}" | Where-Object { $_ -eq $Container }
if (-not $running) {
    $Image = $ImageLocal
    docker image inspect $ImageLocal *> $null
    if ($LASTEXITCODE -ne 0) {
        docker pull $ImageRemote *> $null
        if ($LASTEXITCODE -eq 0) { $Image = $ImageRemote }
        else {
            Say "First start: preparing $AppName (one time, about 10 GB, 10-30 min)"
            docker build -t $ImageLocal $Repo
            if ($LASTEXITCODE -ne 0) { Fail "Preparing the app failed. Check your internet connection and free disk space (~30 GB)." }
        }
    }

    $gpu = @()
    docker run --rm --gpus all $Image nvidia-smi -L *> $null
    if ($LASTEXITCODE -eq 0) { $gpu = @("--gpus", "all"); Info "NVIDIA GPU found: segmentation will be fast." }
    else { Info "No usable NVIDIA GPU: using the CPU (works well, a little slower)." }

    # Folders the app may open: your user folder and every other drive
    $mounts = @("-v", "${Repo}:/workspace", "-v", "$($env:USERPROFILE):/host/home")
    $roots = @("/host/home")
    $map = @("/host/home=$($env:USERPROFILE)")
    foreach ($d in Get-PSDrive -PSProvider FileSystem) {
        if ($d.Root -and $d.Root -ne "$($env:SystemDrive)\" -and (Test-Path $d.Root)) {
            $letter = $d.Name.ToLower()
            $mounts += @("-v", "$($d.Root):/host/$letter")
            $roots += "/host/$letter"
            $map += "/host/$letter=$($d.Name):\"
        }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $env:USERPROFILE ".nucleiquant\numba_cache") | Out-Null

    docker rm -f $Container *> $null
    Say "Launching"
    $dockerArgs = @("run", "-d", "--rm", "--name", $Container) + $gpu + @("--shm-size=4g", "-p", "127.0.0.1:${Port}:8765") + $mounts + @(
        "-e", "HOME=/tmp",
        "-e", "NQ_ROOTS=$($roots -join ':')",
        "-e", "NQ_PATH_MAP=$($map -join ';')",
        "-e", "NQ_STATE_DIR=/host/home/.nucleiquant",
        "-e", "NUMBA_CACHE_DIR=/host/home/.nucleiquant/numba_cache",
        "-e", "TF_CPP_MIN_LOG_LEVEL=3",
        "-w", "/workspace", $Image, "python", "-m", "nucleiquant", "serve", "--host", "0.0.0.0", "--port", "8765")
    & docker @dockerArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "The app could not start. Is port $Port used by another program?" }
}

$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest -UseBasicParsing "$Url/api/health" -TimeoutSec 2 | Out-Null; $ok = $true; break } catch { Start-Sleep 1 }
}
if (-not $ok) { Fail "The app did not answer. See: docker logs $Container" }

Say "$AppName is ready: $Url"
Start-Process $Url
Info "Keep this window open while you work. Quit from the app, or close this window to stop it."
try {
    while (docker ps --format "{{.Names}}" | Where-Object { $_ -eq $Container }) { Start-Sleep 2 }
} finally {
    docker stop $Container *> $null
}
Say "$AppName has stopped."
