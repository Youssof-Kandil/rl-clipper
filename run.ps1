# Start RL Clipper: installs deps on first run, builds the UI, opens the browser.
#   .\run.ps1          normal start (http://127.0.0.1:8765)
#   .\run.ps1 -Dev     backend with reload + Vite dev server on :5173
param([switch]$Dev, [int]$Port = 8765)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
# Pick up tools installed by winget in this session.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

foreach ($cmd in "ffmpeg", "uv", "npm") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        $hint = @{ ffmpeg = "winget install Gyan.FFmpeg"; uv = "winget install astral-sh.uv"; npm = "install Node.js 20+" }[$cmd]
        throw "$cmd not found. Install it with: $hint"
    }
}

# NVIDIA card: also install cuBLAS/cuDNN (~1 GB) so captions transcribe on the GPU.
$groups = if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { @("--group", "gpu") } else { @() }

Push-Location "$root\backend"
uv sync --quiet @groups
Pop-Location

Push-Location "$root\frontend"
if (-not (Test-Path node_modules)) { npm install --silent }
if ($Dev) {
    Start-Process -NoNewWindow npm -ArgumentList "run", "dev"
} else {
    npm run build --silent
}
Pop-Location

$url = if ($Dev) { "http://localhost:5173" } else { "http://127.0.0.1:$Port" }
Write-Host "RL Clipper running at $url" -ForegroundColor Cyan
Start-Process $url

Push-Location "$root\backend"
$reload = if ($Dev) { "--reload" } else { $null }
uv run @groups uvicorn app.main:app --host 127.0.0.1 --port $Port $reload
Pop-Location
