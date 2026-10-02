"""Fontes de dados: histórico do Chrome (Meet) e uso do microfone no Windows."""
import json
import os
import re
import shutil
import sqlite3
import tempfile
import winreg
from datetime import datetime, timedelta, timezone

CHROME_DIR = os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data")
MEET_RE = re.compile(r"https://meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})")
MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"

# Parâmetro hs= que o Google adiciona à URL do Meet conforme a origem do clique
HS_ORIGIN = {"122": "agenda", "146": "chat"}


def _chrome_ts(us):
    """Timestamp do Chrome (µs desde 1601) -> datetime local."""
    return (datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=us)).astimezone()


def find_profile(email):
    for name in os.listdir(CHROME_DIR):
        prefs = os.path.join(CHROME_DIR, name, "Preferences")
        if not os.path.exists(prefs):
            continue
        try:
            with open(prefs, encoding="utf-8") as f:
                accounts = json.load(f).get("account_info") or []
        except (OSError, ValueError):
            continue
        if any(a.get("email", "").lower() == email.lower() for a in accounts):
            return os.path.join(CHROME_DIR, name)
    raise SystemExit(f"Perfil do Chrome com a conta {email} não encontrado.")


def meet_visits(profile_dir):
    """Cada visita a uma sala do Meet: código, início, fim, título e origem do link."""
    tmp = os.path.join(tempfile.gettempdir(), "meet_tracker_history")
    shutil.copy2(os.path.join(profile_dir, "History"), tmp)  # original fica travado pelo Chrome
    con = sqlite3.connect(tmp)
    rows = con.execute(
        """select v.visit_time, v.visit_duration, u.url, u.title
           from visits v join urls u on u.id = v.url
           where u.url like 'https://meet.google.com/___-____-___%'
           order by v.visit_time"""
    ).fetchall()
    con.close()
    visits = []
    for vt, dur, url, title in rows:
        m = MEET_RE.match(url)
        if not m:
            continue
        hs = re.search(r"[?&]hs=(\d+)", url)
        start = _chrome_ts(vt)
        visits.append({
            "code": m.group(1),
            "start": start,
            "end": start + timedelta(microseconds=dur or 0),
            "title": re.sub(r"^Meet\s*[:–-]\s*", "", (title or "").strip()),
            "origin": HS_ORIGIN.get(hs.group(1)) if hs else None,
        })
    return visits


def read_mic_usage():
    """Última sessão de microfone registrada pelo Windows para cada app (start, stop|None)."""
    out = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIC_KEY) as key:
        i = 0
        while True:
            try:
                app = winreg.EnumKey(key, i)
            except OSError:
                break
            i += 1
            with winreg.OpenKey(key, app) as sub:
                try:
                    start = winreg.QueryValueEx(sub, "LastUsedTimeStart")[0]
                    stop = winreg.QueryValueEx(sub, "LastUsedTimeStop")[0]
                except OSError:
                    continue
            exe = app.split("#")[-1].lower()
            to_dt = lambda ft: _chrome_ts(ft // 10)  # FILETIME = 100ns desde 1601
            out[exe] = (to_dt(start), to_dt(stop) if stop > start else None)
    return out
