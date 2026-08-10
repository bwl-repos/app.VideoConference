# BWL VideoConference - Publicacao (git push + deploy AWS Lightsail)
#
# O servidor (Lightsail 18.230.96.137, /opt/bwl/app) NAO e um checkout git: o
# deploy manda o codigo-fonte por scp e builda no Docker. Este script:
#   1. commita + da push no GitHub (GabrielBitencourtt/bwl-videoconference);
#   2. empacota frontend/ e/ou backend/ (sem node_modules/dist/.git);
#   3. envia o pacote pra Lightsail e extrai em /opt/bwl/app;
#   4. rebuilda os servicos afetados no docker compose.
#
# Uso:
#   powershell -File publish.ps1                       (interativo)
#   powershell -File publish.ps1 -Part frontend        (so o frontend)
#   powershell -File publish.ps1 -Part all -Message "x"
#   powershell -File publish.ps1 -NoGit                (nao commita/push, so deploy)

param(
    [ValidateSet('frontend', 'backend', 'all', '')]
    [string]$Part = '',
    [string]$Message,
    [switch]$NoGit
)

# 'Continue', nao 'Stop': git, ssh, scp e docker escrevem informacao NORMAL no stderr
# (avisos de CRLF, progresso do push, log do build). Com 'Stop' o PowerShell 5.1
# transforma cada uma dessas linhas em erro terminante e o script morre no meio de um
# passo que deu certo -- foi o que abortava a publicacao logo apos o push. Quem decide
# se um comando falhou e o $LASTEXITCODE, checado apos cada chamada.
$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

$Remote = 'ubuntu@18.230.96.137'
$Pem    = Join-Path $PSScriptRoot 'infra\.secrets\bwl-lightsail.pem'
$AppDir = '/opt/bwl/app'
$SshOpt = @('-o', 'StrictHostKeyChecking=accept-new', '-i', $Pem)

function Fail($msg) { Write-Host "[ERRO] $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Pem)) { Fail "chave nao encontrada: $Pem" }
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) { Fail 'ssh (OpenSSH) nao encontrado no PATH.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'git nao encontrado no PATH.' }
if (-not (Get-Command tar -ErrorAction SilentlyContinue)) { Fail 'tar nao encontrado no PATH.' }

# --- 1. Git: commit + push -------------------------------------------------
if (-not $NoGit) {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    $pending = git status --porcelain
    if (-not [string]::IsNullOrWhiteSpace($pending)) {
        Write-Host 'Alteracoes pendentes:' -ForegroundColor Cyan
        git status --short
        if ([string]::IsNullOrWhiteSpace($Message)) {
            $Message = Read-Host 'Mensagem do commit (Enter = "Publicacao webconference")'
            if ([string]::IsNullOrWhiteSpace($Message)) { $Message = 'Publicacao webconference' }
        }
        git add -A
        git commit -m $Message
        if ($LASTEXITCODE -ne 0) { Fail 'falha no commit.' }
    } else {
        Write-Host 'Nada novo para commitar.' -ForegroundColor Yellow
    }
    Write-Host "Push para origin/$branch ..." -ForegroundColor Cyan
    git push origin $branch
    if ($LASTEXITCODE -ne 0) { Fail 'falha no push.' }
}

# --- 2. Escolher o que publicar -------------------------------------------
if ([string]::IsNullOrWhiteSpace($Part)) {
    Write-Host ''
    Write-Host '  1) Frontend   2) Backend   3) Ambos' -ForegroundColor Cyan
    $c = Read-Host 'O que publicar na Lightsail? [1]'
    switch ($c) {
        '2' { $Part = 'backend' }
        '3' { $Part = 'all' }
        default { $Part = 'frontend' }
    }
}
$parts = if ($Part -eq 'all') { @('frontend', 'backend') } else { @($Part) }
Write-Host "Publicando: $($parts -join ', ')" -ForegroundColor Cyan

# --- 3. Empacota + envia + extrai -----------------------------------------
$tar = Join-Path $env:TEMP 'bwl-deploy.tgz'
if (Test-Path $tar) { Remove-Item $tar -Force }
$excludes = @(
    '--exclude=node_modules', '--exclude=dist', '--exclude=.git',
    '--exclude=__pycache__', '--exclude=.venv', '--exclude=*.pyc'
)
Write-Host 'Empacotando source...' -ForegroundColor Cyan
# Monta os argumentos num array e passa expandido — o splat `@` do PS 5.1 nao
# expande arrays de forma confiavel para executaveis nativos (gera args vazios).
$tarArgs = @('czf', $tar) + $excludes + $parts
tar $tarArgs
if ($LASTEXITCODE -ne 0) { Fail 'falha ao empacotar (tar).' }

Write-Host 'Enviando para a Lightsail...' -ForegroundColor Cyan
scp @SshOpt $tar "${Remote}:/tmp/bwl-deploy.tgz"
if ($LASTEXITCODE -ne 0) { Fail 'falha no scp.' }

# --- 4. Extrai + rebuilda os servicos afetados ----------------------------
$build = @("cd $AppDir", 'tar xzf /tmp/bwl-deploy.tgz', 'rm -f /tmp/bwl-deploy.tgz')
if ($parts -contains 'backend')  { $build += 'docker compose up -d --build backend' }
if ($parts -contains 'frontend') { $build += 'docker compose run --rm frontend-build'; $build += 'docker compose restart caddy' }
$remoteCmd = ($build -join ' && ')

Write-Host 'Build + restart no servidor (pode levar 1-3 min)...' -ForegroundColor Cyan
ssh @SshOpt $Remote $remoteCmd
if ($LASTEXITCODE -ne 0) { Fail 'falha no build/restart remoto.' }

Write-Host ''
Write-Host '[OK] Publicado em https://video.pbltools.io (limpe o cache: Ctrl+Shift+R).' -ForegroundColor Green
exit 0
