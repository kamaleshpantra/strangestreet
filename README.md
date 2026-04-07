# Strange Street

A production-ready social networking platform built with FastAPI, PostgreSQL, and Machine Learning.

## Features
- **Semantic Search**: Powered by `all-MiniLM-L6-v2`.
- **Cloud Storage**: Integrated with Cloudinary for media persistence.
- **Scalability**: PostgreSQL with connection pooling.
- **Observability**: Structured JSON logging.

## Infrastructure
- **Hosting**: Render (Web Service + Cron Job).
- **Database**: PostgreSQL (Render managed or Neon Serverless).
- **Media**: Cloudinary.

## Deployment
Push to your connected Git repo — Render auto-deploys via `render.yaml`.

```bash
git push origin main
```
