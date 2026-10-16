param(
    [switch]$GenerateToken,
    [switch]$Doctor,
    [switch]$RevealToken
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Output "Created .env from .env.example."
}

if ($GenerateToken) {
    uv run --locked my-last-ai-girlfriends generate-token
}

if ($Doctor) {
    $env:PYTHONPATH = Join-Path $Root "src"
    uv run --locked python -m my_last_ai_girlfriends.main doctor
}

if ($RevealToken) {
    $line = Get-Content -LiteralPath ".env" | Where-Object { $_ -match '^MLAG_AUTH_TOKEN=' } | Select-Object -First 1
    if (-not $line) { throw "MLAG_AUTH_TOKEN is not present in .env" }
    Write-Output "Explicit token reveal requested; protect this terminal output."
    Write-Output ($line.Substring("MLAG_AUTH_TOKEN=".Length))
}

if (-not $GenerateToken -and -not $Doctor -and -not $RevealToken) {
    uv sync --locked
    Write-Output "Setup complete. Run .\scripts\setup.ps1 -GenerateToken -Doctor, then start with: uv run --locked my-last-ai-girlfriends"
}
