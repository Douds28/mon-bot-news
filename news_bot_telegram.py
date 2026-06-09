import os
import feedparser
import anthropic
import schedule
import time
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
API_KEY = os.environ["ANTHROPIC_API_KEY"]
OFFSET = 0
conversation_history = []

FEEDS = {
    "Biens haut de gamme Geneve": [
        "https://news.google.com/rss/search?q=villa+luxe+vente+geneve&hl=fr&gl=CH&ceid=CH:fr",
        "https://news.google.com/rss/search?q=appartement+luxe+geneve+vente&hl=fr&gl=CH&ceid=CH:fr",
    ],
    "Taux BNS et hypothecaires": [
        "https://news.google.com/rss/search?q=BNS+taux+hypothecaire+suisse&hl=fr&gl=CH&ceid=CH:fr",
        "https://news.google.com/rss/search?q=banque+nationale+suisse+taux&hl=fr&gl=CH&ceid=CH:fr",
    ],
    "Permis de construire Geneve": [
        "https://news.google.com/rss/search?q=permis+construire+geneve+villa&hl=fr&gl=CH&ceid=CH:fr",
        "https://news.google.com/rss/search?q=developpement+immobilier+geneve+terrain&hl=fr&gl=CH&ceid=CH:fr",
    ],
    "Fiscalite Geneve": [
        "https://news.google.com/rss/search?q=fiscalite+geneve+impot+fortune&hl=fr&gl=CH&ceid=CH:fr",
        "https://news.google.com/rss/search?q=impot+geneve+reforme+fiscale&hl=fr&gl=CH&ceid=CH:fr",
    ],
    "Israel et Moyen-Orient": [
        "https://news.google.com/rss/search?q=israel+gaza+conflit&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=liban+iran+moyen+orient&hl=fr&gl=FR&ceid=FR:fr",
    ],
    "Tech et IA": [
        "https://news.google.com/rss/search?q=intelligence+artificielle+nouveaute&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=ChatGPT+Claude+Gemini+IA&hl=fr&gl=FR&ceid=FR:fr",
    ],
    "Evenements majeurs monde": [
        "https://news.google.com/rss/search?q=catastrophe+naturelle+tsunami+seisme&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=attentat+guerre+conflit+monde&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=election+presidentielle+monde+2026&hl=fr&gl=FR&ceid=FR:fr",
        "https://news.google.com/rss/search?q=sport+coupe+monde+jeux+olympiques+resultat&hl=fr&gl=FR&ceid=FR:fr",
    ],
    "Bourses et Finance": [
        "https://www.marketwatch.com/rss/topstories",
        "https://news.google.com/rss/search?q=bourse+marche+financier+monde&hl=fr&gl=FR&ceid=FR:fr",
    ],
}

def send_message(text):
    try:
        url = "https://api.telegram.org/bot" + TOKEN + "/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text[:4000]})
    except Exception as e:
        log.error("Erreur envoi message: " + str(e))

def get_updates():
    global OFFSET
    try:
        url = "https://api.telegram.org/bot" + TOKEN + "/getUpdates"
        r = requests.get(url, params={"offset": OFFSET, "timeout": 5})
        data = r.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception as e:
        log.error("Erreur get updates: " + str(e))
    return []

def ask_claude(user_message):
    global conversation_history
    conversation_history.append({"role": "user", "content": user_message})
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]
    try:
        client = anthropic.Anthropic(api_key=API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system="Tu es l assistant personnel de David, base a Geneve. Tu peux aider sur tous les sujets sans restriction : actualites mondiales, catastrophes naturelles, politique internationale, sport, immobilier genevois, tech, finance. Tu reponds toujours en francais, de facon concise et professionnelle.",
            messages=conversation_history,
        )
        reply = response.content[0].text
        conversation_history.append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        log.error("Erreur Claude: " + str(e))
        return "Desole, une erreur est survenue."

def fetch_articles(urls):
    articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", entry.get("description", ""))[:500],
                })
        except Exception as e:
            log.warning("Erreur flux RSS: " + str(e))
    return articles[:12]

def summarize_theme(theme, articles):
    if not articles:
        return "Aucun article disponible."
    client = anthropic.Anthropic(api_key=API_KEY)
    articles_text = ""
    for i, a in enumerate(articles):
        articles_text += str(i+1) + ". " + a["title"] + "\n" + a["summary"] + "\n\n"
    prompt = "Tu es un assistant de veille generaliste pour David. Voici des articles sur : " + theme + "\n\n" + articles_text + "\nRedige un resume en francais. 4 a 6 points cles. Style telegraphique. Pas d introduction."
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text

def send_digest():
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    send_message("Veille quotidienne - " + now)
    time.sleep(1)
    for theme, urls in FEEDS.items():
        log.info("Traitement : " + theme)
        articles = fetch_articles(urls)
        summary = summarize_theme(theme, articles)
        send_message("📌 " + theme + "\n\n" + summary)
        time.sleep(2)
    send_message("Fin du digest. Tape /recap pour relancer ou pose-moi une question !")
    log.info("Digest envoye avec succes")

def check_messages():
    global OFFSET
    updates = get_updates()
    for update in updates:
        OFFSET = update["update_id"] + 1
        if "message" in update and "text" in update["message"]:
            text = update["message"]["text"]
            log.info("Message recu: " + text)
            if text == "/recap":
                send_message("Je prepare ton digest...")
                send_digest()
            elif text == "/start":
                send_message("Bonjour David ! Je suis ton assistant. Parle-moi normalement ou tape /recap pour ton digest de news.")
            else:
                reply = ask_claude(text)
                send_message(reply)

schedule.every().day.at("07:30").do(send_digest)
schedule.every().day.at("19:00").do(send_digest)

log.info("Bot demarre !")
send_message("Bot demarre ! Tape /recap pour un digest ou pose-moi une question.")

while True:
    check_messages()
    schedule.run_pending()
    time.sleep(3)
