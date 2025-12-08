You're right! Here's a complete README.md for your Amazon AI Agent:

---

🚀 Amazon AI Agent - Investment & Product Analysis

A FastAPI-based AI agent that analyzes Amazon products for investment opportunities. Clients submit via Google Forms, the agent analyzes using DeepSeek AI and Apify scraping, and results are sent to Make.com for notifications.

🌟 Features

· Smart Routing: Automatically routes client submissions to product or keyword analysis
· AI-Powered Analysis: Uses DeepSeek AI for market insights and recommendations
· Amazon Scraping: Integrates with Apify for real-time product data
· Client Memory: Remembers client history for personalized analysis
· Queue Management: Redis-based task queue for scalability
· Make.com Integration: Seamless connection to Google Forms, Sheets, and Email

🏗️ Architecture

```
Google Form (Client Input)
        ↓
    Make.com Router
        ├── If investment & price → Product Analysis
        └── If description only → Keyword Analysis
        ↓
    Amazon AI Agent (Railway)
        ├── DeepSeek AI Analysis
        ├── Apify Amazon Scraping
        ├── Redis Queue
        └── PostgreSQL Memory
        ↓
    Make.com Results
        ├── Google Sheets
        └── Email Notifications
```

📁 Project Structure

```
amazon_ai_queue/
├── app/
│   ├── main.py              # FastAPI application
│   ├── agent.py            # Main AI agent with DeepSeek
│   ├── apify_client.py     # Amazon product scraping
│   ├── keyword_analyzer.py # Keyword market analysis
│   ├── memory_manager.py   # Client memory system
│   ├── queue_manager.py    # Redis task queue
│   ├── database.py         # PostgreSQL connections
│   ├── make_client.py      # Make.com webhook integration
│   └── logger.py          # Logging configuration
├── railway.json           # Railway deployment config
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
└── README.md            # This file
```

🔧 API Endpoints

Product Analysis (for investment & price)

```
POST /api/analyze/products
{
  "client_id": "unique_client_id",
  "products": [
    {
      "title": "Product Name",
      "price": 99.99,
      "description": "Product details..."
    }
  ],
  "priority": "normal"
}
```

Keyword Analysis (for product descriptions)

```
POST /api/analyze/keyword
{
  "client_id": "unique_client_id",
  "keyword": "wireless headphones",
  "max_products": 50
}
```

Check Status

```
GET /api/status/{task_id}
```

Queue Statistics

```
GET /api/queue/stats
```

Health Check

```
GET /health
```

🚀 Deployment on Railway

1. Push to GitHub

```bash
git add .
git commit -m "Deploy Amazon AI Agent"
git push origin main
```

2. Add on Railway

1. Create new Railway project
2. Connect GitHub repository
3. Add services:
   · PostgreSQL (for long-term memory)
   · Redis (for task queue)

3. Environment Variables (in Railway Dashboard)

```env
# Required:
DEEPSEEK_API_KEY=your_deepseek_api_key
APIFY_TOKEN=your_apify_token
MAKE_WEBHOOK_URL=https://hook.make.com/your-webhook
MAKE_API_KEY=your_make_api_key

# Auto-added by Railway:
DATABASE_URL=postgresql://...
REDIS_URL=redis://...

# Optional:
LOG_LEVEL=INFO
PORT=8000
```

🛠️ Local Development

1. Clone and Setup

```bash
git clone https://github.com/yourusername/amazon_ai_queue.git
cd amazon_ai_queue
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. Environment Setup

```bash
cp .env.example .env
# Edit .env with your actual API keys
```

3. Run Locally

```bash
uvicorn app.main:app --reload --port 8000
```

Visit: http://localhost:8000/docs for API documentation

🔌 Make.com Setup

1. Google Forms Connection

1. Create Google Form with fields:
   · investment_amount (number)
   · price_range (text)
   · product_description (text)
   · client_email (email)

2. Make.com Scenario

```
Google Forms (Trigger)
    ↓
Router (Decision)
    ├── If investment & price → HTTP (Product Analysis)
    └── If description → HTTP (Keyword Analysis)
    ↓
Your Agent API (https://amazonaiqueue-production.up.railway.app)
    ↓
HTTP Response → Google Sheets/Email
```

3. Webhook Configuration

· Product Analysis: POST /api/analyze/products
· Keyword Analysis: POST /api/analyze/keyword
· Callback URL: Your Make.com webhook for results

📊 Features in Detail

AI Analysis

· DeepSeek AI for market insights
· Investment risk assessment
· Profit margin calculations
· Competitive analysis

Memory System

· Short-term: Redis (24-hour cache)
· Long-term: PostgreSQL (permanent storage)
· Client history tracking
· Personalized recommendations

Queue Management

· Priority-based task processing
· Background job processing
· Progress tracking
· Error handling and retries

🐛 Troubleshooting

Common Issues:

1. Deployment fails: Check Railway logs for missing dependencies
2. API keys not working: Verify in Railway Variables
3. Database connection: Ensure PostgreSQL/Redis are added in Railway
4. Make.com webhook: Test with Postman first

Logs Location:

· Railway Dashboard → Logs tab
· Filter by service, severity, or deployment

📈 Monitoring

Health Check

```
GET /health
```

Returns: Redis status, queue size, database connection

Queue Statistics

```
GET /api/queue/stats
```

Returns: Active tasks, completed tasks, queue size

🔒 Security Notes

· Never commit .env file to GitHub
· Use Railway Variables for production keys
· All API keys stored encrypted in Railway
· PostgreSQL and Redis secured by Railway

📞 Support

For issues:

1. Check Railway deployment logs
2. Verify environment variables
3. Test API endpoints with Postman
4. Review Make.com scenario routing

📄 License

MIT License - See LICENSE file for details

---

🎯 Quick Start Summary

1. Deploy → Push to GitHub, connect Railway
2. Configure → Add API keys in Railway Variables
3. Connect → Setup Make.com with Google Forms
4. Test → Submit form, check results in Sheets/Email

Your Amazon AI Agent is ready to analyze investments and find profitable products! 🚀

---

Copy this to README.md and your project documentation is complete! ✅