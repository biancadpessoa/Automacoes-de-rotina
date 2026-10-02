# Gestão do Tempo Automática + Clockwork

Mede sozinho quanto tempo você passa em reuniões (Google Meet, Google Agenda e microfone do Windows) e gera relatórios semanais e mensais no Google Drive. Também lança as horas no **Clockwork (Jira)**, divididas pelas iniciativas em que você trabalhou na semana.

Nada precisa ser preenchido à mão. Os dados ficam no seu computador (`tracker.db`) e no seu Google Drive.

## O que faz

| Parte | Quando roda | O que faz |
|---|---|---|
| Microfone | A cada 1 min | Anota quando o Chrome usa o microfone, o que dá o horário real de fim de cada call. |
| Dashboard e relatórios | Segundas, 9h | Atualiza o dashboard e salva o relatório semanal (e, no início do mês, o mensal) na pasta `Gestão do tempo - relatórios` do Drive. |
| Clockwork | Segundas, 9h, junto com os relatórios | Lança no Jira 8h por dia útil da semana anterior, divididas por iniciativa. |

Os números contam o tempo em que você **realmente esteve** na call, não o tempo marcado na agenda. Para isso, três fontes são cruzadas:

- **Histórico do Chrome:** as salas do Meet em que você entrou.
- **Google Agenda:** nome da reunião, se é recorrente e se você aceitou. Chega por meio do `agenda_export.gs`.
- **Microfone do Windows:** o momento em que você saiu de fato da call.

## Requisitos

- Windows 10 ou 11
- Google Chrome logado com a conta corporativa
- Python 3.10 ou mais novo (Microsoft Store → "Python 3.12")
- Google Drive para desktop, com a unidade `G:\Meu Drive`
- Acesso ao script.google.com e a um token da API do Atlassian (este só para o Clockwork)

## Instalação

