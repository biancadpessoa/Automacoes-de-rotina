"""Preenche o Clockwork (worklogs do Jira) com as horas de cada dia, por iniciativa.

    python tracker.py clockwork            -> lança os dias úteis pendentes até ontem
    python tracker.py clockwork --simular  -> só mostra o que seria lançado, sem gravar nada
    python tracker.py clockwork token      -> grava (ou troca) o token da API do Jira

Regra de cada dia (horas_dia; 8.8 = "1d" do Jira):
  1. Reuniões de rotina (dailies, weeklies, 1:1s...) vão para a iniciativa de rotinas pelo tempo real.
  2. O restante do dia é dividido entre as iniciativas na proporção dos minutos de reunião
     de cada uma NA SEMANA (os temas da semana, não só os do dia: uma reunião de 30 min não
     decide sozinha o dia inteiro). Reuniões sem tema ("Outros") não pesam: o tempo delas entra
     no restante e segue a mesma proporção.
  3. Iniciativas com "peso_fixo" (ex.: 0.3) levam essa fração do foco toda semana, antes da proporção.
  4. Semana sem nenhuma reunião de iniciativa usa "sem_tema".
Cada dia é completado até horas_dia: o que você já lançou à mão fica como está e só a diferença
é lançada (nada é duplicado nem sobrescrito). Dia sem reunião usa os temas das suas conversas no
Claude (títulos do histórico do Chrome); sem elas, a proporção da semana. Esses dias aparecem na saída.
"""
import base64
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "clockwork.json")
LOG = os.path.join(HERE, "clockwork_lancamentos.csv")
KEYRING_SERVICE = "meeting-tracker-jira"
TAG = "Automático (meeting-tracker)"
ROTINAS, OUTROS = "rotinas", "outros"
KNOWN_CLOUDS = {"https://madeiramadeira.atlassian.net": "c52b487a-f294-4cb9-a67e-3b8983ddfeab"}


def load_config():
    path = CONFIG if os.path.exists(CONFIG) else os.path.join(HERE, "clockwork.example.json")
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


# --- classificação e divisão do dia ---------------------------------------------------------

def bucket(title, cw):
    """Iniciativa específica primeiro (o tema vence o ritual: 'Refinamento - Bot' é do bot)."""
    t = (title or "").lower()
    if t.startswith("call sem nome"):
        return OUTROS
    for ini in cw["iniciativas"]:
        if any(re.search(r, t) for r in ini["regras"]):
            return ini["issue"]
    if any(re.search(r, t) for r in cw["rotinas"]["regras"]):
        return ROTINAS
    return OUTROS


def _round(alloc, total, step):
    """Arredonda para múltiplos de `step` mantendo a soma exata (maior resto)."""
    units = total // step
    raw = {k: v / step for k, v in alloc.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:units - sum(out.values())]:
        out[k] += 1
    out = {k: v * step for k, v in out.items() if v}
    # jornada que não é múltipla de step (8,8h = 528 min): a sobra vai para a maior fatia
    if out and total - sum(out.values()):
        out[max(out, key=out.get)] += total - sum(out.values())
    return out


def split_day(day_min, week_min, cw, total=None):
    """day_min/week_min: {bucket: minutos}. Devolve {issue: minutos} somando `total` (padrão horas_dia)."""
    total = total or int(cw.get("horas_dia", 8) * 60)
    step = int(cw.get("fracao_minutos", 15))
    rot = min(day_min.get(ROTINAS, 0), total)
    rest = total - rot
    alloc = defaultdict(float)
    if rot:
        alloc[cw["rotinas"]["issue"]] += rot
    # iniciativas com peso_fixo levam essa fração do foco toda semana, com ou sem reunião
    fixed = {i["issue"]: i["peso_fixo"] for i in cw["iniciativas"] if i.get("peso_fixo")}
    for k, p in fixed.items():
        alloc[k] += rest * p
    rest -= rest * min(sum(fixed.values()), 1)
    weights = {k: v for k, v in week_min.items() if k not in (ROTINAS, OUTROS) and v > 0}
    if not weights:
        weights = {cw["sem_tema"]: 1}
    wsum = sum(weights.values())
    for k, v in weights.items():
        alloc[k] += rest * v / wsum
    out = _round(alloc, total, step)
    # fatias pequenas demais viram ruído no Clockwork: vão para a maior iniciativa do dia
    small = [k for k, v in out.items() if v < cw.get("minimo_minutos", 30)]
    themes = [k for k in out if k not in small and k != cw["rotinas"]["issue"]]
    if len(small) < len(out):
        top = max(themes or [k for k in out if k not in small], key=out.get)
        for k in small:
            out[top] += out.pop(k)
    return out


