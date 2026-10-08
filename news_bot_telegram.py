"""
Bot Telegram de veille personnalisée - David Abergel

- Alerte quotidienne : tous les jours à 07:00 (heure de Genève)
    Immobilier Genève · Autorisations de construire (tes communes) · Monde · Israël / Moyen-Orient
- Update hebdo : le lundi à 07:15 (heure de Genève)
    Chiffres clés · Économie Suisse & Europe · Politique France/Israël/US · Géopolitique · IA
    + Perspectives : impact dans les années à venir
- Alerte urgence : vérification toutes les 30 min, message uniquement si événement majeur
- Questions : écris-lui n'importe quoi (ou réponds à une news) et il te répond

Commandes : /alerte · /hebdo · /fao · /chiffres · /aide
"""

import os, re, json, time, logging, threading, requests, feedparser, schedule
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import anthropic

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = str(os.environ["CHAT_ID"])
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
FAST_MODEL = os.environ.get("CLAUDE_FAST_MODEL", "claude-haiku-4-5-20251001")
TZ_NAME = "Europe/Zurich"
TZ = ZoneInfo(TZ_NAME)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

# Communes surveillées pour les autorisations de construire (modifiable via la variable COMMUNES sur Railway)
COMMUNES = [c.strip() for c in os.environ.get(
    "COMMUNES",
    "Collonge-Bellerive,Corsier,Anières,Hermance,Cologny,Vandoeuvres,Chêne-Bougeries,Meinier,Choulex",
).split(",") if c.strip()]


# ---------------------------------------------------------------------------
# Sources : recherches Google News
# ---------------------------------------------------------------------------

def gnews(query, period="1d", lang="fr", country="CH"):
    """Flux RSS Google News pour une recherche (period : 1h, 1d, 7d...)."""
    q = quote_plus(f"{query} when:{period}")
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={country}:{lang}"


def gnews_en(query, period="1d"):
    return gnews(query, period, lang="en", country="US")


# ---- ALERTE QUOTIDIENNE (07:00) ------------------------------------------

DAILY = {
    "🏠 Immobilier Genève": {
        "feeds": [
            gnews("immobilier Genève"),
            gnews("site:tdg.ch immobilier OR logement OR construction"),
            gnews("site:fao.ge.ch OR \"feuille d'avis officielle\" Genève immobilier"),
            gnews("taux hypothécaires BNS OR \"taux directeur\" OR \"taux de référence\""),
            gnews("Genève (loi OR LDTR OR \"Grand Conseil\") logement OR immobilier OR zone"),
            gnews("site:immobilier.ch OR site:bilan.ch OR site:letemps.ch OR site:agefi.com immobilier"),
            gnews("Genève villa OR propriété OR transaction vendue millions"),
        ],
        "max_articles": 25,
        "instructions": """Tu fais la veille d'un promoteur-investisseur immobilier basé à Genève.
Garde UNIQUEMENT ce qui est pertinent pour le marché immobilier genevois (luxe ou non) :
- nouvelles lois, votations, règlements, décisions du Grand Conseil / Conseil d'État, LDTR, zones, autorisations
- BNS, taux hypothécaires, taux de référence, financement, fiscalité immobilière
- ventes ou transactions phares, gros projets, promotions, chiffres de marché (prix, vacance)
- publications FAO notables (autorisations de construire importantes, ventes aux enchères)
Ignore le reste. Pour chaque point : 1-2 lignes, factuel, avec chiffres si dispo, et pourquoi ça compte pour un promoteur.""",
    },
    "🌍 Monde : événements majeurs": {
        "feeds": [
            gnews("attentat OR attaque OR explosion", lang="fr", country="FR"),
            gnews("séisme OR tsunami OR ouragan OR catastrophe", lang="fr", country="FR"),
            gnews("breaking news world", lang="en", country="US"),
            gnews_en("site:reuters.com OR site:apnews.com world"),
            gnews("crise OR krach OR sanctions OR embargo économie mondiale", lang="fr", country="FR"),
            gnews("actualité internationale", lang="fr", country="FR"),
        ],
        "max_articles": 30,
        "instructions": """Sélectionne UNIQUEMENT les 3 à 6 événements des dernières 24h les plus impactants
dans le monde : attentats ou tentatives d'attentat, catastrophes naturelles, crises politiques majeures,
chocs économiques ou financiers, décisions qui font bouger les marchés, faits de société d'ampleur.
Ignore les faits divers locaux et l'actualité secondaire. Classe par importance.
Pour chaque événement : ce qui s'est passé + l'impact (économique, financier, politique ou social).
S'il n'y a rien de vraiment majeur, dis-le en une ligne plutôt que de remplir.""",
    },
    "🇮🇱 Israël / Moyen-Orient": {
        "feeds": [
            gnews("Israël", lang="fr", country="FR"),
            gnews("Iran guerre OR frappes OR nucléaire", lang="fr", country="FR"),
            gnews_en("Israel Iran United States"),
            gnews_en("site:timesofisrael.com OR site:jpost.com OR site:ynetnews.com"),
            gnews_en("Israel economy OR shekel OR \"Tel Aviv Stock Exchange\" OR TASE"),
            gnews_en("Israel tech startup OR funding OR exit OR acquisition"),
            gnews_en("Israel real estate OR housing prices"),
            gnews("Liban OR Hezbollah OR Gaza OR Hamas OR Houthis", lang="fr", country="FR"),
        ],
        "max_articles": 30,
        "instructions": """Fais un point de situation Israël / Moyen-Orient en 3 blocs courts :
1. *Sécurité & guerre* : Iran, Gaza, Liban, Houthis, rôle des États-Unis, diplomatie
2. *Économie & marchés* : shekel, bourse de Tel-Aviv, notation, tech israélienne (levées, rachats), immobilier en Israël
3. *À surveiller* : ce qui peut bouger dans les prochains jours
Saute un bloc s'il n'y a rien de neuf.""",
    },
}

