# Sobe NATS (JetStream, via Docker se disponível) + dev-crew num terminal só. Ctrl+C encerra o dev-crew.
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\dev-up.ps1 [-Real] [-Speed 3] [-Escalate]
#   sem -Real: agentes fake (zero tokens)
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

# Docker Desktop fechado: abre e espera o engine (NATS e o sandbox dos agentes dependem dele)
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker version --format '{{.Server.Version}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (Test-Path $desktop) {
            Write-Host 'abrindo o Docker Desktop...'
            Start-Process $desktop
            $deadline = (Get-Date).AddMinutes(3)
            do {
                Start-Sleep -Seconds 3
                docker version --format '{{.Server.Version}}' 2>$null | Out-Null
            } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $deadline)
            if ($LASTEXITCODE -ne 0) { throw 'o engine do Docker não subiu em 3 min' }
        }
    }
}
if (-not $natsUp -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    # Docker primeiro: o Smart App Control do Windows pode bloquear o nats-server.exe
    docker compose -f (Join-Path $root 'infra\docker-compose.yml') up -d
    if ($LASTEXITCODE -ne 0) { throw 'docker compose falhou: o Docker Desktop está aberto?' }
    Start-Sleep -Seconds 2
    Write-Host 'nats via docker (fica rodando; pare com: docker compose -f infra/docker-compose.yml down)'
} elseif (-not $natsUp) {
    $nats = Start-Process -FilePath 'nats-server' -ArgumentList @('-js', '-a', '127.0.0.1', '-p', '4222', '-sd', $store, '-m', '8222') -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 800
    Write-Host "nats-server pid $($nats.Id)"
} else {
    Write-Host 'nats já está rodando em 4222'
}

try {
    Push-Location (Join-Path $root 'backend')
    # python -m em vez do crew.exe: o Smart App Control bloqueia o lançador não assinado que o uv gera
    uv run python -m crew.cli streams init
    $crewArgs = @('run', 'python', '-m', 'crew.cli', 'up')
    if (-not $Real) { $crewArgs += @('--fake-agents', '--fake-speed', "$Speed") }
    if ($Escalate) { $crewArgs += '--fake-escalate' }
    & uv @crewArgs
} finally {
    Pop-Location
    if ($nats) { Stop-Process -Id $nats.Id -ErrorAction SilentlyContinue }
}
