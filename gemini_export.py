import requests as req
import re
from datetime import datetime, timezone, timedelta
import pandas as pd
import streamlit as st

def get_calendar_export(url=None) -> dict:
    """
    Fetches, parses, and returns the cleaned Mahidol University ICT calendar data 
    as a dictionary ready for Gemini context, without writing to disk.
    """
    if not url:
        try:
            if "calendar_export_url" in st.secrets:
                url = st.secrets["calendar_export_url"]
            elif "CALENDAR_EXPORT_URL" in st.secrets:
                url = st.secrets["CALENDAR_EXPORT_URL"]
        except Exception:
            pass

    # 1. Fetch calendar data (.ics format)
    response = req.get(url)
    response.raise_for_status()
    calendar_text = response.text

    # 2. Unfold RFC 5545 folded lines (continuation lines starting with space or tab)
    unfolded_text = re.sub(r'\r?\n[ \t]', '', calendar_text)

    # 3. Set ICT timezone (UTC+7)
    tz_ict = timezone(timedelta(hours=7))

    def parse_ics_dt(dt_str):
        if not dt_str:
            return None
        if dt_str.endswith('Z'):
            return datetime.strptime(dt_str, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).astimezone(tz_ict)
        return datetime.strptime(dt_str, '%Y%m%dT%H%M%S')

    # 4. Parse VEVENT blocks
    events = []
    for block in re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', unfolded_text, re.DOTALL):
        def get_field(name):
            m = re.search(rf'^{name}(?:;[^:]*)?:(.*)$', block, re.MULTILINE)
            return m.group(1).strip() if m else ''
        
        start_dt = parse_ics_dt(get_field('DTSTART'))
        end_dt = parse_ics_dt(get_field('DTEND'))
        summary = get_field('SUMMARY')
        course = get_field('CATEGORIES')
        desc = get_field('DESCRIPTION').replace('\\n', '\n').replace('\\,', ',').replace('\\;', ';')
        
        # Categorize type
        if '[Cancel]' in summary:
            event_type = 'Cancelled'
        elif '[Make-up]' in summary:
            event_type = 'Make-up'
        elif 'due' in summary.lower():
            event_type = 'Deadline'
        else:
            event_type = 'General'
        
        if end_dt and end_dt < datetime.now(tz_ict):
            continue  # Skip past events
        
        events.append({
            'Course': course,
            'Type': event_type,
            'Summary': summary,
            'Start (ICT)': start_dt.strftime('%Y-%m-%d %H:%M') if start_dt else 'N/A',
            'End (ICT)': end_dt.strftime('%Y-%m-%d %H:%M') if end_dt else 'N/A',
            'Description': desc,
            '_dt': start_dt,
            '_end_dt': end_dt
        })

    # 5. Create DataFrames for structure
    df_events = pd.DataFrame(events).sort_values(by='_dt').reset_index(drop=True) if events else pd.DataFrame()

    df_deadlines = df_events[df_events['Type'] == 'Deadline'][['Course', 'Summary', 'Start (ICT)', 'Description']].reset_index(drop=True) if not df_events.empty else pd.DataFrame()
    df_changes = df_events[df_events['Type'].isin(['Cancelled', 'Make-up'])][['Course', 'Type', 'Summary', 'Start (ICT)', 'End (ICT)', 'Description']].reset_index(drop=True) if not df_events.empty else pd.DataFrame()

    # Generate Gemini-Ready Export & Conflict-Free Calendar Export dict
    gemini_export = {
        'metadata': {
            'source': 'Mahidol University ICT Moodle Calendar',
            'timezone': 'Asia/Bangkok (UTC+7)',
            'exported_at': datetime.now(tz_ict).isoformat()
        },
        'deadlines': [],
        'class_schedule_adjustments': [],
        'google_calendar_ready_events': []
    }

    for _, row in df_deadlines.iterrows():
        gemini_export['deadlines'].append({
            'course': row['Course'],
            'title': row['Summary'],
            'due_datetime': row['Start (ICT)'],
            'details': row['Description']
        })

    for _, row in df_changes.iterrows():
        gemini_export['class_schedule_adjustments'].append({
            'course': row['Course'],
            'type': row['Type'],
            'summary': row['Summary'],
            'start': row['Start (ICT)'],
            'end': row['End (ICT)'],
            'details': row['Description']
        })

    # Google Calendar events (All-day for deadlines to prevent 23:59 collisions; precise blocks for make-ups)
    for e in events:
        if e['Type'] == 'Deadline' and e['_dt']:
            dt_str = e['_dt'].strftime('%Y-%m-%d')
            gemini_export['google_calendar_ready_events'].append({
                'summary': f"[{e['Course']}] {e['Summary']}",
                'start': {'date': dt_str},
                'end': {'date': dt_str},
                'description': e['Description']
            })
        elif e['Type'] == 'Make-up' and e['_dt']:
            gemini_export['google_calendar_ready_events'].append({
                'summary': f"[{e['Course']}] {e['Summary']}",
                'start': {'dateTime': e['_dt'].isoformat(), 'timeZone': 'Asia/Bangkok'},
                'end': {'dateTime': e['_end_dt'].isoformat() if e['_end_dt'] else e['_dt'].isoformat(), 'timeZone': 'Asia/Bangkok'},
                'description': e['Description']
            })

    return gemini_export

if __name__ == "__main__":
    data = get_calendar_export()
    print(f"Retrieved {len(data['deadlines'])} deadlines and {len(data['class_schedule_adjustments'])} adjustments.")
