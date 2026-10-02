# Instalador do Tracker de Gestão do Tempo
# Uso: clique com o botão direito > "Executar com o PowerShell"
#   ou: powershell -ExecutionPolicy Bypass -File setup.ps1
param(
    [string]$Nome,
    [string]$Email,
    [switch]$SemTarefas,   # não cria as tarefas agendadas
    [switch]$SemExecutar   # não roda o tracker no final
)
$ErrorActionPreference = "Continue"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "`n=== Tracker de Gestão do Tempo - instalação ===`n" -ForegroundColor Cyan

Push-Location $dir

# 1) Python
$pyOk = $false
try { $v = & python --version 2>&1; $pyOk = ($LASTEXITCODE -eq 0) -and ("$v" -match "Python 3\.(1[0-9])") } catch {}
if (-not $pyOk) {
    Write-Host "Python não encontrado. Instale o Python 3.12 pela Microsoft Store (ou python.org, marcando 'Add python.exe to PATH') e rode este instalador de novo." -ForegroundColor Yellow
    Pop-Location; exit 1
}
Write-Host "[1/5] Python: $(& python --version)"

# 2) Bibliotecas
Write-Host "[2/5] Instalando bibliotecas..."
& python -m pip install --quiet --user openpyxl icalendar recurring-ical-events
if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao instalar bibliotecas (proxy/rede?)." -ForegroundColor Red; Pop-Location; exit 1 }

# 3) Configuração pessoal
$cfgPath = Join-Path $dir "config.json"
if (Test-Path $cfgPath) {
    Write-Host "[3/5] config.json já existe - mantido."
} else {
    if (-not $Nome)  { $Nome  = Read-Host "Seu nome (aparece nos relatórios)" }
    if (-not $Email) { $Email = Read-Host "Seu e-mail corporativo (o mesmo do Chrome)" }
    try { $cfg = Get-Content (Join-Path $dir "config.example.json") -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop }
    catch { Write-Host "config.example.json inválido: $_" -ForegroundColor Red; Pop-Location; exit 1 }
    $cfg.nome = $Nome
    $cfg.email = $Email
    $today = Get-Date
    $cfg.relatorios_a_partir_de = $today.AddDays(-(([int]$today.DayOfWeek + 6) % 7)).ToString("yyyy-MM-dd")  # segunda desta semana
    $json = $cfg | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText($cfgPath, $json, (New-Object Text.UTF8Encoding $false))
    Write-Host "[3/5] config.json criado para $Nome <$Email>."
}

# 4) Confere se o Chrome tem a conta
& python -c "import sources, json; cfg=json.load(open(r'$cfgPath', encoding='utf-8')); p=sources.find_profile(cfg['email']); v=sources.meet_visits(p); print(f'[4/5] Chrome: perfil encontrado, {len(v)} visitas ao Meet no histórico')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Não achei um perfil do Chrome logado com esse e-mail. Entre no Chrome com a conta corporativa e rode de novo." -ForegroundColor Red
    Remove-Item $cfgPath -ErrorAction SilentlyContinue  # deixa refazer com o e-mail certo
    Pop-Location; exit 1
}

# 5) Tarefas agendadas + primeira execução
if (-not $SemTarefas) {
    & (Join-Path $dir "install_tasks.ps1")
    Write-Host "[5/5] Tarefas agendadas criadas (microfone a cada minuto; dashboard e relatórios toda segunda às 9h)."
} else { Write-Host "[5/5] Tarefas agendadas: puladas." }
if (-not $SemExecutar) {
    & python (Join-Path $dir "tracker.py") --open
}
Write-Host "`nPronto! Próximo passo: configurar a exportação da agenda (Apps Script) - veja o guia." -ForegroundColor Green
Pop-Location