def plan(data, cw, done_days, today=None, warnings=None):
    """Dias úteis pendentes -> lista de lançamentos {date, issue, min, comment}.
    done_days: {data: minutos já lançados}. Cada dia é completado até horas_dia (o que já foi
    lançado à mão fica como está). Dia sem reunião medida usa os temas das conversas no Claude
    daquele dia; sem elas, a proporção da semana (e entra em `warnings` para conferir)."""
    today = today or date.fromisoformat(data["today"])
    first = max(date.fromisoformat(data["firstDay"]), date.fromisoformat(cw["lancar_a_partir_de"]))
    off = set(data["daysOff"])
    full = int(cw.get("horas_dia", 8) * 60)
    step = int(cw.get("fracao_minutos", 15))
    by_day, by_week, titles = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float)), defaultdict(list)
    for r in data["rows"]:
        b = bucket(r["title"], cw)
        by_day[r["date"]][b] += r["min"]
        by_week[r["week"]][b] += r["min"]
        titles[(r["date"], b)].append(r["title"])
    claude, claude_titles = defaultdict(lambda: defaultdict(float)), defaultdict(list)
    for c in data.get("claude", []):
        b = bucket(c["title"], cw)
        if b not in (ROTINAS, OUTROS):
            claude[c["date"]][b] += max(c["min"], 1)
            claude_titles[(c["date"], b)].append(c["title"])
    names = {i["issue"]: i["nome"] for i in cw["iniciativas"]}
    names[cw["rotinas"]["issue"]] = "Rotinas"
    entries = []
    d = first
    while d < today:
        ds = d.isoformat()
        missing = full - int(done_days.get(ds, 0))
        if d.weekday() < 5 and ds not in off and missing >= step:
            week = d.strftime("%G-W%V")
            weights, source = by_week[week], "foco, proporcional aos temas da semana"
            if not by_day.get(ds):
                if not cw.get("completar_dias_sem_reuniao", True):
                    if warnings is not None:
                        warnings.append(f"{ds}: sem reuniões, não lançado")
                    d += timedelta(days=1)
                    continue
                if claude.get(ds):
                    weights, source = claude[ds], None
                elif warnings is not None:
                    warnings.append(f"{ds}: sem reuniões nem conversas no Claude medidas - usei a proporção da semana")
            if ds in done_days and warnings is not None:
                warnings.append(f"{ds}: já tinha {_fmt(done_days[ds])} lançado à mão - completei {_fmt(missing)}")
            for issue, m in split_day(by_day[ds], weights, cw, missing).items():
                b = ROTINAS if issue == cw["rotinas"]["issue"] else issue
                met, chats = titles.get((ds, b), []), claude_titles.get((ds, issue), [])
                if met:
                    uniq = list(dict.fromkeys(met))
                    why = f"{len(met)} {'reunião' if len(met) == 1 else 'reuniões'}: " + ", ".join(uniq[:3]) + ("…" if len(uniq) > 3 else "")
                elif chats and source is None:
                    uniq = list(dict.fromkeys(chats))
                    why = "análises no Claude: " + ", ".join(uniq[:3]) + ("…" if len(uniq) > 3 else "")
                else:
                    why = source or "foco, proporcional às análises do dia no Claude"
                entries.append({"date": ds, "issue": issue, "nome": names.get(issue, issue), "min": m,
                                "comment": f"{TAG} - {why}"})
        d += timedelta(days=1)
    return entries


