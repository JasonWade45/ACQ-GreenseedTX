---
title: Acquisitions Assistant
emoji: 🏠
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Acquisitions Assistant — Hugging Face Space

This README is the Space configuration file. It is copied over the repository
README when publishing to Hugging Face; the full application documentation stays in
the GitHub repository.

- Docker Space, CPU Basic (2 vCPU / 16 GB), free and no credit card.
- The database must be an external PostgreSQL (Neon free tier) because a free Space
  has an ephemeral disk.
- Set the app password and secrets in **Settings → Variables and secrets**:
  `APP_ACCESS_PASSWORD`, `DATABASE_URL`, `SESSION_SECRET`, `APP_TIMEZONE`,
  `PORT=7860`, `RESIMPLI_MODE=disabled`, `SYNC_ENABLED=false`,
  `CRM_WRITES_ENABLED=false`.
- The application URL is `https://<owner>-<space>.hf.space`.
- Free public Spaces sleep after 48 hours without traffic; the first request after
  that takes about 30 seconds.

Full Arabic steps: `deploy/huggingface/PUBLISH_AR.md` in the GitHub repository.
