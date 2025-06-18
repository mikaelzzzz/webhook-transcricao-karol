# Notion Read.ai Webhook Integration

A FastAPI webhook integration that connects Read.ai meeting summaries with Notion and WhatsApp notifications.

## Features

- Receives Read.ai meeting end webhooks
- Finds corresponding Notion database entries by participant email
- Updates Notion entries with:
  - Status changed to "Reunião Realizada"
  - Full meeting transcript with clickable links
  - Comprehensive meeting summary with chapters, action items, and key questions
- Sends WhatsApp notifications to admin numbers via Z-API

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/notion-readai-webhook.git
cd notion-readai-webhook
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
NOTION_TOKEN=your_notion_token
NOTION_DATABASE_ID=your_database_id
ZAPI_INSTANCE=your_zapi_instance
ZAPI_TOKEN=your_zapi_token
ZAPI_CLIENT_TOKEN=your_zapi_client_token
ADMIN_PHONES=phone1,phone2,phone3
TZ=America/Sao_Paulo
```

4. Run the server:
```bash
uvicorn main:app --reload
```

## Webhook Configuration

1. In Read.ai, configure the webhook endpoint:
   - URL: `https://your-domain.com/webhook`
   - Event: `meeting.ended`

2. Ensure your Notion database has the following properties:
   - Email (email type)
   - Status (status type)
   - Transcrição (rich text type)
   - Resumo Completo (rich text type)

## API Documentation

The API exposes a single endpoint:

- `POST /webhook`: Receives Read.ai meeting end webhooks
  - Processes meeting data
  - Updates Notion database
  - Sends WhatsApp notifications

## Environment Variables

| Variable | Description |
|----------|-------------|
| NOTION_TOKEN | Notion API integration token |
| NOTION_DATABASE_ID | ID of your Notion database |
| ZAPI_INSTANCE | Z-API instance ID |
| ZAPI_TOKEN | Z-API token |
| ZAPI_CLIENT_TOKEN | Z-API client token |
| ADMIN_PHONES | Comma-separated list of admin phone numbers |
| TZ | Timezone (default: America/Sao_Paulo) |

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 