# --- Jira -----------------------------------------------------------------------------------

def get_token(email):
    if os.environ.get("JIRA_API_TOKEN"):
        return os.environ["JIRA_API_TOKEN"]
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, email)
    except Exception:
        return None


def save_token(email):
    """Pede o token, testa no Jira e só então guarda (token errado não fica salvo)."""
    import getpass
    import keyring
    print("Crie o token em https://id.atlassian.com/manage-profile/security/api-tokens")
    print("  Use o botão 'Criar token da API' (o SEM escopos), nome 'meeting-tracker', validade máxima > Copiar.")
    print("  Cole abaixo com o botão direito do mouse ou Ctrl+V e aperte Enter. Nada aparece enquanto você cola.")
    for tentativa in range(3):
        token = "".join(getpass.getpass("Token da API do Jira: ").split())  # tira espaços e quebras de linha
        if len(token) < 20:
            print(f"  Recebi {len(token)} caracteres; é curto demais para um token (os atuais têm cerca de 190). Copie de novo e cole.")
            continue
        try:
            jira = Jira(load_config()["site"], email, token)
            me = jira.get("/rest/api/3/myself")
        except RuntimeError as e:
            print(f"  O Jira recusou o token ({e}).")
            print(f"  Confira se o token foi criado na conta {email} e cole de novo.")
            continue
        keyring.set_password(KEYRING_SERVICE, email, token)
        print(f"Token salvo no Gerenciador de Credenciais do Windows. Conectado como {me['displayName']}.")
        return
    raise SystemExit("Não consegui validar o token. Rode de novo: python tracker.py clockwork token")