# ---- UPDATE HEBDO (lundi 07:15) -----------------------------------------

WEEKLY = {
    "📊 Économie Suisse & Europe": {
        "feeds": [
            gnews("économie suisse OR BNS OR franc suisse OR inflation Suisse", "7d"),
            gnews("SECO OR conjoncture OR PIB Suisse", "7d"),
            gnews("BCE OR zone euro OR économie européenne", "7d", country="FR"),
            gnews_en("ECB OR eurozone economy OR European markets", "7d"),
        ],
        "max_articles": 25,
        "instructions": """Résume la semaine économique en Suisse puis en Europe : banques centrales (BNS, BCE),
inflation, croissance, franc/euro, marchés, entreprises ou secteurs marquants. Chiffres clés + ce que ça implique.""",
    },
    "🗳️ Politique France · Israël · États-Unis": {
        "feeds": [
            gnews("politique France gouvernement OR Assemblée", "7d", country="FR"),
            gnews("politique Israël Knesset OR Netanyahou OR élections", "7d", country="FR"),
            gnews_en("Israel politics Knesset OR coalition", "7d"),
            gnews_en("US politics White House OR Congress OR Trump", "7d"),
        ],
        "max_articles": 30,
        "instructions": """Fais un point politique de la semaine, un sous-bloc par pays : *France*, *Israël*, *États-Unis*.
Pour chacun : 2-4 faits marquants et leurs conséquences possibles.""",
    },
    "🌐 Géopolitique mondiale": {
        "feeds": [
            gnews("géopolitique OR diplomatie OR sommet international", "7d", country="FR"),
            gnews("Ukraine Russie guerre", "7d", country="FR"),
            gnews("pétrole OR OPEP OR prix de l'énergie", "7d", country="FR"),
            gnews_en("China Taiwan OR China US tensions OR tariffs", "7d"),
            gnews_en("geopolitics oil prices sanctions", "7d"),
        ],
        "max_articles": 30,
        "instructions": """Résume les grandes lignes géopolitiques de la semaine qui ont un impact mondial
(Ukraine/Russie, Chine/US, Moyen-Orient vu globalement, énergie et pétrole, sanctions, commerce).
Pour chaque sujet : la situation + l'effet concret (pétrole, marchés, inflation, chaînes d'approvisionnement).""",
    },
    "🤖 Avancées IA": {
        "feeds": [
            gnews("intelligence artificielle", "7d", country="FR"),
            gnews_en("AI model launch OR release OpenAI OR Anthropic OR Google OR Meta", "7d"),
            gnews_en("artificial intelligence regulation OR breakthrough", "7d"),
        ],
        "max_articles": 25,
        "instructions": """Résume les avancées IA de la semaine : nouveaux modèles et produits, annonces majeures
des grands acteurs, régulation, usages concrets notables (y compris immobilier/finance si pertinent).""",
    },
}


