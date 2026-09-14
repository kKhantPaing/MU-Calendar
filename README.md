# MU Calendar

A Streamlit-based AI assistant powered by Google Gemini, tailored for Mahidol University Faculty of ICT students. The assistant integrates course syllabus schedules, Moodle calendar exports, and manual schedule updates with highest priority.

## Features

- **Course Schedules & Syllabus Integration**: Loads week-by-week lecture topics, delivery modes, and exam dates for courses (`ITCS503`, `ITCS509`, `ITCS514`, `ITCS525`, `ITCS544`).
- **Moodle Calendar Sync**: Fetches real-time deadlines, make-up classes, and cancellations directly from Moodle `.ics` calendar feeds.
- **Highest Priority Manual Overrides (`CustomUpdate.json`)**: Allows students to manually override class topics, delivery modes, and schedules with highest priority. Overrides take precedence over conflicting syllabus or Moodle calendar entries.
- **Instant Hot-Reload**: Automatically invalidates cache and refreshes context when `CustomUpdate.json` is updated.
- **Automated Validation CI**: GitHub Action checks `CustomUpdate.json` format, date formats (`YYYY-MM-DD`), and time ranges (`HH:MM`) on every push or pull request.

---

## Setup & Configuration

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Secrets

Create a `.streamlit/secrets.toml` file with your Gemini API key and calendar export URL:

```toml
gemini_api_key = "YOUR_GEMINI_API_KEY"
calendar_export_url = "YOUR_MOODLE_ICS_CALENDAR_URL"
```

### 3. Run Application

```bash
streamlit run app.py
```

---

## Manual Schedule Overrides (`CustomUpdate.json`)

To manually update or override a class session, edit `CustomUpdate.json`:

```json
[
  {
    "date": "2026-09-13",
    "course": "ITCS503",
    "type": "Lecture",
    "delivery_mode": "Hybrid (Boonsit)",
    "start_time": "09:00",
    "end_time": "12:00"
  }
]
```

### Validating JSON Locally

You can run the validator script at any time to verify `CustomUpdate.json`:

```bash
python scripts/validate_custom_update.py
```
