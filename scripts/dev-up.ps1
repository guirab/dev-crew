# Sobe NATS (JetStream) + dev-crew num terminal só. Ctrl+C encerra os dois.
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\dev-up.ps1 [-Real] [-Speed 3] [-Escalate]
#   sem -Real: agentes e Azure fake (zero tokens)
param(
    [switch]$Real,
    [double]$Speed = 3,
    [switch]$Escalate
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

$store = Join-Path $HOME '.dev-crew\nats'
New-Item -ItemType Directory -Force $store | Out-Null

$natsUp = $false
try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', 4222); $c.Close(); $natsUp = $true } catch {}
$nats = $null
if (-not $natsUp) {
    $nats = Start-Process -FilePath 'nats-server' -ArgumentList @('-js', '-a', '127.0.0.1', '-p', '4222', '-sd', $store, '-m', '8222') -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 800
    Write-Host "nats-server pid $($nats.Id)"
} else {
    Write-Host 'nats já está rodando em 4222'
}

try {
    Push-Location (Join-Path $root 'backend')
    uv run crew streams init
    $crewArgs = @('run', 'crew', 'up')
    if (-not $Real) { $crewArgs += @('--fake-agents', '--fake-azure', '--fake-speed', "$Speed") }
    if ($Escalate) { $crewArgs += '--fake-escalate' }
    & uv @crewArgs
} finally {
    Pop-Location
    if ($nats) { Stop-Process -Id $nats.Id -ErrorAction SilentlyContinue }
}
