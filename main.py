from fastapi import FastAPI, Request, HTTPException
import httpx
import os
import pytz
import re
import logging
import json
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Read.ai Webhook Integration",
    description="Webhook integration between Read.ai, Notion, and WhatsApp",
    version="1.0.0"
)

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Read.ai Webhook Integration",
        "endpoints": {
            "/webhook": "POST - Receives Read.ai meeting end webhooks",
            "/docs": "GET - OpenAPI documentation",
            "/redoc": "GET - ReDoc documentation"
        }
    }

# Variáveis de ambiente
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
ZAPI_INSTANCE = os.getenv("ZAPI_INSTANCE")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN")
ADMIN_PHONES = [p.strip() for p in os.getenv("ADMIN_PHONES", "").split(",") if p]
TZ = pytz.timezone(os.getenv("TZ", "America/Sao_Paulo"))

# Função para buscar a página no Notion pelo email
def notion_headers():
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    logger.info(f"Using Notion headers: {json.dumps(headers, default=str)}")
    return headers

async def find_page_by_email(email):
    search_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    logger.info(f"Searching Notion for email: {email}")
    logger.info(f"Using database ID: {NOTION_DATABASE_ID}")
    
    search_body = {
        "filter": {
            "property": "Email",
            "email": {"equals": email}
        }
    }
    logger.info(f"Search body: {json.dumps(search_body, default=str)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(search_url, json=search_body, headers=notion_headers())
            response.raise_for_status()
            data = response.json()
            logger.info(f"Notion search response: {json.dumps(data, default=str)}")
            
            if not data.get("results"):
                logger.warning(f"No results found for email: {email}")
                return None
            
            page_id = data["results"][0]["id"]
            logger.info(f"Found Notion page ID: {page_id}")
            return page_id
    except Exception as e:
        logger.error(f"Error searching Notion: {str(e)}")
        raise

# Função para atualizar status e transcrição
def build_transcript(transcript_data):
    # Concatena as falas dos speakers
    if not transcript_data or "speaker_blocks" not in transcript_data:
        return ""
    return "\n".join([
        f"{block['speaker']['name']}: {block['words']}" for block in transcript_data["speaker_blocks"]
    ])

def markdown_to_notion_rich_text(text, chunk_size=2000):
    """
    Converte markdown simples com links [texto](url) para blocos rich_text do Notion.
    Divide em blocos de até chunk_size caracteres.
    """
    pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    parts = []
    last_end = 0
    for match in pattern.finditer(text):
        # Texto antes do link
        if match.start() > last_end:
            parts.append({"text": {"content": text[last_end:match.start()]}})
        # O link
        link_text = match.group(1)
        link_url = match.group(2)
        parts.append({"text": {"content": link_text, "link": {"url": link_url}}})
        last_end = match.end()
    # Qualquer texto depois do último link
    if last_end < len(text):
        parts.append({"text": {"content": text[last_end:]}})
    # Agora, dividir em blocos de até chunk_size caracteres
    blocks = []
    current_block = {"text": {"content": ""}}
    for part in parts:
        content = part["text"]["content"]
        link = part["text"].get("link")
        while content:
            space_left = chunk_size - len(current_block["text"]["content"])
            if space_left <= 0:
                if current_block["text"]["content"]:
                    blocks.append(current_block)
                current_block = {"text": {"content": ""}}
                continue
            take = content[:space_left]
            if link:
                blocks.append({"text": {"content": take, "link": link}})
            else:
                current_block["text"]["content"] += take
            content = content[space_left:]
    if current_block["text"]["content"]:
        blocks.append(current_block)
    return blocks

async def update_notion_page(page_id, status, transcript, full_markdown):
    update_url = f"https://api.notion.com/v1/pages/{page_id}"
    logger.info(f"Updating Notion page: {page_id}")
    
    update_data = {
        "properties": {
            "Status": {"status": {"name": status}},
            "Transcrição": {"rich_text": markdown_to_notion_rich_text(transcript)},
            "Resumo Completo": {"rich_text": markdown_to_notion_rich_text(full_markdown)}
        }
    }
    logger.info(f"Update data: {json.dumps(update_data, default=str)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(update_url, json=update_data, headers=notion_headers())
            response.raise_for_status()
            logger.info(f"Notion update response: {json.dumps(response.json(), default=str)}")
    except Exception as e:
        logger.error(f"Error updating Notion: {str(e)}")
        raise

# Função para enviar mensagem WhatsApp via Z-API para múltiplos números
async def send_whatsapp_message_to_admins(message):
    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE}/token/{ZAPI_TOKEN}/send-text"
    headers = {
        "Content-Type": "application/json",
        "Client-Token": ZAPI_CLIENT_TOKEN
    }
    async with httpx.AsyncClient() as client:
        for phone in ADMIN_PHONES:
            payload = {
                "phone": phone,
                "message": message
            }
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        logger.info(f"Received webhook data: {json.dumps(data, default=str)}")
        
        # 1. Pega o email do owner da reunião
        email = data["owner"]["email"]
        logger.info(f"Processing meeting for email: {email}")
        
        # 2. Busca a página no Notion
        page_id = await find_page_by_email(email)
        if not page_id:
            error_msg = f"Linha não encontrada para o e-mail: {email}"
            logger.error(error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
            
        # 3. Monta a transcrição
        transcript = build_transcript(data.get("transcript"))
        logger.info(f"Built transcript, length: {len(transcript)}")
        
        # 4. Monta o resumo completo
        full_markdown = build_full_meeting_markdown(data)
        logger.info(f"Built full markdown, length: {len(full_markdown)}")
        
        # 5. Atualiza status e transcrição
        try:
            await update_notion_page(page_id, "Reunião Realizada", transcript, full_markdown)
            logger.info("Successfully updated Notion page")
        except Exception as e:
            logger.error(f"Failed to update Notion: {str(e)}")
            raise
            
        # 6. Monta mensagem WhatsApp
        owner = data["owner"]["name"]
        lead = next((p["name"] for p in data.get("participants", []) if p["email"] != email), "Lead")
        assunto = ", ".join([t["text"] for t in data.get("topics", [])])
        proximas_etapas = ", ".join([a["text"] for a in data.get("action_items", [])])
        motivo = "Motivo XYZ"  # Personalize conforme necessário
        
        whatsapp_msg = (
            f"{owner} realizou a reunião com o Lead {lead}. "
            f"O assunto abordado foi {assunto}. "
            f"As próximas etapas são {proximas_etapas}. "
            f"O Lead demonstra altas chances de fechar negócio por conta de {motivo}."
        )
        logger.info(f"Prepared WhatsApp message: {whatsapp_msg}")
        
        # 7. Envia WhatsApp para todos os admins
        try:
            await send_whatsapp_message_to_admins(whatsapp_msg)
            logger.info("Successfully sent WhatsApp messages")
        except Exception as e:
            logger.error(f"Failed to send WhatsApp messages: {str(e)}")
            raise
            
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

def build_full_meeting_markdown(data):
    title = data.get("title", "Reunião")
    report_url = data.get("report_url", "#")
    start_time = data.get("start_time", "")
    end_time = data.get("end_time", "")
    platform = "Zoom"
    participants = ", ".join([p["name"] for p in data.get("participants", [])])
    summary = data.get("summary", "")
    chapters = ""
    for chapter in data.get("chapter_summaries", []):
        chapters += f"**{chapter['title']}**\n{chapter['description']}\n"
        for topic in chapter.get("topics", []):
            chapters += f"- {topic['text']}\n"
        chapters += "\n"
    action_items = ""
    for a in data.get("action_items", []):
        action_items += f"- [ ] {a['text']}\n"
    key_questions = ""
    for k in data.get("key_questions", []):
        key_questions += f"- {k['text']}\n"
    transcript = ""
    if data.get("transcript") and data["transcript"].get("speaker_blocks"):
        for block in data["transcript"]["speaker_blocks"]:
            transcript += f"**{block['speaker']['name']}:** {block['words']}\n\n"
    md = f"""# {start_time[:10]} {title}
**Meeting:** [{title}]({report_url})
**Event time:** {start_time} - {end_time}
**Platform:** {platform}
**Participants:** {participants}

## **✨ Summary**
{summary}

## **💬 Chapters & Topics**
{chapters}

## **✅ Action Items**
{action_items}

## **🔍 Key Questions**
{key_questions}

## **🗣️ Transcript**
{transcript}
"""
    return md 