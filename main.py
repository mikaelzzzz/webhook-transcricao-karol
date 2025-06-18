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
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Charset": "utf-8"
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
                return None, None
            
            # Get both the page ID and the Page ID property
            page = data["results"][0]
            page_id = page["id"]
            parent_page_id = page["properties"].get("Page ID", {}).get("formula", {}).get("string")
            
            if not parent_page_id:
                logger.error("Page ID property not found or empty")
                return None, None
                
            logger.info(f"Found Notion page ID: {page_id} with Parent Page ID: {parent_page_id}")
            return page_id, parent_page_id
    except Exception as e:
        logger.error(f"Error searching Notion: {str(e)}")
        raise

# Função para atualizar status e transcrição
def build_transcript(transcript_data):
    if not transcript_data or "speaker_blocks" not in transcript_data:
        return "Transcrição não disponível"
        
    # Construir a transcrição formatada
    formatted_transcript = []
    for block in transcript_data["speaker_blocks"]:
        speaker = block.get("speaker", {}).get("name", "Desconhecido")
        words = block.get("words", "")
        start_time = block.get("start_time", "")
        
        if start_time:
            try:
                # Converter timestamp para datetime
                timestamp_ms = int(start_time)
                dt = datetime.fromtimestamp(timestamp_ms / 1000)
                local_time = dt.astimezone(TZ)
                timestamp_str = local_time.strftime("%H:%M:%S")
            except:
                timestamp_str = ""
        else:
            timestamp_str = ""
            
        formatted_line = f"[{timestamp_str}] {speaker}: {words}"
        formatted_transcript.append(formatted_line)
    
    return "\n".join(formatted_transcript)

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

async def create_meeting_page(parent_page_id, meeting_data, transcript, full_markdown):
    create_url = "https://api.notion.com/v1/pages"
    logger.info(f"Creating meeting page under parent ID: {parent_page_id}")
    
    # Usar o título original da reunião
    title = meeting_data.get("title", "Sem título")
    
    # Converter o markdown em blocos rich_text
    markdown_blocks = markdown_to_notion_rich_text(full_markdown)
    transcript_blocks = markdown_to_notion_rich_text(transcript)
    
    create_data = {
        "parent": {
            "page_id": parent_page_id
        },
        "icon": {
            "external": {
                "url": "https://i.imgur.com/pFbQrWe.png"
            }
        },
        "cover": {
            "external": {
                "url": "https://i.imgur.com/AWoGTe4.png"
            }
        },
        "properties": {
            "title": {
                "title": [
                    {
                        "text": {
                            "content": title
                        }
                    }
                ]
            }
        },
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": markdown_blocks
                }
            },
            {
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": "🗣️ Transcript"}}]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": transcript_blocks
                }
            }
        ]
    }
    
    logger.info(f"Create data: {json.dumps(create_data, default=str)}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(create_url, json=create_data, headers=notion_headers())
            response.raise_for_status()
            result = response.json()
            logger.info(f"Created meeting page with ID: {result.get('id')}")
            return result.get('id')
    except Exception as e:
        logger.error(f"Error creating meeting page: {str(e)}")
        raise

async def update_lead_status(page_id, status="Reunião Realizada"):
    update_url = f"https://api.notion.com/v1/pages/{page_id}"
    logger.info(f"Updating lead status for page: {page_id}")
    
    update_data = {
        "icon": {
            "external": {
                "url": "https://i.imgur.com/pFbQrWe.png"
            }
        },
        "properties": {
            "Status": {"status": {"name": status}}
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(update_url, json=update_data, headers=notion_headers())
            response.raise_for_status()
            logger.info("Successfully updated lead status and icon")
    except Exception as e:
        logger.error(f"Error updating lead status: {str(e)}")
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
        
        # 2. Busca a página no Notion e o Page ID
        page_id, parent_page_id = await find_page_by_email(email)
        if not page_id or not parent_page_id:
            error_msg = f"Linha não encontrada para o e-mail: {email}"
            logger.error(error_msg)
            raise HTTPException(status_code=404, detail=error_msg)
            
        # 3. Monta a transcrição
        transcript = build_transcript(data)
        logger.info(f"Built transcript, length: {len(transcript)}")
        
        # 4. Monta o resumo completo
        full_markdown = build_full_meeting_markdown(data)
        logger.info(f"Built full markdown, length: {len(full_markdown)}")
        
        # 5. Cria uma nova página para a reunião
        try:
            await create_meeting_page(parent_page_id, data, transcript, full_markdown)
            logger.info("Successfully created meeting page")
        except Exception as e:
            logger.error(f"Failed to create meeting page: {str(e)}")
            raise
            
        # 6. Atualiza o status do lead
        try:
            await update_lead_status(page_id)
            logger.info("Successfully updated lead status")
        except Exception as e:
            logger.error(f"Failed to update lead status: {str(e)}")
            raise
            
        # 7. Monta mensagem WhatsApp
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
        
        # 8. Envia WhatsApp para todos os admins
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
    sections = []
    
    # Título e Informações Básicas
    title = data.get("title", "Sem título")
    start_time = data.get("start_time", "")
    end_time = data.get("end_time", "")
    report_url = data.get("report_url", "")
    
    # Cabeçalho
    sections.append(f"# {title}\n")
    
    # Link para o relatório
    if report_url:
        sections.append(f"**Meeting:** [{title}]({report_url})")
    else:
        sections.append(f"**Meeting:** {title}")
    
    # Data e hora do evento
    if start_time and end_time:
        try:
            start_dt = datetime.fromisoformat(start_time.rstrip('Z'))
            end_dt = datetime.fromisoformat(end_time.rstrip('Z'))
            start_local = start_dt.astimezone(TZ)
            end_local = end_dt.astimezone(TZ)
            event_time = f"{start_local.strftime('%Y-%m-%d %I:%M %p')} - {end_local.strftime('%I:%M %p')} ({TZ.zone})"
            sections.append(f"**Event time:** {event_time}")
        except:
            sections.append(f"**Event time:** {start_time} - {end_time}")
    
    # Participantes
    participants = data.get("participants", [])
    if participants:
        sections.append(f"**Participants:** {', '.join(p.get('name', '') for p in participants)}\n")
    
    # Resumo
    summary = data.get("summary", "")
    if summary:
        sections.append("## ✨ Summary\n")
        sections.append(f"{summary}\n")
    
    # Capítulos e Tópicos
    chapter_summaries = data.get("chapter_summaries", [])
    if chapter_summaries:
        sections.append("## 💬 Chapters & Topics\n")
        for chapter in chapter_summaries:
            title = chapter.get("title", "")
            description = chapter.get("description", "")
            chapter_topics = chapter.get("topics", [])
            
            sections.append(f"**{title}** [{description}]")
            for topic in chapter_topics:
                sections.append(f"- {topic.get('text', '')}")
            sections.append("")
    
    # Action Items
    action_items = data.get("action_items", [])
    if action_items:
        sections.append("## ✅ Action Items\n")
        for item in action_items:
            sections.append(f"- [ ] {item.get('text', '')}")
        sections.append("")
    
    # Key Questions
    key_questions = data.get("key_questions", [])
    if key_questions:
        sections.append("## 🔍 Key Questions\n")
        for question in key_questions:
            sections.append(f"- {question.get('text', '')}")
        sections.append("")
    
    return "\n".join(sections) 