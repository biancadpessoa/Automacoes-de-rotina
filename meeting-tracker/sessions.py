"""Junta visitas do Meet em sessões reais de call."""
from collections import defaultdict
from datetime import timedelta

MERGE_GAP = timedelta(minutes=10)   # reconexões/recarregamentos dentro desse intervalo = mesma call
MIN_CALL = timedelta(minutes=2)     # abaixo disso é só abrir/fechar a sala
MAX_CALL = timedelta(hours=4)       # aba esquecida aberta não vira reunião de 10h


def build_sessions(visits, mic_sessions=()):
    by_code = defaultdict(list)
    for v in visits:
        by_code[v["code"]].append(v)

    # nome mais informativo de cada sala (o Meet só mostra o nome do evento para salas da agenda)
    titles = {}
    for code, vs in by_code.items():
        named = [v["title"] for v in vs if v["title"] not in ("", "Meet", code)]
        titles[code] = max(set(named), key=named.count) if named else None

    sessions = []
    for code, vs in by_code.items():
        vs.sort(key=lambda v: v["start"])
        cur = None
        for v in vs:
            if cur and v["start"] <= cur["end"] + MERGE_GAP:
                cur["end"] = max(cur["end"], v["end"])
                cur["origin"] = cur["origin"] or v["origin"]
            else:
                cur = {"code": code, "start": v["start"], "end": v["end"], "origin": v["origin"]}
                sessions.append(cur)

    result = []
    for s in sessions:
        s["end"] = _trim_with_mic(s, mic_sessions)
        dur = min(s["end"] - s["start"], MAX_CALL)
        if dur < MIN_CALL:
            continue
        s["end"] = s["start"] + dur
        s["minutes"] = round(dur.total_seconds() / 60, 1)
        s["title"] = titles[s["code"]]
        result.append(s)

    # sala usada em 2+ semanas diferentes = reunião recorrente (link fixo do evento recorrente)
    weeks = defaultdict(set)
    for s in result:
        weeks[s["code"]].add(s["start"].isocalendar()[:2])
    for s in result:
        s["recurring"] = len(weeks[s["code"]]) >= 2
    result.sort(key=lambda s: s["start"])
    return result


def _trim_with_mic(s, mic_sessions):
    """Se há registro de microfone cobrindo a call, a call acaba quando o microfone foi liberado
    (corrige aba que ficou aberta na tela 'Você saiu da reunião')."""
    overlapping = [m for m in mic_sessions if m[0] < s["end"] and (m[1] or s["end"]) > s["start"]]
    if not overlapping:
        return s["end"]
    last_stop = max((m[1] or s["end"]) for m in overlapping)
    return min(s["end"], last_stop + timedelta(minutes=1))
