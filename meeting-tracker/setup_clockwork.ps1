# Liga o preenchimento automático do Clockwork (Jira) no tracker já instalado.
# Uso: clique com o botão direito > "Executar com o PowerShell"
#   ou: powershell -ExecutionPolicy Bypass -File setup_clockwork.ps1
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
function Sair($code) { Pop-Location; Read-Host "`nPressione Enter para fechar"; exit $code }
# arquivos baixados da internet ficam marcados como bloqueados pelo Windows
Get-ChildItem $dir -File | Unblock-File -ErrorAction SilentlyContinue
Write-Host "`n=== Clockwork automático - instalação ===`n" -ForegroundColor Cyan
Push-Location $dir

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python não encontrado. Instale o Python 3.12 pela Microsoft Store e rode de novo." -ForegroundColor Yellow
    Sair 1
}

# O tracker pode estar instalado em outra pasta: a tarefa agendada de segunda sabe qual é
if (-not (Test-Path (Join-Path $dir "config.json"))) {
    $candidatos = @()
    $tarefa = Get-ScheduledTask -TaskName "MeetingTracker - Dashboard" -ErrorAction SilentlyContinue
    if ($tarefa) { $candidatos += $tarefa.Actions[0].WorkingDirectory }
    $candidatos += (Join-Path $HOME "meeting-tracker")
    $instalado = $candidatos | Where-Object { $_ -and ($_ -ne $dir) -and (Test-Path (Join-Path $_ "config.json")) } | Select-Object -First 1
    if ($instalado) {
        Write-Host "Tracker encontrado em $instalado - copiando os arquivos novos para lá..."
        $novos = "clockwork.py", "clockwork.example.json", "tracker.py", "setup.ps1", "setup_clockwork.ps1",
                 "Instalar Clockwork.cmd", "CLOCKWORK - LEIA-ME.txt", "LEIA-ME.txt"
        foreach ($f in $novos) { Copy-Item (Join-Path $dir $f) $instalado -Force }
        Get-ChildItem $instalado -File | Unblock-File -ErrorAction SilentlyContinue
        Pop-Location
        $dir = $instalado
        Push-Location $dir
    } else {
        Write-Host "O tracker de reuniões ainda não está instalado neste computador." -ForegroundColor Yellow
        Write-Host "Vou instalar agora: ele vai pedir seu nome e seu e-mail corporativo (o mesmo do Chrome).`n"
        $destino = Join-Path $HOME "meeting-tracker"
        if ($dir -ne $destino) {  # instala sempre na pasta padrão, não em Downloads
            New-Item -ItemType Directory -Force $destino | Out-Null
            Copy-Item (Join-Path $dir "*") $destino -Recurse -Force
            Get-ChildItem $destino -File | Unblock-File -ErrorAction SilentlyContinue
            Pop-Location
            $dir = $destino
            Push-Location $dir
            Write-Host "Arquivos copiados para $dir`n"
        }
        & (Join-Path $dir "setup.ps1") -SemExecutar
        if (-not (Test-Path (Join-Path $dir "config.json"))) {
            Write-Host "A instalação do tracker não terminou. Leia a mensagem acima, corrija e rode de novo." -ForegroundColor Red
            Sair 1
        }
        Write-Host "`nTracker instalado. Continuando com o Clockwork...`n" -ForegroundColor Green
    }
}

# 1) Biblioteca que guarda o token no Gerenciador de Credenciais do Windows
Write-Host "[1/4] Instalando biblioteca de credenciais..."
& python -m pip install --quiet --user keyring
if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao instalar o keyring (proxy/rede?)." -ForegroundColor Red; Sair 1 }

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
    Sair 1
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
Sair 0