# ---- PERSPECTIVES (lundi, après l'update hebdo) ---------------------------

OUTLOOK_THEME = "🔮 Perspectives : impact dans les années à venir"
OUTLOOK_FEEDS = [
    gnews_en("Israel war cost OR budget OR deficit OR debt OR \"credit rating\"", "7d"),
    gnews("coût de la guerre Israël OR budget Israël OR notation Israël", "7d", country="FR"),
    gnews("immobilier Genève OR Suisse prix OR marché OR taux", "7d"),
    gnews("BNS OR BCE OR Fed taux perspectives", "7d", country="FR"),
    gnews_en("oil price outlook OR global economy outlook OR IMF forecast", "7d"),
]
OUTLOOK_INSTRUCTIONS = """Tu es l'analyste personnel d'un promoteur-investisseur immobilier basé à Genève,
qui suit aussi de près Israël, la géopolitique et les marchés.

À partir des résumés de la semaine et des articles ci-dessus, choisis les 3 à 5 faits les plus
structurants (ex. : le coût de la guerre pour Israël, une décision de banque centrale, un choc pétrolier...).

Pour chacun :
• *Le fait* : résumé en 1 ligne, avec le chiffre clé
• *Impact à venir* : ton analyse de ce que ça implique sur 1 à 5 ans (dette, impôts, croissance,
  monnaie, taux, marchés, immobilier...), avec si utile un scénario probable et un scénario de risque
• *Pour toi* : le lien concret avec l'immobilier genevois, les taux suisses ou ses investissements, s'il y en a un

Tu peux donner ton avis et raisonner au-delà des articles, mais distingue clairement les faits (issus des
articles) de ton analyse, qui reste une projection et non une certitude. Pas de conseil d'investissement."""


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

recent_sent = deque(maxlen=12)   # derniers contenus envoyés (contexte pour les questions)


def md_escape(text):
    """Échappe les caractères Markdown (v1) dans un texte venant de l'extérieur."""
    return re.sub(r"([_*`\[])", r"\\\1", text or "")


def split_text(text, limit=3900):
    parts, current = [], ""
    for para in text.split("\n"):
        while len(para) > limit:
            parts.append(para[:limit])
            para = para[limit:]
        if len(current) + len(para) + 1 > limit:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def _send_one(text, silent=False, reply_to=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True,
               "disable_notification": silent}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        r = requests.post(url, json={**payload, "parse_mode": "Markdown"}, timeout=20)
        if not r.ok:  # Markdown mal formé → on renvoie en texte brut
            log.warning(f"Envoi Markdown refusé : {r.text[:200]}")
            r = requests.post(url, json=payload, timeout=20)
            if not r.ok:
                log.error(f"Envoi refusé : {r.text[:200]}")
    except Exception as e:
        log.error(f"Erreur envoi: {e}")


def send_message(text, silent=False, reply_to=None, remember=True):
    for i, part in enumerate(split_text(text)):
        _send_one(part, silent=silent, reply_to=reply_to if i == 0 else None)
        time.sleep(0.5)
    if remember:
        recent_sent.append(text)


def send_typing():
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendChatAction",
                      json={"chat_id": CHAT_ID, "action": "typing"}, timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# News : récupération + résumé
# ---------------------------------------------------------------------------

def fetch_feed(url):
    try:
        r = requests.get(url, timeout=10, headers=UA)
        return feedparser.parse(r.content).entries[:6]
    except Exception as e:
        log.error(f"Erreur fetch {url}: {e}")
        return []


def fetch_articles(urls, max_articles):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_feed, urls))
    articles, seen = [], set()
    for entries in results:
        for entry in entries:
            title = entry.get("title", "").strip()
            key = title.lower()[:80]
            if not title or key in seen:
                continue
            seen.add(key)
            articles.append({
                "title": title,
                "summary": entry.get("summary", "")[:300],
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
            })
    return articles[:max_articles]


