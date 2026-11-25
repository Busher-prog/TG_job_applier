# AI Job Copilot

Telegram bot that walks a job seeker through the whole process: create or upload a CV, improve it,
pick target roles, find real vacancies, check the match, find the official way to apply, write a
personalised cover letter, send it from the user's own Gmail after explicit confirmation, and track
the results.

Modular monolith: **Python 3.12 · aiogram 3 · FastAPI · PostgreSQL · SQLAlchemy 2 · Alembic · Redis ·
Celery · Pydantic · OpenAI / Gemini · WeasyPrint · python-docx · S3-compatible storage · Docker**.

---

## Implementation status

| Phase | Scope | Status |
|---|---|---|
| 1. Bot foundation | bot, DB, migrations, localisation (en/uk/ru/de), welcome, language, consent, 4 CV scenarios entry, PDF/DOCX upload, OCR, AI CV parsing, profile confirmation & editing, main menu, My CVs, settings, GDPR export/delete | ✅ done, tested |
| 2. CV Builder | adaptive interview, AI content generation, dynamic section order, 3 templates, PDF/DOCX, preview, NL editing, CV optimizer, version history, CV examples | ✅ done, tested |
| 3. Job engine | sources, normalisation, hard filters, matching, feed, saved jobs | ⏳ next |
| 4. Application engine | contacts, cover letters, tailoring, Gmail OAuth/API, tracker | planned |
| 5. Commercial | Telegram Stars payments, subscriptions, credits, scheduler, notifications, admin | planned |

All four CV scenarios (upload, create with AI, improve, examples) work. Menu sections of later
phases (jobs, applications, subscription…) answer “coming soon”.

### What was verified in this repository

* `pytest`: **99 tests pass** (unit + integration against a real PostgreSQL 16):
  * file validation (format by magic bytes, size, legacy `.doc`, encrypted/corrupted files, zip bombs);
  * text extraction from PDF (incl. embedded hyperlinks, Cyrillic) and DOCX (incl. headers and tables);
  * **real OCR** of an image-only PDF with Tesseract;
  * CV parsing, grounding (contacts the model invents are dropped), experience calculation;
  * the full Phase 1 conversation driven through the real aiogram `Dispatcher`, handlers, middlewares
    and database with a fake Telegram API (welcome → language → consent gate → consent → resume options →
    upload → profile summary → edit → leave to menu → continue → confirm), My CVs (download/delete),
    settings (independent UI/CV/letter languages), GDPR export and account deletion;
  * **CV Builder end-to-end** through the bot: multi-fact answers (name + email + phone in one message
    are not asked again), only missing experience details are asked, profession-specific questions,
    skill suggestions with multi-select, languages, CV language, design → generated PDF; then the five
    natural-language edits from the spec, design/language buttons, DOCX download, version restore,
    confirmation; interrupted interview resumes after leaving to the menu;
  * CV Optimizer flow (report with indicative ATS score → clarifying questions → improved CV) and
    CV examples (3 previews + PDFs → “create similar”);
  * fact protection: invented numbers, skills and employers from the model are dropped; dates,
    companies, titles and institutions always come from the facts; career changers keep all
    employers (irrelevant ones move to “Additional experience”);
  * rendering: all 3 templates × Latin/Cyrillic → A4, selectable text, correct reading order,
    clickable links, automatic check that every essential fact is present in the PDF text,
    page-limit compaction, HTML escaping of user content, DOCX output;
  * per-user data isolation (another user cannot download your CV by id);
  * Alembic `upgrade head` → `alembic check` (no drift vs. models) → `downgrade base` → `upgrade head`;
  * locale files: identical keys, identical placeholders, balanced HTML tags.
* **Not verified here:** a live Telegram bot token, OpenAI / Gemini calls (no API keys in this
  environment — the code paths are implemented, tests use the explicit `MOCK_MODE` provider),
  S3/MinIO, and `docker build` (the sandbox could not reach Debian apt mirrors). `docker compose config`
  validates.

