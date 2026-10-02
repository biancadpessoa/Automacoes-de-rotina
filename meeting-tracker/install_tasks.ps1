# Cria as tarefas agendadas do tracker (usuário atual, sem precisar de admin).
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw = (Get-Command pythonw.exe).Source

# 1) Microfone: a cada minuto registra quando o Chrome está usando o microfone (sem janela)
$a1 = New-ScheduledTaskAction -Execute $pyw -Argument "`"$dir\tracker.py`" mic" -WorkingDirectory $dir
$t1 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
# 2) Dashboard + relatórios: toda segunda às 9h (se o PC estiver desligado, roda ao ligar)
$a2 = New-ScheduledTaskAction -Execute $pyw -Argument "`"$dir\tracker.py`"" -WorkingDirectory $dir
$t2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9am

$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "MeetingTracker - Microfone" -Action $a1 -Trigger $t1 -Settings $s -Force | Out-Null
Register-ScheduledTask -TaskName "MeetingTracker - Dashboard" -Action $a2 -Trigger $t2 -Settings $s -Force | Out-Null
"Tarefas criadas. Para remover: Unregister-ScheduledTask -TaskName 'MeetingTracker*' -Confirm:`$false"