def ask_claude(prompt, max_tokens=900, model=None, system=None, messages=None):
    kwargs = {"model": model or MODEL, "max_tokens": max_tokens,
              "messages": messages or [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    return msg.content[0].text


def summarize(theme, config, articles, period_label):
    if not articles:
        return "_Rien de notable sur cette période._"
    articles_text = "\n".join(
        f"- {a['title']} ({a['published'][:16]})\n  {a['summary']}\n  {a['link']}" for a in articles
    )
    prompt = f"""Thème : {theme}
Période : {period_label}

Articles récents :
{articles_text}

{config['instructions']}

Règles de forme :
- Français, style télégraphique, direct, neutre
- Pas d'introduction ni de conclusion
- Format Markdown Telegram simple : *gras*, _italique_, puces "•"
- N'invente rien qui ne soit pas dans les articles
- 15 lignes maximum"""
    try:
        return ask_claude(prompt)
    except Exception as e:
        log.error(f"Erreur Claude ({theme}): {e}")
        return "_Résumé indisponible (erreur technique)._"


def build_section(item, period_label):
    theme, config = item
    log.info(f"Traitement : {theme}")
    articles = fetch_articles(config["feeds"], config["max_articles"])
    return f"*{theme}*\n\n{summarize(theme, config, articles, period_label)}"


# ---------------------------------------------------------------------------
# Autorisations de construire (registre officiel du canton, données ouvertes SITG)
# Mêmes dossiers que ceux publiés dans la FAO, mis à jour chaque jour.
# ---------------------------------------------------------------------------

SITG = "https://vector.sitg.ge.ch/arcgis/rest/services"
TYPE_LABELS = {
    "DD": ("🏗️", "Demande définitive"),
    "DP": ("📐", "Demande préalable"),
    "M": ("🧨", "Démolition"),
    "MPA": ("🧨", "Démolition (proc. accélérée)"),
    "APA": ("🔧", "Proc. accélérée"),
    "APAT": ("🔧", "Proc. accélérée"),
    "DR": ("📄", "Renseignement"),
}
STATUS_LABELS = {
    "ENREGISTREMENT": "enregistré", "INSTRUCTION": "en instruction", "ACCEPTE": "✅ accepté",
    "REFUSE": "❌ refusé", "RENVOYE": "renvoyé", "CHANTIER": "chantier ouvert",
}
PRIORITY = {"DD": 0, "M": 1, "MPA": 1, "DP": 2, "APA": 3, "APAT": 3}

_communes_cache = None
permits_seen = set()


def sitg_query(service, params):
    url = f"{SITG}/{service}/FeatureServer/0/query"
    r = requests.post(url, data={**params, "f": "json"}, timeout=30, headers=UA)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data


def get_communes():
    """Contours des communes surveillées (mis en cache)."""
    global _communes_cache
    if _communes_cache is None:
        names = ",".join("'" + c.replace("'", "''") + "'" for c in COMMUNES)
        data = sitg_query("CAD_COMMUNE", {
            "where": f"COMMUNE IN ({names})", "outFields": "COMMUNE",
            "returnGeometry": "true", "maxAllowableOffset": "5", "geometryPrecision": "0",
        })
        _communes_cache = [(f["attributes"]["COMMUNE"], f["geometry"]["rings"]) for f in data["features"]]
        found = {c for c, _ in _communes_cache}
        missing = [c for c in COMMUNES if c not in found]
        if missing:
            log.warning(f"Communes introuvables (vérifie l'orthographe) : {missing}")
    return _communes_cache


def point_in_rings(x, y, rings):
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def fetch_permits(days=10):
    """Dossiers mis à jour ces derniers jours, situés dans les communes surveillées."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    communes = get_communes()
    features, offset = [], 0
    while True:
        data = sitg_query("SIT_AUTOR_DOSSIER", {
            "where": f"DATE_MAJ_2 >= DATE '{since}'",
            "outFields": "ID_DOSSIER,TYPE_DOSSIER,STATUT,DATE_DEPOT,DESCRIPTION,DATE_MAJ_2,LIEN_SAD",
            "returnGeometry": "true", "geometryPrecision": "0",
            "orderByFields": "DATE_MAJ_2 DESC", "resultOffset": str(offset), "resultRecordCount": "2000",
        })
        features += data.get("features", [])
        if not data.get("exceededTransferLimit"):
            break
        offset += len(data.get("features", []))
    permits = []
    for f in features:
        g = f.get("geometry") or {}
        if "x" not in g:
            continue
        for name, rings in communes:
            if point_in_rings(g["x"], g["y"], rings):
                a = f["attributes"]
                a["COMMUNE"] = name
                a["KEY"] = f"{a['ID_DOSSIER']}|{a['STATUT']}"
                permits.append(a)
                break
    return permits


def format_permits(permits, title):
    if not permits:
        return f"*{title}*\n\n_Aucun nouveau dossier dans tes communes._"
    permits = sorted(permits, key=lambda a: (a["COMMUNE"], PRIORITY.get(a["TYPE_DOSSIER"], 9)))
    lines, current, shown = [f"*{title}*"], None, 0
    for a in permits:
        if shown >= 25:
            break
        if a["COMMUNE"] != current:
            current = a["COMMUNE"]
            lines.append(f"\n📍 *{md_escape(current)}*")
        emoji, label = TYPE_LABELS.get(a["TYPE_DOSSIER"], ("📄", a["TYPE_DOSSIER"]))
        status = STATUS_LABELS.get(a["STATUT"], (a["STATUT"] or "").lower())
        depot = datetime.fromtimestamp(a["DATE_DEPOT"] / 1000, timezone.utc).strftime("%d.%m") if a.get("DATE_DEPOT") else "?"
        desc = (a.get("DESCRIPTION") or "").strip()
        desc = desc[:160] + ("…" if len(desc) > 160 else "")
        lines.append(f"{emoji} {label} · {status} · déposé le {depot}\n   {md_escape(desc)}\n   [{a['ID_DOSSIER']}]({a['LIEN_SAD']})")
        shown += 1
    if len(permits) > shown:
        lines.append(f"\n_+ {len(permits) - shown} autres dossiers (tape /fao pour la liste complète de la semaine)._")
    lines.append("\n_Source : registre officiel des autorisations de construire (SITG)._")
    return "\n".join(lines)


def permits_section(only_new=True):
    title = "🏗️ Autorisations de construire · tes communes"
    try:
        permits = fetch_permits(days=10 if only_new else 7)
    except Exception as e:
        log.error(f"Erreur autorisations: {e}")
        return f"*{title}*\n\n_Données indisponibles ce matin (erreur technique)._"
    if only_new:
        new = [p for p in permits if p["KEY"] not in permits_seen]
        permits_seen.update(p["KEY"] for p in permits)
        return format_permits(new, title + " (nouveautés)")
    return format_permits(permits, title + " (7 derniers jours)")


def init_permits_seen():
    """Au démarrage : marque comme déjà vus les dossiers de plus de 3 jours (évite de tout renvoyer)."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).timestamp() * 1000
        for p in fetch_permits(days=10):
            if (p.get("DATE_MAJ_2") or 0) < cutoff:
                permits_seen.add(p["KEY"])
        log.info(f"Autorisations : {len(permits_seen)} dossiers déjà connus, communes : {[c for c, _ in get_communes()]}")
    except Exception as e:
        log.error(f"Init autorisations: {e}")


# ---------------------------------------------------------------------------
# Chiffres clés (lundi + /chiffres)
# ---------------------------------------------------------------------------

MARKETS = [
    ("SMI", "^SSMI", 0), ("S&P 500", "^GSPC", 0), ("TA-35 (TLV)", "TA35.TA", 0),
    ("EUR/CHF", "EURCHF=X", 4), ("USD/CHF", "CHF=X", 4), ("USD/ILS", "ILS=X", 3),
    ("Pétrole Brent $", "BZ=F", 1), ("Or $/oz", "GC=F", 0),
]


def yahoo_quote(symbol):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(symbol)}",
                     params={"range": "1mo", "interval": "1d"}, headers=UA, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    last = res["meta"].get("regularMarketPrice") or closes[-1]
    week_ago = closes[-6] if len(closes) >= 6 else closes[0]
    return last, (last / week_ago - 1) * 100


def snb_latest(cube, keys):
    """Dernières valeurs mensuelles d'un cube de la BNS (data.snb.ch)."""
    start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m")
    r = requests.get(f"https://data.snb.ch/api/cube/{cube}/data/csv/en", params={"fromDate": start},
                     headers=UA, timeout=15)
    r.raise_for_status()
    values = {}
    for line in r.text.splitlines():
        cells = [c.strip('"') for c in line.split(";")]
        if len(cells) >= 3 and re.match(r"\d{4}-\d{2}", cells[0]) and cells[-1]:
            key = cells[-2]
            if key in keys:
                values[key] = (cells[0], float(cells[-1]))
    return values


def market_table():
    rows = []

    def one(item):
        name, sym, dec = item
        try:
            last, chg = yahoo_quote(sym)
            return f"{name:<16}{last:>11,.{dec}f}  {chg:+5.1f}%".replace(",", "'")
        except Exception as e:
            log.error(f"Erreur cours {sym}: {e}")
            return f"{name:<16}{'n/d':>11}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(one, MARKETS))

    rates = []
    try:
        hyp = snb_latest("zikrepro", {"MV", "50", "10"})
        month = max(v[0] for v in hyp.values())
        for key, label in (("MV", "Hypo variable"), ("50", "Hypo fixe 5 ans"), ("10", "Hypo fixe 10 ans")):
            if key in hyp:
                rates.append(f"{label:<16}{hyp[key][1]:>10.2f}%")
        rates.append(f"  (moyenne BNS, {month})")
    except Exception as e:
        log.error(f"Erreur taux hypo BNS: {e}")
    try:
        mm = snb_latest("zimoma", {"SARON"})
        if "SARON" in mm:
            rates.append(f"{'SARON':<16}{mm['SARON'][1]:>10.2f}%  (moy. {mm['SARON'][0]})")
    except Exception as e:
        log.error(f"Erreur SARON BNS: {e}")

    table = "\n".join(rows + ([""] + rates if rates else []))
    return f"*💹 Chiffres clés* _(variation sur 1 semaine)_\n```\n{table}\n```"


# ---------------------------------------------------------------------------
# Alerte urgence (toutes les 30 min)
# ---------------------------------------------------------------------------

URGENT_FEEDS = [
    gnews("attentat OR attaque terroriste OR explosion", "1h", country="FR"),
    gnews_en("breaking terror attack OR explosion OR missile strike", "1h"),
    gnews_en("breaking earthquake OR tsunami OR hurricane", "1h"),
    gnews_en("Israel Iran attack OR war breaking", "1h"),
    gnews("BNS décision taux surprise OR krach OR effondrement bourse", "1h"),
    gnews_en("stock market crash OR emergency rate cut OR bank collapse", "1h"),
]
urgent_seen_titles = set()
urgent_sent = deque(maxlen=20)


def check_urgent(seed_only=False):
    articles = fetch_articles(URGENT_FEEDS, 40)
    fresh = [a for a in articles if a["title"].lower()[:80] not in urgent_seen_titles]
    urgent_seen_titles.update(a["title"].lower()[:80] for a in articles)
    if seed_only or not fresh:
        return
    already = "\n".join(f"- {s}" for s in urgent_sent) or "(aucune)"
    titles = "\n".join(f"- {a['title']} ({a['published'][:22]})" for a in fresh)
    prompt = f"""Nouvelles dépêches de la dernière heure :
{titles}

Alertes déjà envoyées récemment (ne pas répéter le même événement) :
{already}

Tu filtres pour un investisseur basé à Genève, très attentif à Israël. Ne retiens QUE les événements
vraiment majeurs qui justifient de le prévenir immédiatement : attentat ou tentative d'attentat d'ampleur,
guerre qui démarre ou s'étend, frappe majeure impliquant Israël/Iran/États-Unis, catastrophe naturelle
meurtrière, krach ou mouvement de marché extrême, décision surprise d'une banque centrale (BNS, Fed, BCE).
En cas de doute, ne retiens rien. Il est normal de ne rien retenir la plupart du temps.

Réponds UNIQUEMENT en JSON : {{"alertes": [{{"titre": "...", "resume": "2 lignes max, en français", "impact": "1 ligne"}}]}}
ou {{"alertes": []}}."""
    try:
        raw = ask_claude(prompt, max_tokens=600, model=FAST_MODEL)
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception as e:
        log.error(f"Erreur alerte urgence: {e}")
        return
    hour = datetime.now(TZ).hour
    silent = hour >= 23 or hour < 7
    for al in data.get("alertes", [])[:3]:
        urgent_sent.append(al.get("titre", ""))
        send_message(f"🚨 *ALERTE : {md_escape(al.get('titre', ''))}*\n\n{md_escape(al.get('resume', ''))}\n\n"
                     f"_Impact : {md_escape(al.get('impact', ''))}_", silent=silent)
        log.info(f"Alerte urgence envoyée : {al.get('titre')}")


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------

def outlook_section(week_texts):
    articles = fetch_articles(OUTLOOK_FEEDS, 25)
    articles_text = "\n".join(f"- {a['title']} ({a['published'][:16]})\n  {a['summary']}" for a in articles)
    prompt = f"""Résumés de la semaine :
{chr(10).join(week_texts)}

Articles complémentaires :
{articles_text}

{OUTLOOK_INSTRUCTIONS}

Règles de forme :
- Français, direct, concret
- Format Markdown Telegram simple : *gras*, _italique_, puces "•"
- 25 lignes maximum"""
    try:
        text = ask_claude(prompt, max_tokens=1500)
    except Exception as e:
        log.error(f"Erreur Claude (perspectives): {e}")
        text = "_Analyse indisponible (erreur technique)._"
    return f"*{OUTLOOK_THEME}*\n_Analyse et projections, pas des certitudes._\n\n{text}"


def run_digest(sections, title, period_label, extra_first=None, extra_after=None, with_outlook=False):
    now = datetime.now(TZ).strftime("%d.%m.%Y · %H:%M")
    send_message(f"*{title}*\n_{now}_\n{'─' * 24}", remember=False)
    with ThreadPoolExecutor(max_workers=len(sections) + 1) as pool:
        first = pool.submit(extra_first) if extra_first else None
        futures = [pool.submit(build_section, it, period_label) for it in sections.items()]
        texts = [f.result() for f in futures]
        first_text = first.result() if first else None
    ordered = ([first_text] if first_text else []) + texts
    if extra_after:  # section insérée après la première section news
        ordered.insert(len(ordered) - len(texts) + 1, extra_after())
    for text in ordered:
        send_message(text)
        time.sleep(1)
    if with_outlook:
        log.info(f"Traitement : {OUTLOOK_THEME}")
        send_message(outlook_section(ordered))
    log.info(f"{title} envoyé ✓")


def daily_alert():
    run_digest(DAILY, "☀️ Alerte du jour", "dernières 24 heures",
               extra_after=lambda: permits_section(only_new=True))


def weekly_update():
    run_digest(WEEKLY, "📅 Update de la semaine", "7 derniers jours",
               extra_first=market_table, with_outlook=True)


# ---------------------------------------------------------------------------
# Questions libres
# ---------------------------------------------------------------------------

chat_history = deque(maxlen=12)
QA_SYSTEM = """Tu es l'assistant personnel de David, promoteur-investisseur immobilier basé à Genève,
qui suit de près Israël, la géopolitique, les marchés et l'IA. Tu réponds sur Telegram : en français,
direct, concret, sans blabla, 15 lignes maximum sauf s'il demande plus. Format Markdown Telegram simple
(*gras*, _italique_, puces "•"). Tu t'appuies sur les dernières news que le bot lui a envoyées (fournies
ci-dessous) et sur tes connaissances. Si tu n'es pas sûr d'une info récente, dis-le clairement plutôt
que d'inventer. Tu peux donner ton analyse, mais pas de conseil d'investissement personnalisé.

Dernières news envoyées par le bot :
"""


def answer_question(text, replied_text=None, message_id=None):
    send_typing()
    question = text if not replied_text else f"(À propos de ce message du bot : « {replied_text[:3000]} »)\n\n{text}"
    context = "\n\n---\n\n".join(list(recent_sent)[-8:]) or "(aucune pour l'instant)"
    messages = list(chat_history) + [{"role": "user", "content": question}]
    try:
        reply = ask_claude(None, max_tokens=1200, system=QA_SYSTEM + context[:30000], messages=messages)
    except Exception as e:
        log.error(f"Erreur Claude (question): {e}")
        reply = "_Désolé, je n'arrive pas à répondre pour l'instant (erreur technique)._"
    chat_history.append({"role": "user", "content": question})
    chat_history.append({"role": "assistant", "content": reply})
    send_message(reply, reply_to=message_id, remember=False)


# ---------------------------------------------------------------------------
# Commandes Telegram
# ---------------------------------------------------------------------------

HELP = """🤖 *Ce que je fais*
• Tous les jours à 07:00 : immobilier Genève, autorisations de construire dans tes communes, monde, Israël
• Le lundi à 07:15 : chiffres clés, économie, politique, géopolitique, IA + perspectives
• Toutes les 30 min : alerte 🚨 uniquement si événement majeur
• Pose-moi n'importe quelle question, ou réponds à une de mes news

*Commandes*
/alerte → alerte du jour maintenant
/hebdo → update de la semaine maintenant
/fao → autorisations de construire des 7 derniers jours
/chiffres → chiffres clés maintenant
/aide → ce message"""

_job_lock = threading.Lock()


def run_in_background(fn, *args):
    """Lance une tâche longue sans bloquer la lecture des messages."""
    def wrapper():
        with _job_lock:
            try:
                fn(*args)
            except Exception as e:
                log.exception(f"Erreur tâche {fn.__name__}: {e}")
    threading.Thread(target=wrapper, daemon=True).start()


last_update_id = None


def handle_update(u):
    msg = u.get("message") or {}
    if str(msg.get("chat", {}).get("id")) != CHAT_ID:
        return  # le bot ne répond qu'à toi
    text = (msg.get("text") or "").strip()
    if not text:
        return
    cmd = text.split()[0].split("@")[0].lower()
    if cmd in ("/alerte", "/recap"):
        send_message("Je prépare l'alerte du jour…", remember=False)
        run_in_background(daily_alert)
    elif cmd == "/hebdo":
        send_message("Je prépare l'update de la semaine…", remember=False)
        run_in_background(weekly_update)
    elif cmd == "/fao":
        send_message("Je regarde les autorisations de construire…", remember=False)
        run_in_background(lambda: send_message(permits_section(only_new=False)))
    elif cmd == "/chiffres":
        run_in_background(lambda: send_message(market_table()))
    elif cmd in ("/aide", "/help", "/start"):
        send_message(HELP, remember=False)
    else:
        replied = (msg.get("reply_to_message") or {}).get("text")
        threading.Thread(target=answer_question, args=(text, replied, msg.get("message_id")), daemon=True).start()


def check_messages():
    global last_update_id
    params = {"timeout": 2}
    if last_update_id is not None:
        params["offset"] = last_update_id + 1
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", params=params, timeout=10)
        for u in r.json().get("result", []):
            last_update_id = u["update_id"]
            handle_update(u)
    except Exception as e:
        log.error(f"Erreur getUpdates: {e}")


def skip_old_updates():
    """Ignore les messages reçus avant le (re)démarrage."""
    global last_update_id
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", params={"timeout": 0}, timeout=10)
        results = r.json().get("result", [])
        if results:
            last_update_id = results[-1]["update_id"]
    except Exception as e:
        log.error(f"Erreur init updates: {e}")


# ---------------------------------------------------------------------------
# Planning (heure de Genève, quel que soit le fuseau du serveur)
# ---------------------------------------------------------------------------

schedule.every().day.at("07:00", TZ_NAME).do(run_in_background, daily_alert)
schedule.every().monday.at("07:15", TZ_NAME).do(run_in_background, weekly_update)
schedule.every(30).minutes.do(lambda: threading.Thread(target=check_urgent, daemon=True).start())

if __name__ == "__main__":
    skip_old_updates()
    log.info("Bot démarré !")
    threading.Thread(target=init_permits_seen, daemon=True).start()
    threading.Thread(target=check_urgent, kwargs={"seed_only": True}, daemon=True).start()
    send_message("🤖 Bot mis à jour.\n\n" + HELP, remember=False)
    while True:
        check_messages()
        schedule.run_pending()
        time.sleep(2)
