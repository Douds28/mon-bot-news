"""
Bot Telegram de veille personnalisée - David Abergel

- Alerte quotidienne : tous les jours à 07:00 (heure de Genève)
    Immobilier Genève · Monde (événements majeurs) · Israël / Moyen-Orient
- Update hebdo : le lundi à 07:15 (heure de Genève)
    Économie Suisse & Europe · Politique France/Israël/US · Géopolitique mondiale · IA

Commandes Telegram : /alerte (relance l'alerte du jour) · /hebdo (relance l'update hebdo)
"""

import os, time, logging, requests, feedparser, schedule
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import anthropic

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
TZ_NAME = "Europe/Zurich"
TZ = ZoneInfo(TZ_NAME)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------------------------------------------------------------------------
# Sources : recherches Google News (filtrables par site) + quelques flux directs
# ---------------------------------------------------------------------------

def gnews(query, period="1d", lang="fr", country="CH"):
    """Flux RSS Google News pour une recherche (period : 1d, 7d...)."""
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


# ---------------------------------------------------------------------------
# Récupération + résumé
# ---------------------------------------------------------------------------

def fetch_feed(url):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
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
        msg = client.messages.create(
            model=MODEL,
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        log.error(f"Erreur Claude ({theme}): {e}")
        return "_Résumé indisponible (erreur technique)._"


def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text[:4000], "disable_web_page_preview": True}
    try:
        r = requests.post(url, json={**payload, "parse_mode": "Markdown"}, timeout=20)
        if not r.ok:  # Markdown mal formé → on renvoie en texte brut
            log.warning(f"Envoi Markdown refusé : {r.text[:200]}")
            r = requests.post(url, json=payload, timeout=20)
            if not r.ok:
                log.error(f"Envoi refusé : {r.text[:200]}")
    except Exception as e:
        log.error(f"Erreur envoi: {e}")


def build_section(item, period_label):
    theme, config = item
    log.info(f"Traitement : {theme}")
    articles = fetch_articles(config["feeds"], config["max_articles"])
    return f"*{theme}*\n\n{summarize(theme, config, articles, period_label)}"


def run_digest(sections, title, period_label):
    now = datetime.now(TZ).strftime("%d.%m.%Y · %H:%M")
    send_message(f"*{title}*\n_{now}_\n{'─' * 24}")
    # Tous les thèmes sont préparés en parallèle, puis envoyés dans l'ordre
    with ThreadPoolExecutor(max_workers=len(sections)) as pool:
        texts = list(pool.map(lambda it: build_section(it, period_label), sections.items()))
    for text in texts:
        send_message(text)
        time.sleep(1)
    log.info(f"{title} envoyé ✓")


def daily_alert():
    run_digest(DAILY, "☀️ Alerte du jour", "dernières 24 heures")


def weekly_update():
    run_digest(WEEKLY, "📅 Update de la semaine", "7 derniers jours")


# ---------------------------------------------------------------------------
# Commandes Telegram
# ---------------------------------------------------------------------------

last_update_id = None


def check_messages():
    global last_update_id
    params = {"timeout": 2}
    if last_update_id is not None:
        params["offset"] = last_update_id + 1
    try:
        r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", params=params, timeout=10)
        for u in r.json().get("result", []):
            last_update_id = u["update_id"]
            text = (u.get("message", {}).get("text") or "").strip().lower()
            if text in ("/alerte", "/recap"):
                send_message("Je prépare l'alerte du jour…")
                daily_alert()
            elif text == "/hebdo":
                send_message("Je prépare l'update de la semaine…")
                weekly_update()
    except Exception as e:
        log.error(f"Erreur getUpdates: {e}")


def skip_old_updates():
    """Ignore les commandes reçues avant le (re)démarrage."""
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

schedule.every().day.at("07:00", TZ_NAME).do(daily_alert)
schedule.every().monday.at("07:15", TZ_NAME).do(weekly_update)

if __name__ == "__main__":
    skip_old_updates()
    log.info("Bot démarré !")
    send_message("🤖 Bot mis à jour.\n• Alerte tous les jours à 07:00\n• Update hebdo le lundi à 07:15\n\n/alerte → alerte du jour maintenant\n/hebdo → update de la semaine maintenant")
    while True:
        check_messages()
        schedule.run_pending()
        time.sleep(3)
