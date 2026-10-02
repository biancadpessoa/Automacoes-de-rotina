"""Tracker de tempo em reuniões.

    python tracker.py        -> sincroniza dados e gera dashboard.html
    python tracker.py mic    -> registra a sessão atual de microfone (rodar a cada minuto)
    python tracker.py clockwork [--simular|token] -> lança as horas no Clockwork (ver clockwork.py)
"""
import json
import os
import re
import sqlite3
import sys
import webbrowser
from datetime import datetime, timedelta

import sources
from sessions import build_sessions

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "tracker.db")
CALL_APPS = ("chrome.exe",)


def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def db():
    con = sqlite3.connect(DB)
    con.executescript("""
        create table if not exists visits (code text, start text, end text, title text, origin text,
                                           primary key (code, start));
        create table if not exists mic (app text, start text, stop text, primary key (app, start));
    """)
    return con


def log_mic():
    con = db()
    for app, (start, stop) in sources.read_mic_usage().items():
        con.execute("insert or replace into mic values (?,?,?)",
                    (app, start.isoformat(), stop.isoformat() if stop else None))
    con.commit()


def sync_history(con, email):
    """O Chrome apaga histórico com mais de 90 dias; guardamos tudo no nosso banco."""
    for v in sources.meet_visits(sources.find_profile(email)):
        con.execute("insert or replace into visits values (?,?,?,?,?)",
                    (v["code"], v["start"].isoformat(), v["end"].isoformat(), v["title"], v["origin"]))
    con.commit()


def load_visits(con):
    return [{"code": c, "start": datetime.fromisoformat(s), "end": datetime.fromisoformat(e),
             "title": t, "origin": o} for c, s, e, t, o in con.execute("select * from visits")]


def load_mic(con):
    now = datetime.now().astimezone()
    q = "select start, stop from mic where app in (%s)" % ",".join("?" * len(CALL_APPS))
    return [(datetime.fromisoformat(s), datetime.fromisoformat(e) if e else now)
            for s, e in con.execute(q, CALL_APPS)]


def categorize(title, cfg):
    if not title:
        return cfg["categoria_avulsa"]
    t = title.lower()
    for cat in cfg["categorias"]:
        if any(re.search(r, t) for r in cat["regras"]):
            return cat["nome"]
    return cfg["categoria_padrao"]


def match_calendar(sessions, events):
    """Liga cada call a um evento da agenda (mesmo link do Meet, horário próximo)."""
    by_code = {}
    for ev in events:
        if ev["code"]:
            by_code.setdefault(ev["code"], []).append(ev)
    for s in sessions:
        cands = [ev for ev in by_code.get(s["code"], [])
                 if ev["start"] - timedelta(minutes=30) < s["end"] and ev["end"] + timedelta(hours=1) > s["start"]]
        if not cands:
            s["scheduled"] = False
            continue
        ev = min(cands, key=lambda ev: abs(ev["start"] - s["start"]))
        ev["attended"] = True
        ev["session"] = s
        s.update(scheduled=True, title=ev["title"] or s["title"], recurring=ev["recurring"])
        # aba esquecida aberta: corta 30 min depois do fim previsto
        s["end"] = max(s["start"], min(s["end"], ev["end"] + timedelta(minutes=30)))
        s["minutes"] = round((s["end"] - s["start"]).total_seconds() / 60, 1)


def remove_overlaps(items):
    """Duas coisas ao mesmo tempo não contam em dobro: o trecho sobreposto fica com a primeira."""
    items.sort(key=lambda x: x["start"])
    frontier = None
    out = []
    for x in items:
        start = max(x["start"], frontier) if frontier else x["start"]
        if x["end"] > start:
            x["minutes"] = round((x["end"] - start).total_seconds() / 60, 1)
            out.append(x)
        frontier = max(frontier, x["end"]) if frontier else x["end"]
    return out


