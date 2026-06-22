"""
Bot Telegram de veille personnalisée - David Abergel
"""

import os, time, logging, requests, feedparser, schedule
from datetime import datetime
from dotenv import load_dotenv
import anthropic

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

FEEDS = {
    "🏠 Biens haut de gamme Genève": [
        "https://news.google.com/rss/search?q=immobilier+luxe+geneve+vente+when:1d&hl=fr&gl=CH&ceid=CH:fr",
        "https://news.google.com/rss/search?q=villa+appartement+geneve+prix+when:1d&hl=fr&gl=CH&ceid=CH:fr",
    ],
    "💰 Fiscalité & Impôts Genève": [
        "https://news.google.com/rss/search?q=impot+geneve+fiscalite+when:1d&hl=fr&gl=CH&ceid=CH:fr",
        "https://news.google.com/rss/search?q=reforme+fiscale+suisse+when:1d&hl=fr&gl=CH&ceid=CH:fr",
    ],
    "🌍 Israël / Moyen-Orient": [
        "https://news.google.com/rss/search?q=israel+gaza+when:1d&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=iran+liban+moyen+orient+when:1d&hl=fr&gl=FR&ceid=FR:fr",
    ],
    "🤖 Intelligence Artificielle": [
        "https://news.google.com/rss/search?q=intelligence+artificielle+when:1d&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=ChatGPT+Claude+Gemini+when:1d&hl=fr&gl=FR&ceid=FR:fr",
    ],
    "🌋 Catastrophes naturelles": [
        "https://news.google.com/rss/search?q=catastrophe+naturelle+seisme+when:1d&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=inondation+eruption+cyclone+when:1d&hl=fr&gl=FR&ceid=FR:fr",
    ],
    "⚔️ Conflits & Géopolitique": [
        "https://news.google.com/rss/search?q=guerre+conflit+monde+when:1d&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=attentat+tension+diplomatique+when:1d&hl=fr&gl=FR&ceid=FR:fr",
    ],
    "🗳️ Élections mondiales": [
        "https://news.google.com/rss/search?q=election+presidentielle+2026+when:1d&hl=fr&gl=FR&ceid=FR:fr",
    ],
    "📈 Marchés financiers": [
        "https://news.google.com/rss/search?q=bourse+marche+financier+when:1d&hl=fr&gl=FR&ceid=FR:fr",
        "https://www.marketwatch.com/rss/topstories",
    ],
    "🏆 Sport": [
        "https://news.google.com/rss/search?q=sport+resultat+when:1d&hl=fr&gl=FR&ceid=FR:fr",
    ],
}

def fetch_articles(urls):
    articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:4]:
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            log.error(f"Erreur fetch {url}: {e}")
    return articles[:8]

def summarize_theme(theme, articles):
    if not articles:
        return "_Aucune actualité disponible pour ce thème aujourd'hui._"
    articles_text = "\n".join([
        f"- {a['title']} ({a['published'][:16] if a['published'] else ''})\n  {a['summary']}"
        for a in articles
    ])
    prompt = f"""Voici des articles récents sur le thème : {theme}

{articles_text}

Rédige un récapitulatif concis en français (8-12 lignes) avec :
- 3 à 5 points clés (faits, chiffres, tendances)
- Style télégraphique, informatif et neutre
- Liens importants conservés entre parenthèses
Format Markdown Telegram (*bold*, _italic_). Va directement aux faits sans introduction."""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text

def send_message(text):
    url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
    except Exception as e:
        log.error(f"Erreur envoi: {e}")

def send_digest():
    now = datetime.now().strftime("%A %d %B · %H:%M")
    send_message(f"*📰 Veille quotidienne*\n_{now}_\n{'─'*28}")
    time.sleep(1)
    for theme, urls in FEEDS.items():
        log.info(f"Traitement: {theme}")
        articles = fetch_articles(urls)
        summary = summarize_theme(theme, articles)
        send_message(f"*{theme}*\n\n{summary}")
        time.sleep(2)
    send_message("_Fin du digest · /recap pour relancer_")
    log.info("Digest envoyé ✓")

def check_messages():
    url = "https://api.telegram.org/bot" + TOKEN + "/getUpdates"
    try:
        r = requests.get(url, params={"timeout": 2})
        updates = r.json().get("result", [])
        for u in updates:
            text = u.get("message", {}).get("text", "")
            if text == "/recap":
                send_message("Je prépare ton digest...")
                send_digest()
    except:
        pass

schedule.every().day.at("07:30").do(send_digest)
schedule.every().day.at("19:00").do(send_digest)

log.info("Bot démarré !")
send_message("Bot démarré ! Tape /recap pour un digest ou pose-moi une question.")
send_digest()

while True:
    check_messages()
    schedule.run_pending()
    time.sleep(3)