---

## Quick start (Docker)

```bash
cp .env.example .env          # fill TELEGRAM_BOT_TOKEN, OPENAI_API_KEY (or GEMINI_API_KEY), ENCRYPTION_KEY
docker compose up -d --build  # postgres, redis, migrate (alembic upgrade head), bot, api
docker compose logs -f bot
```

Use `STORAGE_BACKEND=local` for a single-server setup, or start MinIO with
`docker compose --profile s3 up -d` and set `STORAGE_BACKEND=s3`.

## Local development

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
# system packages: libpango-1.0-0 libpangoft2-1.0-0 (WeasyPrint), tesseract-ocr + language packs (OCR)
export DATABASE_URL=postgresql+asyncpg://copilot:copilot@localhost:5432/copilot
alembic upgrade head
python -m app.main bot        # Telegram bot (long polling)
python -m app.main api        # FastAPI on :8000 (health, /privacy, /terms, webhook, OAuth)
python -m app.main all        # both (required for BOT_MODE=webhook)
```

Development without an AI key: set `MOCK_MODE=true`. The mock provider never invents data — the CV
parser falls back to deterministic extraction from the document. `MOCK_MODE` is **rejected at startup
when `APP_ENV=production`**.

### Tests

```bash
createdb copilot_test   # or set TEST_DATABASE_URL
pytest -q
```

---

## External services and keys

| Variable | Where to get it | Needed for |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` | everything |
| `OPENAI_API_KEY` | platform.openai.com → API keys (paid usage) | CV parsing, generation, voice transcription |
| `GEMINI_API_KEY` | aistudio.google.com → Get API key | alternative AI provider (`AI_PROVIDER=gemini`) |
| `ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | encrypting OAuth tokens |
| `GOOGLE_CLIENT_ID/SECRET` | Google Cloud Console → OAuth consent screen + OAuth client (Web). `gmail.send` is a *sensitive* scope: Google verification is required before going public | Phase 4 |
| `S3_*` | any S3-compatible provider or the bundled MinIO | file storage in production |
| `APP_BASE_URL` | your HTTPS domain (reverse proxy such as Caddy/Traefik/nginx in front of `api:8000`) | legal pages, OAuth callback, webhook |

---

## Architecture

```
app/
├── bot/            aiogram: handlers/, keyboards/, middlewares/, states/, factory.py, utils.py
├── api/            FastAPI: health, legal pages, Telegram webhook (OAuth in Phase 4)
├── services/       business logic (cv/, users/, ai/, i18n.py …) — no Telegram types here
├── providers/      integrations: llm/ (OpenAI, Gemini, Mock), storage/ (local, S3)
├── database/       models/ (26 tables), repositories/, session.py
├── schemas/        Pydantic schemas = JSON Schemas for AI agents (validated before saving)
├── prompts/        one system prompt per AI agent (*.md)
├── locales/        en.json, uk.json, ru.json, de.json — all UI text
├── templates/      CV templates classic_ats/ modern/ creative/ (Jinja2 + CSS), legal/ pages
├── workers/        Celery tasks (Phase 3+)
├── config.py       settings from environment
└── main.py         entry point: bot | api | all
migrations/         Alembic (0001 schema, 0002 seed of resume templates)
examples/           fictional example CVs: *.json → *.pdf, *.docx, *.png (python -m scripts.build_examples)
tests/              unit/ and integration/ (real PostgreSQL, real Dispatcher)
```

### Key design decisions

* **AI never acts.** Every agent returns JSON validated by a Pydantic model
  (`LLMProvider.generate_json`, one automatic retry on schema errors). Backend services decide what
  to store or do. Sending email, payments and deletion are never triggered by model output.
* **Prompt-injection defence.** CV text, job postings, websites and emails are wrapped in
  `<untrusted_data>` blocks; every system prompt states they are data, not instructions; the wrapper
  cannot be closed from inside the content.
* **CV generation pipeline.** `facts (profile) → Structure Planner (AI, rule-based fallback) →
  Content Generator (AI, text only) → deterministic assembly → renderer → PDF verification`.
  The model never returns dates, employers, titles or institutions; they are merged from the facts.
  Generated bullets/summary containing numbers that are not in the facts are replaced by the
  original wording; skills not present in the facts are dropped. A document whose PDF text lost an
  essential fact is not handed out.
* **Every CV change is a new version** (`resume_versions`, PDF + DOCX in storage); any version can be
  restored. Structure/design changes re-render without calling the AI; wording changes regenerate.
* **No invented facts.** After parsing, `ground_parsed_cv` removes emails, phones and URLs that do not
  literally appear in the document and recomputes total experience from dates (overlaps merged).
  Language levels default to `Unknown` unless stated.
* **Progress is never lost.** The onboarding step is stored on the user record; FSM state lives in
  Redis. Any slash command interrupts pending input without losing progress; “Continue setup”
  resumes at the saved step.
* **Consent gate.** Features processing personal data are behind `ConsentRequiredMiddleware`
  (versioned consent records; a new policy version requires re-consent).
* **Data isolation.** Repository queries are always scoped by `user_id`.
* **Logs without personal data.** A redacting log filter masks emails, phones and tokens; handlers log
  exception *types* only; audit-log metadata never contains CV content.

### Database

`users, consent_records, candidate_profiles, work_experiences, education_records, candidate_skills,
candidate_languages, portfolios, resumes, resume_versions, resume_templates, search_preferences,
job_sources, job_listings, job_matches, recruiter_contacts, saved_jobs, cover_letters, applications,
email_connections, subscriptions, credit_transactions, payments, notification_preferences,
audit_logs` + `app_settings` (admin-editable settings). Foreign keys with explicit `ON DELETE`,
unique constraints (e.g. one match per user/vacancy, idempotency keys for applications and credit
transactions), indexes on hot paths.

---

## Privacy & GDPR

* Privacy Policy and Terms are served at `/privacy` and `/terms` (`app/templates/legal/`).
  **They are templates — the operator must fill in controller details and get legal review.**
* Users can export all data (JSON) and delete their account (cascade + file storage wipe) from
  *Settings → Privacy & data*; individual CVs can be deleted from *My CVs*.
* Backups: use managed PostgreSQL point-in-time recovery or scheduled `pg_dump`, and bucket
  versioning for S3. Deleted accounts must also expire from backups within the retention window.

### AI agents (`app/prompts/`)

| Agent | Prompt | Used for | Fallback without AI |
|---|---|---|---|
| CV Parser | `cv_parser.md` | uploaded CV → structured facts | rule-based extraction |
| Adaptive Interview Agent | `interview_agent.md`, `interview_questions.md`, `skill_suggester.md` | extracting facts from free answers, profession questions, skill suggestions | rule-based extraction, localised question bank |
| CV Structure Planner | `cv_structure_planner.md` | profile type, section order, relevant vs additional experience, template | rule-based planner |
| CV Content Generator | `cv_content_generator.md` | summary, bullets, grouping of skills | facts verbatim |
| CV Optimizer | `cv_optimizer.md` | qualitative review + clarifying questions (score is rule-based) | rule-based findings |
| User Intent Interpreter | `user_intent_interpreter.md` | NL edit request → edit operations | keyword rules (en/de/uk/ru) |

Job Description Parser, Job Matching, Contact Verification, Cover Letter and CV Tailoring agents come
with Phases 3–4.

## Known limitations / open items

* Phases 2–5 are not implemented yet (see status table).
* Only English legal pages exist; other languages fall back to English.
* Voice transcription requires OpenAI or Gemini (not available in `MOCK_MODE`).
* AI prompts were exercised only through the schema/validation layer and the offline mock — quality
  of real model output must be reviewed with a live key before launch.
* Section headings are localised for en/de/uk/ru; a CV in another language uses English headings.
* The ATS score is an indicative rule-based estimate, explicitly labelled as such in the bot.
