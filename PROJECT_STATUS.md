# Project Status — Таблица Калывана

## Architecture Overview

The project consists of **3 separate services** designed for independent deployment on Render.com:

### 1. Telegram Bot (	g-bot/)
- Python 3.12 + aiogram 3.x
- Serves WebApp static files via aiohttp
- Handles all payment flows (Stars, Triboote, requisites)
- Generates tokens via API server after payment
- Sends ZIP archive + token to user
- Admin panel via /adm command
- MongoDB for persistence (users, purchases, settings)

### 2. WebApp (	g-webapp/ or served from 	g-bot/webapp/)
- Pure HTML/CSS/JS (no build step)
- Premium dark green/black glassmorphism design
- Telegram WebApp API integration
- Fetches plans from /api/plans endpoint
- Animated scroll effects, responsive mobile-first

### 3. API Server (pi-server/)
- Node.js + Express
- MongoDB: loader_keys, 	able, Admin_Key, AnaloguesAks, Cars, 	able_free, AveragePrice, MarketPlace, CfgTokens
- Token authentication (/api/checkToken)
- HWID binding
- Subscription expiration (DD.MM.YYYY format)
- Lua script compatibility preserved
- New endpoint: /api/CreateSubscriptionToken (for bot)
- Health check: /api/health

## What Was Completed

- [x] Replaced SQLite with MongoDB in bot
- [x] Replaced tokens.txt with API server token generation
- [x] Integrated bot → API server → MongoDB token flow
- [x] ZIP archive delivery after purchase
- [x] Redesigned WebApp with premium dark theme
- [x] Advanced admin panel (/adm) with inline keyboards
- [x] Settings stored in MongoDB (prices, discounts, highlighted tariff)
- [x] All sensitive data in .env
- [x] Render deployment files for all 3 services
- [x] Health check endpoints
- [x] Triboote setup preserved + documentation
- [x] All existing API logic preserved
- [x] Russian language throughout

## Current Status

**READY FOR DEPLOYMENT** after:
1. Creating GitHub repositories
2. Setting up environment variables
3. Connecting MongoDB Atlas
4. Configuring webhooks

## Important Notes

- The API server's erifyAdmin() now checks BOTH ADMIN_TOKEN env var AND the MongoDB Admin_Key collection for backward compatibility
- Token expiration uses DD.MM.YYYY format (matching Lua script expectations)
- Forever tariff stores subscription_expiration: null
- Settings collection auto-creates with defaults on first run
- ZIP file path configurable via ZIP_FILE_PATH env var

## Project Structure

`
tg-bot/                    # Telegram Bot repo
  bot/
    config.py              # Environment config
    database.py            # MongoDB models
    keyboards.py           # All keyboard layouts
    main.py                # Entrypoint
    webhook_server.py      # aiohttp: WebApp + webhooks + health
    handlers/
      start.py             # /start
      menu.py              # Reply buttons
      webapp.py            # WebApp data receiver
      stars.py             # Stars payment
      triboote.py          # Triboote payment
      requisites.py        # Manual payment
      admin.py             # /adm panel
      gsheets.py           # Google Sheets request
    services/
      api_client.py        # HTTP → API server
      token_service.py     # Token generation
      delivery.py          # Post-purchase delivery
      triboote_api.py      # Triboote API client
      settings_service.py  # MongoDB settings
  webapp/
    index.html             # Redesigned WebApp
    style.css              # Premium dark theme
    script.js              # Animations + Telegram API
  .env.example
  requirements.txt
  render.yaml
  Dockerfile

api-server/                # API Server repo
  server.js                # Express API (preserved + enhanced)
  package.json
  render.yaml
  .env.example

tg-webapp/                 # Optional standalone WebApp repo
  (same files as tg-bot/webapp/)
`

## Future Recommendations

- Add rate limiting to API server
- Implement webhook retry logic for Triboote
- Add analytics dashboard to admin panel
- Consider caching settings in bot memory with periodic refresh
- Add unit tests for payment flows