def ensure_drive(timeout=90):
    """A agenda e os relatórios passam pelo Google Drive para desktop: abre o app se não estiver montado."""
    import glob
    import subprocess
    import time
    if drive_dir():
        return True
    exes = sorted(glob.glob(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                         "Google", "Drive File Stream", "*", "GoogleDriveFS.exe")))
    if not exes:
        return False
    subprocess.Popen([exes[-1]])
    for _ in range(timeout // 3):
        time.sleep(3)
        if drive_dir():
            return True
    return False


def run(clockwork_mode="auto"):
    """clockwork_mode: 'auto' (execução de segunda), 'lancar', 'simular' ou None (não mexe no Jira)."""
    cfg = load_config()
    ensure_drive()
    con = db()
    sync_history(con, cfg["email"])
    visits = load_visits(con)
    sessions = build_sessions(visits, load_mic(con))
    first = min(v["start"] for v in visits)
    now = datetime.now().astimezone()

    events, cal_status = [], "sem agenda conectada"
    from calendar_ics import find_drive_json, load_events_json
    agenda_json = find_drive_json(cfg.get("agenda_json", ""))
    if agenda_json:
        try:
            events, exported = load_events_json(agenda_json, first, now, cfg["ignorar_eventos"])
            exported = datetime.fromisoformat(exported.replace("Z", "+00:00")).astimezone()
            cal_status = f"agenda conectada ({len(events)} eventos, exportada {exported:%d/%m %H:%M})"
        except Exception as e:
            cal_status = f"erro ao ler a agenda: {e}"
    elif cfg.get("ics_url"):
        from calendar_ics import fetch_events
        try:
            events = fetch_events(cfg["ics_url"], cfg["email"], first, now, cfg["ignorar_eventos"])
            cal_status = f"agenda conectada ({len(events)} eventos)"
        except Exception as e:  # agenda fora do ar não pode derrubar o relatório
            cal_status = f"erro ao ler a agenda: {e}"
    match_calendar(sessions, events)

    items = []
    for s in sessions:
        # sem agenda conectada: o Meet só mostra o nome da sala quando ela pertence a um evento
        if not events:
            s["scheduled"] = bool(s["title"])
        kind = "agendada" if s["scheduled"] else ("chat" if s["origin"] == "chat" else "avulsa")
        items.append({**s, "kind": kind})
    # bloco só meu (tarefa, lembrete, consulta): continua servindo para casar calls, mas não é reunião
    is_meeting = lambda ev: ev.get("guests") is None or ev["guests"] >= 2
    for ev in events:
        # eventos aceitos sem Meet (presenciais, telefone) também ocupam a agenda
        if not ev["code"] and ev["accepted"] and ev["end"] <= now and is_meeting(ev):
            items.append({"code": None, "title": ev["title"], "start": ev["start"], "end": ev["end"],
                          "recurring": ev["recurring"], "kind": "presencial"})
    # agendas em que estou sempre (muitas vezes na sala, sem Meet): contam pelo evento inteiro
    always = [a.lower() for a in cfg.get("sempre_presente", [])]
    for ev in events:
        if not any(a in ev["title"].lower() for a in always) or ev["end"] > now:
            continue
        ev["attended"] = True
        if ev.get("session"):
            s = ev["session"]
            s["start"], s["end"] = min(s["start"], ev["start"]), max(s["end"], ev["end"])
            s["minutes"] = round((s["end"] - s["start"]).total_seconds() / 60, 1)
        else:
            items.append({"code": ev["code"], "title": ev["title"], "start": ev["start"], "end": ev["end"],
                          "recurring": ev["recurring"], "kind": "presencial"})
    items = remove_overlaps(items)
    missed = [ev for ev in events
              if ev["code"] and ev["accepted"] and not ev.get("attended") and ev["end"] <= now and is_meeting(ev)]

    rows = [{
        "date": x["start"].strftime("%Y-%m-%d"),
        "week": x["start"].strftime("%G-W%V"),
        "start": x["start"].strftime("%H:%M"),
        "end": x["end"].strftime("%H:%M"),
        "min": x["minutes"],
        "title": x["title"] or f"Call sem nome ({x['code']})",
        "cat": categorize(x["title"], cfg),
        "kind": x["kind"],
        "rec": bool(x["recurring"]),
    } for x in items]
    data = {
        "generated": now.strftime("%d/%m/%Y %H:%M"),
        "sheet": sheet_name(cfg),
        "owner": cfg.get("nome", ""),
        "today": now.strftime("%Y-%m-%d"),
        "firstDay": first.strftime("%Y-%m-%d"),
        "hoursPerWeek": cfg["horas_semana"],
        "daysOff": cfg.get("dias_sem_expediente", []),
        "categories": [c["nome"] for c in cfg["categorias"]] + [cfg["categoria_avulsa"], cfg["categoria_padrao"]],
        "calendar": cal_status,
        "micDays": len({m[0].date() for m in load_mic(con)}),
        "rows": rows,
        "missed": [{"date": ev["start"].strftime("%Y-%m-%d"), "week": ev["start"].strftime("%G-W%V"),
                    "start": ev["start"].strftime("%H:%M"), "end": ev["end"].strftime("%H:%M"),
                    "min": round((ev["end"] - ev["start"]).total_seconds() / 60, 1),
                    "title": ev["title"], "rec": bool(ev["recurring"]), "cat": categorize(ev["title"], cfg)}
                   for ev in missed],
    }
    with open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8") as f:
        html = f.read().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    out = os.path.join(HERE, "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    export_sheet(data, cfg)
    make_reports(data, cfg, now)
    if clockwork_mode:
        sync_clockwork(data, cfg, clockwork_mode)
    return out


def sync_clockwork(data, cfg, mode):
    """Erro no Jira (sem rede, token vencido) não pode derrubar o dashboard nem os relatórios."""
    import clockwork
    if mode == "auto" and not os.path.exists(clockwork.CONFIG):
        return  # automação ainda não configurada
    try:
        clockwork.sync(json.loads(json.dumps(data)), cfg["email"], simulate=mode == "simular")
    except Exception as e:
        msg = f"{datetime.now():%Y-%m-%d %H:%M} Clockwork: {e}"
        print(msg)
        with open(os.path.join(HERE, "clockwork_erros.log"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
        if mode != "auto":
            raise SystemExit(1)


def drive_dir():
    return next((p for l in "GHIJKLMNOPQRSTUVWXYZ" for d in ("Meu Drive", "My Drive")
                 if os.path.isdir(p := os.path.join(l + ":" + os.sep, d))), None)


def reports_dir(cfg):
    base = drive_dir() or HERE
    return os.path.join(base, cfg.get("pasta_relatorios", "Gestão do tempo - relatórios"))


def make_reports(data, cfg, now, force=None):
    """Gera os relatórios fechados que estão vencidos e ainda não existem (nunca sobrescreve)."""
    from datetime import date
    import report
    folder = reports_dir(cfg)
    since = date.fromisoformat(cfg.get("relatorios_a_partir_de", "2000-01-01"))
    first = date.fromisoformat(data["firstDay"])
    due = force or [(k, a, b) for k, a, b in report.due_reports(now.date()) if a >= first - timedelta(days=6)]
    for kind, a, b in due:
        if b < since and not force:  # período que termina antes do início combinado
            continue
        path = os.path.join(folder, report.report_name(kind, a, b))
        if os.path.exists(path) and not force:
            continue
        try:
            report.build_report(json.loads(json.dumps(data)), kind, a, b, path)
            print("Relatório:", path)
        except PermissionError:
            pass


def sheet_name(cfg):
    first = cfg.get("nome", "").split(" ")[0]
    return cfg.get("planilha_nome") or f"Gestão do tempo{' - ' + first if first else ''} (automático).xlsx"


def export_sheet(data, cfg):
    """Planilha para o gestor: local e, se houver, no Google Drive (compartilhe o arquivo uma vez)."""
    from export_xlsx import build
    name = sheet_name(cfg)
    targets = [os.path.join(HERE, name)]
    drive = drive_dir()
    if drive:
        targets.append(os.path.join(drive, name))
    for path in targets:
        try:
            build(json.loads(json.dumps(data)), path, cfg.get("semanas_resumo", 4))
        except PermissionError:  # arquivo aberto no Excel: tenta de novo na próxima rodada
            pass


if __name__ == "__main__":
    if sys.argv[1:] == ["mic"]:
        log_mic()
    elif sys.argv[1:2] == ["relatorio"]:
        # python tracker.py relatorio semanal|mensal [AAAA-MM-DD]  -> (re)gera o período daquela data
        import report
        from datetime import date
        kind = sys.argv[2]
        day = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date.today()
        a, b = (report.week_bounds if kind == "semanal" else report.month_bounds)(day)
        run.__globals__["make_reports"] = lambda data, cfg, now: make_reports(data, cfg, now, force=[(kind, a, b)])
        run(clockwork_mode=None)
    elif sys.argv[1:2] == ["clockwork"]:
        if sys.argv[2:] == ["token"]:
            import clockwork
            clockwork.save_token(clockwork.load_config().get("email") or load_config()["email"])
        else:
            run(clockwork_mode="simular" if "--simular" in sys.argv else "lancar")
    else:
        path = run()
        print("Dashboard:", path)
        if "--open" in sys.argv:
            webbrowser.open(path)
