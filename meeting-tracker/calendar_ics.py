"""Eventos do Google Agenda via endereço secreto iCal (sem precisar de projeto no Google Cloud)."""
import re
import urllib.request
from datetime import datetime

import icalendar
import recurring_ical_events

CODE_RE = re.compile(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})")


def fetch_events(ics_url, email, start, end, ignore_words):
    with urllib.request.urlopen(ics_url, timeout=60) as r:
        cal = icalendar.Calendar.from_ical(r.read())
    email = email.lower()
    events = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        s, e = ev.get("DTSTART").dt, ev.get("DTEND").dt if ev.get("DTEND") else None
        if not isinstance(s, datetime) or e is None:  # dia inteiro
            continue
        if str(ev.get("TRANSP", "")).upper() == "TRANSPARENT":  # marcado como "disponível"
            continue
        title = str(ev.get("SUMMARY", "")).strip()
        if any(w in title.lower() for w in ignore_words):
            continue
        status = _my_status(ev, email)
        if status == "DECLINED":
            continue
        text = " ".join(str(ev.get(k, "")) for k in ("X-GOOGLE-CONFERENCE", "LOCATION", "DESCRIPTION"))
        m = CODE_RE.search(text)
        events.append({
            "title": title,
            "start": s.astimezone(),
            "end": e.astimezone(),
            "code": m.group(1) if m else None,
            "recurring": bool(ev.get("RRULE") or ev.get("RECURRENCE-ID")),
            "accepted": status in ("ACCEPTED", None),  # None = eu sou a organizadora
        })
    return events


def _my_status(ev, email):
    attendees = ev.get("ATTENDEE") or []
    if not isinstance(attendees, list):
        attendees = [attendees]
    for a in attendees:
        if str(a).lower().removeprefix("mailto:") == email:
            return str(a.params.get("PARTSTAT", "")).upper() or None
    return None


# --- Alternativa quando o admin bloqueia o iCal: JSON exportado pelo agenda_export.gs no Drive ---
JSON_NAME = "meeting-tracker-agenda.json"


def find_drive_json(path=""):
    """Procura o arquivo na pasta do Google Drive para desktop (ex.: G:/Meu Drive)."""
    import os
    import string
    if path:
        return path if os.path.exists(path) else None
    for letter in string.ascii_uppercase:
        for folder in ("Meu Drive", "My Drive"):
            p = os.path.join(f"{letter}:\\", folder, JSON_NAME)
            if os.path.exists(p):
                return p
    return None


def load_events_json(path, start, end, ignore_words):
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    events = []
    for e in data["events"]:
        s, en = datetime.fromisoformat(e["start"]).astimezone(), datetime.fromisoformat(e["end"]).astimezone()
        if en < start or s > end or e["free"] or e["status"] == "declined":
            continue
        if any(w in e["title"].lower() for w in ignore_words):
            continue
        events.append({"title": e["title"].strip(), "start": s, "end": en, "code": e["code"],
                       "recurring": e["recurring"], "accepted": e["status"] == "accepted",
                       "guests": e.get("guests")})
    return events, data["exported"]