class Jira:
    """Token clássico funciona no endereço do site; token "com escopos" só no gateway
    api.atlassian.com/ex/jira/<cloudId>. Tenta o site e, se recusar o login, troca para o gateway."""
    GATEWAY = "https://api.atlassian.com/ex/jira/"

    def __init__(self, site, email, token):
        self.site = site.rstrip("/")
        self.base = None
        self.auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()

    def _request(self, base, method, path, body=None):
        req = urllib.request.Request(base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": self.auth, "Accept": "application/json",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")

    def _connect(self):
        try:
            self._request(self.site, "GET", "/rest/api/3/myself")
            self.base = self.site
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403):
                raise RuntimeError(f"Jira GET /rest/api/3/myself: HTTP {e.code} {e.read()[:300]!r}") from None
            cloud = load_config().get("cloud_id") or KNOWN_CLOUDS.get(self.site)
            if not cloud:
                with urllib.request.urlopen(self.site + "/_edge/tenant_info", timeout=30) as r:  # público
                    cloud = json.loads(r.read())["cloudId"]
            gw = self.GATEWAY + cloud
            try:
                self._request(gw, "GET", "/rest/api/3/myself")
            except urllib.error.HTTPError as e2:
                raise RuntimeError(f"Jira recusou o login (HTTP {e2.code}): token errado, vencido, de outra "
                                   "conta ou sem os escopos read:jira-work, write:jira-work e read:jira-user") from None
            self.base = gw

    def _call(self, method, path, body=None):
        if self.base is None:
            self._connect()
        try:
            return self._request(self.base, method, path, body)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Jira {method} {path}: HTTP {e.code} {e.read()[:300]!r}") from None

    def get(self, path):
        return self._call("GET", path)

    def post(self, path, body):
        return self._call("POST", path, body)

    def logged_days(self, a, b):
        """{AAAA-MM-DD: minutos} que eu já lancei entre a e b, somando todas as issues."""
        me = self.get("/rest/api/3/myself")["accountId"]
        jql = f'worklogAuthor = currentUser() AND worklogDate >= "{a}" AND worklogDate <= "{b}"'
        keys, token = [], None
        while True:
            body = {"jql": jql, "fields": ["key"], "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            r = self.post("/rest/api/3/search/jql", body)
            keys += [i["key"] for i in r.get("issues", [])]
            token = r.get("nextPageToken")
            if not token:
                break
        after = int(datetime.combine(a, datetime.min.time()).astimezone().timestamp() * 1000)
        days = defaultdict(float)
        for k in keys:
            start = 0
            while True:
                r = self.get(f"/rest/api/3/issue/{k}/worklog?startedAfter={after}&startAt={start}&maxResults=1000")
                for w in r.get("worklogs", []):
                    if w["author"]["accountId"] == me:
                        days[_parse(w["started"]).date().isoformat()] += w["timeSpentSeconds"] / 60
                start += len(r.get("worklogs", []))
                if not r.get("worklogs") or start >= r.get("total", 0):
                    break
        return dict(days)

    def add_worklog(self, issue, started, minutes, comment):
        body = {"started": started.strftime("%Y-%m-%dT%H:%M:%S.000%z"), "timeSpentSeconds": int(minutes * 60),
                "comment": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": comment[:900]}]}]}}
        return self.post(f"/rest/api/3/issue/{urllib.parse.quote(issue)}/worklog?notifyUsers=false", body)


def _parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone()


# --- execução -------------------------------------------------------------------------------

def _fmt(m):
    return f"{int(m // 60)}h{int(m % 60):02d}"


def show(entries):
    if not entries:
        print("Clockwork: nenhum dia pendente.")
        return
    print(f"{'Data':<11} {'Issue':<15} {'Horas':>6}  Motivo")
    for e in entries:
        print(f"{e['date']:<11} {e['issue']:<15} {_fmt(e['min']):>6}  {e['comment'][len(TAG) + 3:][:90]}")
    tot = defaultdict(float)
    for e in entries:
        tot[(e["issue"], e["nome"])] += e["min"]
    print("\nTotal por iniciativa:")
    for (k, n), m in sorted(tot.items(), key=lambda x: -x[1]):
        print(f"  {k:<15} {_fmt(m):>7}  {n}")


def sync(data, email, simulate=False):
    cw = load_config()
    if not cw.get("ativo", True) and not simulate:
        return []
    email = cw.get("email") or email
    token = get_token(email)
    today = date.fromisoformat(data["today"])
    a = max(date.fromisoformat(data["firstDay"]), date.fromisoformat(cw["lancar_a_partir_de"]))
    if not token:
        if not simulate:
            raise RuntimeError("token da API do Jira não configurado (rode: python tracker.py clockwork token)")
        print("Sem token do Jira: simulando sem conferir os dias já lançados.\n")
        jira, done = None, {}
    else:
        jira = Jira(cw["site"], email, token)
        done = jira.logged_days(a, today - timedelta(days=1)) if a < today else {}
    warnings = []
    entries = plan(data, cw, done, today, warnings)
    if warnings:
        print("Confira estes dias:")
        for w_ in warnings:
            print("  " + w_)
        print()
    if simulate:
        show(entries)
        return entries
    h, m = map(int, cw.get("inicio_do_dia", "09:00").split(":"))
    clock = {}
    new_file = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if new_file:
            w.writerow(["lancado_em", "data", "issue", "minutos", "worklog_id", "comentario"])
        for e in entries:
            d = date.fromisoformat(e["date"])
            started = clock.get(e["date"]) or datetime(d.year, d.month, d.day, h, m).astimezone()
            r = jira.add_worklog(e["issue"], started, e["min"], e["comment"])
            clock[e["date"]] = started + timedelta(minutes=e["min"])  # lançamentos do dia em sequência
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), e["date"], e["issue"], e["min"],
                        r.get("id", ""), e["comment"]])
    if entries:
        print(f"Clockwork: {len(entries)} lançamentos em {len({e['date'] for e in entries})} dias.")
    return entries


if __name__ == "__main__":
    if sys.argv[1:] == ["token"]:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8-sig") as f:
            save_token(load_config().get("email") or json.load(f)["email"])
