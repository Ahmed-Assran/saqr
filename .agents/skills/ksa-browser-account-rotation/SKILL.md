---
name: ksa-browser-account-rotation
description: Manages Playwright stealth browser contexts, ar-SA/Asia-Riyadh locale spoofing, multi-account rotation, residential proxy binding, human jitter, circuit breakers, and atomic checkpoint recovery.
---

# KSA Browser Account Rotation Skill

## Purpose
Governs browser instance creation, session persistence, account cooldowns, and anti-detection measures when scraping social platforms (X.com and TikTok) for Saudi and GCC retail investors.

## Operating Principles
1. **Locale & Timezone Spoofing**:
   - Always set `locale = "ar-SA"`.
   - Set `timezone_id = "Asia/Riyadh"`.
   - Emulate realistic geolocation coordinates (Riyadh: lat 24.7136, lng 46.6753).
2. **Stealth Script Injections**:
   - Mask `navigator.webdriver` to `undefined`.
   - Mock Chrome runtime object and plugins.
   - Override WebGL renderer vendor strings to emulate standard Intel/Apple/Nvidia consumer GPUs.
3. **Bandwidth & Request Optimization**:
   - Intercept and abort resource types `image`, `media`, `font`, `stylesheet` to minimize proxy data consumption and maximize page load speeds.
   - Allow all document, script, and `xhr`/`fetch` requests necessary for GraphQL/REST responses.
4. **Account State Machine**:
   - Accounts cycle through: `active`, `cooldown`, `challenged`, `banned`.
   - Enforce hard rotation threshold: maximum 20 requests per active window.
   - Cool down accounts for 45 minutes after reaching the request ceiling.
   - Circuit breaker: Upon detecting HTTP 429 (Too Many Requests), HTTP 403 (Forbidden), Arkose challenge, or captcha redirect, immediately mark the account `cooldown` (60 mins) or `challenged` and switch to the next healthy account.
5. **Humanized Interaction**:
   - Apply randomized delays: 3.5 to 8.2 seconds between queries or scroll steps.
   - Inject human jitter: 15% probability of upward scroll (-150px) to simulate realistic reading behavior.
6. **Atomic Checkpointing**:
   - Persist query index, account states, and timestamps to `data/checkpoints/progress.json`.
   - Support seamless `--resume` execution without repeating completed targets.
