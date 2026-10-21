---
name: web-scraping
description: Web scraping pipeline and checkpointing skill for resilient data collection and progress recovery.
---

# Web Scraping Skill

Handles web scraping pipelines with:
- Proxy rotation and user-agent management.
- Request rate limiting and circuit breakers.
- Checkpoint persistence and `--resume` support.
- JSONL raw data staging.