1. Baixe a pasta `meeting-tracker` (deste repositório ou do zip do kit) e extraia em `C:\Users\<seu usuário>\`.
2. Clique com o botão direito em **`setup.ps1`** e escolha **Executar com o PowerShell**. Ele instala o tracker e cria as tarefas agendadas.
3. Configure a exportação da agenda (`agenda_export.gs`) em script.google.com. Os passos estão no PDF *Gestão do Tempo Automática - Passo a passo*.
4. Para o Clockwork, clique com o botão direito em **`setup_clockwork.ps1`** e escolha **Executar com o PowerShell**. Ele:
   - instala a biblioteca que guarda o token no Gerenciador de Credenciais do Windows;
   - cria o `clockwork.json` com as iniciativas;
   - abre a página do Atlassian para você criar o token (nome: `meeting-tracker`) e colar no PowerShell;
   - mostra uma **simulação** e só lança se você responder **S**.

> Se o Windows bloquear o script, rode no PowerShell:
> `powershell -ExecutionPolicy Bypass -File "$HOME\meeting-tracker\setup_clockwork.ps1"`

## Como o Clockwork divide cada dia

Cada dia útil recebe 8h (`horas_dia`), divididas assim:

1. **Rotinas** (dailies, weeklies, WBR, planning, retro, 1:1s, treinamentos) vão para a iniciativa de rotinas pelo **tempo real** da reunião.
2. **Iniciativas com `peso_fixo`** recebem essa fração do tempo restante toda semana, mesmo sem reunião. Hoje a PLATSERV-4063 tem 30%.
3. **O restante** vai para as iniciativas **na proporção das reuniões de cada tema na semana**. Uma única reunião de 30 min não decide o dia inteiro. Reuniões sem tema ("Outros") não pesam na divisão.
4. **Lançamentos de menos de 30 min** (`minimo_minutos`) são somados à maior iniciativa do dia.

Os lançamentos do dia saem em sequência a partir das 09:00, em múltiplos de 15 min. Cada um leva o comentário `Automático (meeting-tracker) - <reuniões que justificam>`.

**O que nunca é lançado:**
- Feriados e folgas listados em `dias_sem_expediente`, no `config.json`.
- Dias em que você **já lançou qualquer coisa**. A automação não duplica nem sobrescreve.
- Dias úteis **sem nenhuma reunião medida**, porque provavelmente são ausência. Esses dias aparecem na saída para você lançar à mão, se foram dias trabalhados.
- O dia de hoje.

## Iniciativas configuradas

| Issue | Iniciativa | Exemplos de reunião |
|---|---|---|
| [PLATSERV-5270](https://madeiramadeira.atlassian.net/browse/PLATSERV-5270) | Rotinas e dia a dia | Daily, Weekly, WBR, 1:1, Planning, Retro |
| [PLATSERV-5274](https://madeiramadeira.atlassian.net/browse/PLATSERV-5274) | Autoatendimento pós-venda (Bot CX WhatsApp / Mercado Livre) | Testes Bot, Fluxo de cancelamento |
| [PLATSERV-5275](https://madeiramadeira.atlassian.net/browse/PLATSERV-5275) | Serviços em marketplaces (Shopee / Mercado Livre / Installation Services) | MM <> Shopee, Installation Services |
| [PLATSERV-4062](https://madeiramadeira.atlassian.net/browse/PLATSERV-4062) | Extinguir a plataforma da venda legada | Venda legada, desconto progressivo, VTEX |
| [PLATSERV-1731](https://madeiramadeira.atlassian.net/browse/PLATSERV-1731) | Agente de preço fixo / agente de vendas | Agent de Vendas, Proposta de Valor |
| [PLATSERV-4063](https://madeiramadeira.atlassian.net/browse/PLATSERV-4063) | Pesquisas com usuário (peso fixo de 30%) | Pesquisa, entrevista, discovery |

Para mudar, abra o `clockwork.json` no Bloco de Notas:

- **`regras`** são os termos procurados no título da reunião (em minúsculas; aceita regex).
- Cada reunião vai para a **primeira** iniciativa cujo termo aparece no título. Só depois disso as rotinas são verificadas, então o tema vence o ritual: "Refinamento - Fluxo de Cancelamento" vai para o Bot CX.
- Mantenha as aspas e vírgulas. Teste sempre com `--simular` antes.

## Comandos

```powershell
python "$HOME\meeting-tracker\tracker.py" --open                 # abre o dashboard
python "$HOME\meeting-tracker\tracker.py" clockwork --simular    # mostra o que seria lançado (não grava nada)
python "$HOME\meeting-tracker\tracker.py" clockwork              # lança agora os dias pendentes
python "$HOME\meeting-tracker\tracker.py" clockwork token        # troca o token do Jira (ex.: venceu)
python "$HOME\meeting-tracker\tracker.py" relatorio semanal 2026-09-25   # gera de novo um relatório
```

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `tracker.py` | Ponto de entrada: sincroniza os dados e gera o dashboard, os relatórios e o Clockwork. |
| `clockwork.py` | Divide as horas por iniciativa e lança os worklogs pela API do Jira. |
| `clockwork.example.json` | Modelo do `clockwork.json` (iniciativas, regras e parâmetros). |
| `setup.ps1` / `install_tasks.ps1` | Instalador do tracker e das tarefas agendadas do Windows. |
| `setup_clockwork.ps1` | Instalador do Clockwork (token, simulação e confirmação). |
| `sources.py`, `sessions.py`, `calendar_ics.py` | Leitura do Chrome, do microfone e da agenda. |
| `report.py`, `export_xlsx.py`, `dashboard_template.html` | Relatórios e dashboard. |
| `agenda_export.gs` | Script do Google Apps Script que exporta a agenda para o Drive. |

Gerados no seu computador e **fora do Git** (`.gitignore`):

- `config.json` e `clockwork.json`: suas configurações.
- `tracker.db`: o histórico de reuniões.
- `clockwork_lancamentos.csv`: tudo o que foi lançado, com data, issue, minutos e id do worklog.
- `clockwork_erros.log`: falhas da execução automática.
- `dashboard.html` e as planilhas `.xlsx`.

## Problemas comuns

| Sintoma | Como resolver |
|---|---|
| Nada foi lançado na segunda | Veja o `clockwork_erros.log`. Se o PC estava desligado às 9h, a tarefa roda quando ele ligar. |
| `HTTP 401` no log | O token venceu ou foi copiado incompleto. Rode `tracker.py clockwork token`. |
| Lançou na iniciativa errada | Corrija ou apague direto no Clockwork e ajuste as `regras` no `clockwork.json`. |
| Um dia trabalhado não foi lançado | Ele não tinha nenhuma reunião medida. Lance à mão, porque o tracker não mexe em dias já lançados. |
| Quero pausar | No `clockwork.json`, troque `"ativo": true` por `"ativo": false`. |

## Segurança e privacidade

- O token do Jira fica **só** no Gerenciador de Credenciais do Windows, nunca em arquivo ou no Git.
- Os worklogs são criados com `notifyUsers=false`, então ninguém é notificado a cada lançamento.
- Limitações: calls pelo celular, por outro navegador ou outro perfil do Chrome, Zoom e Teams não são detectadas.

## Desinstalar

```powershell
Unregister-ScheduledTask -TaskName 'MeetingTracker*' -Confirm:$false
```

Depois:

- apague a pasta `meeting-tracker`;
- exclua o projeto "Exportar agenda" no script.google.com;
- revogue o token "meeting-tracker" em https://id.atlassian.com/manage-profile/security/api-tokens.
