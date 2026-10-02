# Liga o preenchimento automático do Clockwork (Jira) no tracker já instalado.
# Uso: clique com o botão direito > "Executar com o PowerShell"
#   ou: powershell -ExecutionPolicy Bypass -File setup_clockwork.ps1
$ErrorActionPreference = "Continue"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "`n=== Clockwork automático - instalação ===`n" -ForegroundColor Cyan
Push-Location $dir

if (-not (Test-Path (Join-Path $dir "config.json"))) {
    Write-Host "O tracker ainda não foi instalado. Rode primeiro o setup.ps1." -ForegroundColor Yellow
    Pop-Location; exit 1
}

# 1) Biblioteca que guarda o token no Gerenciador de Credenciais do Windows
Write-Host "[1/4] Instalando biblioteca de credenciais..."
& python -m pip install --quiet --user keyring
if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao instalar o keyring (proxy/rede?)." -ForegroundColor Red; Pop-Location; exit 1 }

# 2) Configuração das iniciativas
$cwPath = Join-Path $dir "clockwork.json"
if (Test-Path $cwPath) {
    Write-Host "[2/4] clockwork.json já existe - mantido."
} else {
    Copy-Item (Join-Path $dir "clockwork.example.json") $cwPath
    Write-Host "[2/4] clockwork.json criado (iniciativas, rotinas e regras)."
}

# 3) Token da API do Jira
Write-Host "[3/4] Token da API do Jira"
Write-Host "      Vou abrir a página do Atlassian. Clique em 'Criar token da API', dê o nome 'meeting-tracker',"
Write-Host "      escolha a validade máxima, clique em Criar e depois em Copiar."
Start-Process "https://id.atlassian.com/manage-profile/security/api-tokens"
& python (Join-Path $dir "tracker.py") clockwork token
if ($LASTEXITCODE -ne 0) {
    Write-Host "Não consegui conectar no Jira com esse token. Confira se copiou o token inteiro e rode de novo." -ForegroundColor Red
    Pop-Location; exit 1
}

# 4) Simulação e confirmação
Write-Host "`n[4/4] Simulação: isto é o que seria lançado (nada foi gravado ainda)`n" -ForegroundColor Cyan
& python (Join-Path $dir "tracker.py") clockwork --simular
$ok = Read-Host "`nLançar esses dias no Clockwork agora e ligar o lançamento automático de toda segunda? (S/N)"
if ($ok -match '^[sS]') {
    $cfg = (Get-Content $cwPath -Raw -Encoding UTF8) -replace '"ativo":\s*false', '"ativo": true'
    [IO.File]::WriteAllText($cwPath, $cfg, (New-Object Text.UTF8Encoding $false))
    & python (Join-Path $dir "tracker.py") clockwork
    Write-Host "`nPronto! Toda segunda às 9h, junto com o relatório, a semana anterior é lançada sozinha." -ForegroundColor Green
    Write-Host "Histórico dos lançamentos: clockwork_lancamentos.csv (nesta pasta)."
} else {
    $cfg = Get-Content $cwPath -Raw -Encoding UTF8
    $cfg = $cfg -replace '"ativo":\s*true', '"ativo": false'
    [IO.File]::WriteAllText($cwPath, $cfg, (New-Object Text.UTF8Encoding $false))
    Write-Host "`nNada foi lançado e o automático ficou desligado. Ajuste o clockwork.json e rode este instalador de novo." -ForegroundColor Yellow
}
Pop-Location
