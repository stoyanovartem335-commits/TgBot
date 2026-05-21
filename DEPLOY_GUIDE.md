# Deployment Guide — Таблица Калывана

## 1. GitHub Setup

Create 3 separate repositories:

```bash
cd tg-bot
git init && git add . && git commit -m "init"
gh repo create kalivan-tg-bot --public --source=. --remote=origin
git push -u origin main

cd ../api-server
git init && git add . && git commit -m "init"
gh repo create kalivan-api-server --public --source=. --remote=origin
git push -u origin main
```

## 2. MongoDB Atlas Setup

1. Go to mongodb.com/cloud/atlas
2. Create a free cluster (M0)
3. Create a database user with read/write access
4. Whitelist 0.0.0.0/0 (or Render IP ranges)
5. Get connection string:
   `mongodb+srv://username:password@cluster0.xxxxx.mongodb.net/Connect?retryWrites=true&w=majority`
6. The database name must be `Connect`

## 3. Render.com Deployment

### Deploy API Server First

1. Go to render.com → New Web Service
2. Connect `kalivan-api-server` repo
3. Settings:
   - Name: `kalivan-api-server`
   - Runtime: Node
   - Build Command: `npm install`
   - Start Command: `node server.js`
4. Environment Variables:
   - MONGO_URI
   - ADMIN_TOKEN
   - PORT=10000
   - TABLE_CSV_URL, ANALOGUES_CSV_URL, CARS_CSV_URL

### Deploy Telegram Bot

1. New Web Service → Connect `kalivan-tg-bot` repo
2. Settings:
   - Name: `kalivan-telegram-bot`
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python -m bot.main`
3. Environment Variables (see .env.example)

## 4. Webhook Setup

### Triboote Webhook
1. In Triboote dashboard, set webhook URL to:
   `https://YOUR-BOT-SERVICE.onrender.com/triboote/webhook`
2. Set success URL to:
   `https://YOUR-BOT-SERVICE.onrender.com/triboote/success`

## 5. Health Checks
- API Server: GET /api/health
- Bot: GET /health

## 6. Verification Checklist
- [ ] API server responds at /api/health
- [ ] Bot responds to /start
- [ ] WebApp opens from Telegram
- [ ] Stars payment works
- [ ] Token generated and sent
- [ ] ZIP archive sent
- [ ] /adm works for admin only
- [ ] Prices changeable via admin