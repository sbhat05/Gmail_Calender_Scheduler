import base64
import json
import re
from datetime import datetime, timedelta
from dateutil import parser
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.cloud import pubsub_v1
import os
from dotenv import load_dotenv
load_dotenv()
# ---------------- CONFIG ----------------
PROJECT_ID = os.getenv("PROJECT_ID")
TOPIC_NAME = os.getenv("TOPIC_NAME", "gmail-push-topic")
SUBSCRIPTION_ID = os.getenv("SUBSCRIPTION_ID", "gmail-push-topic-sub")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/pubsub"  # Add Pub/Sub scope
]
CLIENT_SECRET_FILE = os.getenv("CLIENT_SECRET_FILE", "client_secret.json")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

# Set Google Application Credentials for Pub/Sub
credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service-account-key.json")
if os.path.exists(credentials_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
else:
    print(f"⚠️  Warning: Service account key not found at {credentials_path}")
    print("   Pub/Sub authentication may fail!")

# Validate required environment variables
if not PROJECT_ID:
    print("❌ ERROR: PROJECT_ID not set in .env file!")
    print("   Please copy .env.example to .env and configure it.")
    exit(1)

# Try to import transformers for AI (optional)
try:
    from transformers import pipeline
    import warnings
    warnings.filterwarnings('ignore', category=UserWarning, module='transformers')
    
    print("📦 Loading AI model (Flan-T5-small)...")
    # Using Google's Flan-T5-small: 80MB, fast, accurate for extraction
    event_extractor = pipeline(
        "text2text-generation",
        model="google/flan-t5-small",
        device=-1  # CPU (use device=0 for GPU)
    )
    AI_AVAILABLE = True
    print("✅ AI model loaded successfully\n")
except ImportError:
    print("⚠️  Transformers not installed. Install with: pip install transformers torch")
    print("   Running in regex-only mode...\n")
    AI_AVAILABLE = False
except Exception as e:
    print(f"⚠️  AI model loading failed: {e}")
    print("   Running in regex-only mode...\n")
    AI_AVAILABLE = False
# ---------------------------------------

print("="*60)
print("🚀 GMAIL CALENDAR SCHEDULER STARTING")
print("="*60)
print(f"📅 Current date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"🌍 Timezone: {TIMEZONE}")
print(f"🤖 AI Mode: {'Flan-T5 (Local)' if AI_AVAILABLE else 'Regex-Only'}\n")

print("🔑 Authenticating with Google...")
flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
creds = flow.run_local_server(port=0)

gmail_service = build('gmail', 'v1', credentials=creds)
calendar_service = build('calendar', 'v3', credentials=creds)

# Use the same credentials for Pub/Sub
subscriber = pubsub_v1.SubscriberClient(credentials=creds)
subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
print("✅ Google authentication successful\n")

processed_ids = set()

# ---------------- HELPERS ----------------
def extract_event_with_ai(subject, body):
    """Use Flan-T5 to determine if email contains an event"""
    if not AI_AVAILABLE:
        return None
    
    try:
        # Simpler, more direct prompt
        prompt = f"""Does this email describe a scheduled event, meeting, or appointment?
Subject: {subject}
Body: {body[:200]}

Answer YES or NO:"""
        
        response = event_extractor(prompt, max_new_tokens=5, do_sample=False)[0]['generated_text']
        has_event = "yes" in response.lower()
        
        return {"has_event": has_event, "title": subject if has_event else None}
    except Exception as e:
        print(f"   ⚠️  AI extraction error: {e}")
        return None

def extract_event_details(subject, body):
    """
    Extract event details using regex + optional AI
    """
    print(f"\n{'─'*60}")
    print("🔍 EXTRACTING EVENT DETAILS")
    print(f"{'─'*60}")
    print(f"📧 Subject: {subject}")
    print(f"📝 Body length: {len(body)} chars")
    
    combined_text = subject + "\n" + body
    
    # Regex patterns for dates
    date_patterns = [
        r'\b(\d{1,2}(?:st|nd|rd|th)?\s+of\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)(?:\s+\d{4})?)\b',
        r'\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)(?:\s+\d{4})?)\b',
        r'\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b',
        r'\b(tomorrow|today)\b',
    ]
    time_patterns = [
        r'(?:at|@)\s+(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))',
        r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\b',
        r'\b(\d{1,2}\s*(?:AM|PM|am|pm))\b',
    ]

    date_found, time_found = None, None

    print("\n🔎 Regex extraction:")
    for pattern in date_patterns:
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if match:
            date_found = match.group(1) if match.lastindex else match.group()
            print(f"   ✅ Date found: {date_found}")
            break
    if not date_found:
        print(f"   ❌ No date found")

    for pattern in time_patterns:
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if match:
            time_found = match.group(1) if match.lastindex else match.group()
            print(f"   ✅ Time found: {time_found}")
            break
    if not time_found:
        print(f"   ❌ No time found")

    # Parse date/time with proper default
    parsed_date = None
    if date_found:
        # Handle relative dates
        if date_found.lower() == 'today':
            parsed_date = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        elif date_found.lower() == 'tomorrow':
            parsed_date = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            dt_text = date_found
            if time_found:
                dt_text += " " + time_found
            
            try:
                # Use a fixed default time of 9:00 AM instead of current time
                default_datetime = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
                parsed_date = parser.parse(dt_text, fuzzy=True, default=default_datetime)
                
                # Fix year if it's wrong
                if parsed_date.year < datetime.now().year - 1 or parsed_date.year > datetime.now().year + 1:
                    parsed_date = parsed_date.replace(year=datetime.now().year)
                
                # If no time was found in the text, ensure we're using default time
                if not time_found:
                    parsed_date = parsed_date.replace(hour=9, minute=0, second=0, microsecond=0)
                    print(f"   ℹ️  No time specified, using default: 9:00 AM")
                
                print(f"   ✅ Parsed datetime: {parsed_date.strftime('%Y-%m-%d %H:%M')}")
            except Exception as e:
                print(f"   ⚠️  Parse failed: {e}")

    # Call AI if available
    ai_result = None
    if AI_AVAILABLE:
        print("\n🤖 Calling AI for event classification...")
        ai_result = extract_event_with_ai(subject, body)
        if ai_result:
            print(f"   ✅ AI classification:")
            print(f"      has_event: {ai_result.get('has_event')}")
            if ai_result.get('has_event'):
                print(f"      title: {ai_result.get('title', subject)}")

    # Decision logic: Use a scoring system
    result = None
    confidence_score = 0
    
    # Score 1: AI says yes (+2 points)
    if ai_result and ai_result.get('has_event'):
        confidence_score += 2
    
    # Score 2: Regex found date/time (+2 points)
    if parsed_date:
        confidence_score += 2
    
    # Score 3: Subject has event keywords (+1 point)
    event_keywords = [
        'meeting', 'interview', 'call', 'tutorial', 'class', 'session',
        'appointment', 'scheduled', 'schedule', 'felicitation', 'event', 
        'conference', 'webinar', 'workshop', 'seminar', 'exam', 'test',
        'deadline', 'night', 'party', 'celebration', 'ceremony', 'prep',
        'training', 'orientation', 'hackathon', 'competition'
    ]
    
    subject_lower = subject.lower()
    body_lower = body[:300].lower()
    
    if any(keyword in subject_lower for keyword in event_keywords):
        confidence_score += 1
    
    # Score 4: Body has event keywords (+1 point)
    if any(keyword in body_lower for keyword in event_keywords):
        confidence_score += 1
    
    print(f"\n   📊 Confidence Score: {confidence_score}/6")
    
    # Decision: Need at least 2 points AND a date to create event
    if confidence_score >= 2 and parsed_date:
        # Check if date is in the past
        if parsed_date.date() < datetime.now().date():
            print(f"   ⏭️  SKIPPED: Event date is in the past ({parsed_date.date()})")
            return {"has_event": False}
        
        print(f"   ✅ Creating event (confidence threshold met)")
        result = {
            "has_event": True,
            "title": subject,
            "date": parsed_date.strftime("%Y-%m-%d"),
            "time": parsed_date.strftime("%H:%M"),
            "duration_minutes": 60,
            "location": None,
            "description": f"Confidence: {confidence_score}/6"
        }
    else:
        if not parsed_date:
            print(f"   ❌ No date/time found - cannot create event")
        else:
            print(f"   ❌ Confidence too low ({confidence_score}/6) - skipping")
        return {"has_event": False}
    
    if result:
        print(f"\n   ✅ Event will be created:")
        print(f"      title: {result['title']}")
        print(f"      date: {result['date']}")
        print(f"      time: {result['time']}")
    
    return result or {"has_event": False}

def create_calendar_event(summary, start_datetime):
    print(f"\n📅 Creating calendar event...")
    print(f"   Title: {summary}")
    print(f"   Start: {start_datetime.strftime('%Y-%m-%d %H:%M')}")
    print(f"   End: {(start_datetime + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')}")
    
    event = {
        'summary': summary,
        'start': {'dateTime': start_datetime.isoformat(), 'timeZone': TIMEZONE},
        'end': {'dateTime': (start_datetime + timedelta(hours=1)).isoformat(), 'timeZone': TIMEZONE},
    }
    try:
        created_event = calendar_service.events().insert(calendarId='primary', body=event).execute()
        print(f"   ✅ Event created successfully!")
        print(f"   📎 Event link: {created_event.get('htmlLink', 'N/A')}")
    except Exception as e:
        print(f"   ⚠️  Calendar error: {e}")

import base64
import json
import time

# ------------- IMPROVED PUBSUB DECODING -------------
def decode_pubsub_message(message):
    """Decode Gmail Pub/Sub message with multiple fallback strategies"""
    try:
        # Strategy 1: Direct decode (sometimes it's already correct)
        try:
            decoded = base64.b64decode(message.data).decode('utf-8')
            return json.loads(decoded)
        except Exception:
            pass
        
        # Strategy 2: URL-safe base64 decode
        try:
            decoded = base64.urlsafe_b64decode(message.data).decode('utf-8')
            return json.loads(decoded)
        except Exception:
            pass
        
        # Strategy 3: Add padding
        try:
            padded = message.data + b'=' * (-len(message.data) % 4)
            decoded = base64.b64decode(padded).decode('utf-8')
            return json.loads(decoded)
        except Exception:
            pass
        
        # Strategy 4: URL-safe with padding
        try:
            padded = message.data + b'=' * (-len(message.data) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode('utf-8')
            return json.loads(decoded)
        except Exception:
            pass
            
        print(f"   ⚠️  All decode strategies failed. Raw data: {message.data[:100]}")
        return None
        
    except Exception as e:
        print(f"   ⚠️  Pub/Sub decode error: {e}")
        return None

# ------------- CREDENTIAL REFRESH HELPER -------------
def refresh_gmail_service():
    """Refresh Gmail service if credentials expire"""
    global gmail_service
    try:
        # Test if service is still valid
        gmail_service.users().getProfile(userId='me').execute()
        return True
    except Exception as e:
        print(f"\n⚠️  Gmail service error: {e}")
        print("🔄 Attempting to refresh credentials...")
        try:
            # Re-authenticate
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            gmail_service = build('gmail', 'v1', credentials=creds)
            print("✅ Gmail service refreshed successfully")
            return True
        except Exception as refresh_error:
            print(f"❌ Failed to refresh: {refresh_error}")
            return False

# ------------- ROBUST CALLBACK WITH RETRY -------------
def callback(message):
    """Process Gmail notifications with retry logic"""
    max_retries = 3
    retry_delay = 2  # seconds
    
    try:
        print(f"\n{'='*60}")
        print(f"🔔 GMAIL NOTIFICATION RECEIVED")
        print(f"{'='*60}")
        print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        data = decode_pubsub_message(message)
        if data:
            print(f"📦 Notification data: {data}")
        else:
            print(f"📦 Notification received (data decode failed, proceeding anyway)")
        
        # Acknowledge message early to prevent redelivery
        message.ack()

        # Retry logic for fetching emails
        emails = None
        for attempt in range(max_retries):
            try:
                emails = fetch_unread_emails(limit=5)
                break  # Success!
            except Exception as e:
                print(f"   ⚠️  Fetch attempt {attempt + 1}/{max_retries} failed: {e}")
                
                if "SSL" in str(e) or "WRONG_VERSION_NUMBER" in str(e):
                    print(f"   🔄 SSL error detected, refreshing credentials...")
                    if refresh_gmail_service():
                        continue  # Retry with refreshed credentials
                
                if attempt < max_retries - 1:
                    print(f"   ⏳ Waiting {retry_delay}s before retry...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    print(f"   ❌ All retry attempts exhausted")
                    return
        
        if not emails:
            print("📭 No new emails to process")
            return

        for mail in emails:
            try:
                subject = mail['subject']
                body = mail['body']
                
                print(f"\n{'─'*60}")
                print(f"Processing: {subject[:50]}...")
                print(f"{'─'*60}")
                
                event_info = extract_event_details(subject, body)
                
                if event_info and isinstance(event_info, dict) and event_info.get("has_event"):
                    event_date_str = event_info.get("date")
                    event_time_str = event_info.get("time") or "09:00"
                    
                    print(f"\n✅ EVENT DETECTED!")
                    print(f"   📅 Date: {event_date_str}")
                    print(f"   ⏰ Time: {event_time_str}")
                    
                    try:
                        dt_str = f"{event_date_str} {event_time_str}"
                        default_datetime = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
                        event_time = parser.parse(dt_str, fuzzy=True, default=default_datetime)

                        # Skip past events
                        if event_time.date() < datetime.now().date():
                            print(f"   ⏭️  Skipping past event (date: {event_time.date()})")
                            continue

                        create_calendar_event(
                            summary=event_info.get("title", subject),
                            start_datetime=event_time
                        )
                    except Exception as e:
                        print(f"   ⚠️  Failed to create event: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print(f"\n❌ No event detected in: {subject[:50]}...")
                    
            except Exception as e:
                print(f"\n⚠️  Error processing email '{mail.get('subject', 'Unknown')[:50]}': {e}")
                import traceback
                traceback.print_exc()
                continue
                
    except Exception as e:
        print(f"\n⚠️  Critical error in callback: {e}")
        import traceback
        traceback.print_exc()

# ------------- ROBUST FETCH WITH RETRY -------------
def fetch_unread_emails(limit=5):
    """Fetch unread emails with retry on SSL errors"""
    print(f"\n{'─'*60}")
    print(f"📬 FETCHING UNREAD EMAILS (limit: {limit})")
    print(f"{'─'*60}")
    
    try:
        results = gmail_service.users().messages().list(
            userId='me', labelIds=['INBOX', 'UNREAD'], maxResults=limit
        ).execute()
        messages = results.get('messages', [])
        print(f"📊 Found {len(messages)} unread email(s)")
        
        emails = []
        for idx, msg in enumerate(messages, 1):
            if msg['id'] in processed_ids:
                print(f"   ⏭️  Email {idx}/{len(messages)}: Already processed (ID: {msg['id'][:8]}...)")
                continue
            
            print(f"\n{'─'*60}")
            print(f"📧 EMAIL {idx}/{len(messages)}")
            print(f"{'─'*60}")
            print(f"🆔 Message ID: {msg['id']}")
            
            msg_data = gmail_service.users().messages().get(userId='me', id=msg['id']).execute()

            # Get full body
            body = ''
            parts = msg_data['payload'].get('parts', [])
            for part in parts:
                if part.get('mimeType') == 'text/plain' and 'data' in part['body']:
                    body += base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')

            if not body:
                body = msg_data.get('snippet', '')
                print(f"⚠️  No body found, using snippet")

            # Get subject
            subject = next(
                (h['value'] for h in msg_data['payload']['headers'] if h['name'] == 'Subject'),
                'No Subject'
            )
            print(f"📧 Subject: {subject}")
            print(f"📝 Body preview: {body[:100]}...")

            emails.append({'id': msg['id'], 'subject': subject, 'body': body})
            processed_ids.add(msg['id'])
        
        if not emails:
            print("📭 No new emails to process")
        
        return emails
    except Exception as e:
        print(f"⚠️  fetch_unread_emails failed: {e}")
        raise  # Re-raise so caller can handle retry

# ---------------- MAIN ----------------
import threading

def extract_event_with_ai(subject, body):
    """Use Flan-T5 to determine if email contains an event (with timeout)"""
    if not AI_AVAILABLE:
        return None
    
    result_holder = {"data": None, "error": None, "completed": False}
    
    def run_ai():
        try:
            # Simpler, more direct prompt
            prompt = f"""Does this email describe a scheduled event, meeting, or appointment?
Subject: {subject}
Body: {body[:200]}

Answer YES or NO:"""
            
            response = event_extractor(prompt, max_new_tokens=5, do_sample=False)[0]['generated_text']
            has_event = "yes" in response.lower()
            
            result_holder["data"] = {"has_event": has_event, "title": subject if has_event else None}
            result_holder["completed"] = True
        except Exception as e:
            result_holder["error"] = e
            result_holder["completed"] = True
    
    # Run AI in thread with timeout
    thread = threading.Thread(target=run_ai, daemon=True)
    thread.start()
    thread.join(timeout=10)  # 10 second timeout
    
    if not result_holder["completed"]:
        print(f"   ⚠️  AI extraction timeout (>10s) - skipping AI")
        return None
    
    if result_holder["error"]:
        print(f"   ⚠️  AI extraction error: {result_holder['error']}")
        return None
    
    return result_holder["data"]


# ---------------- MAIN WITH BETTER ERROR HANDLING ----------------
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print("📡 STARTING GMAIL WATCH")
    print(f"{'='*60}")
    
    try:
        response = gmail_service.users().watch(
            userId='me',
            body={"labelIds": ["INBOX"], "topicName": f"projects/{PROJECT_ID}/topics/{TOPIC_NAME}"}
        ).execute()
        expiration = datetime.fromtimestamp(int(response['expiration']) / 1000)
        print(f"✅ Gmail watch started successfully")
        print(f"⏰ Watch expires: {expiration.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔔 Listening for Gmail notifications...\n")
    except Exception as e:
        print(f"❌ Failed to start Gmail watch: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

    # Process existing unread emails
    print(f"\n{'='*60}")
    print("🔍 PROCESSING EXISTING UNREAD EMAILS")
    print(f"{'='*60}")
    
    try:
        for mail in fetch_unread_emails(limit=5):
            try:
                subject = mail['subject']
                body = mail['body']
                event_info = extract_event_details(subject, body)

                if event_info and isinstance(event_info, dict) and event_info.get("has_event"):
                    try:
                        dt_str = f"{event_info.get('date') or ''} {event_info.get('time') or ''}".strip()
                        event_time = parser.parse(dt_str, fuzzy=True, default=datetime.now())

                        if event_time < datetime.now():
                            event_time = event_time.replace(year=datetime.now().year)

                        create_calendar_event(
                            summary=event_info.get("title") or subject,
                            start_datetime=event_time
                        )
                    except Exception as e:
                        print(f"   ⚠️  Failed to create event for '{subject}': {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print(f"\n❌ No event detected in: {subject[:50]}...")
            except Exception as e:
                print(f"\n⚠️  Error processing email: {e}")
                import traceback
                traceback.print_exc()
                continue
    except Exception as e:
        print(f"\n⚠️  Error in initial email processing: {e}")
        import traceback
        traceback.print_exc()

    # Start listening
    print(f"\n{'='*60}")
    print("👂 LISTENING FOR NEW EMAILS...")
    print(f"{'='*60}")
    print("Press Ctrl+C to stop\n")
    
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
    try:
        streaming_pull_future.result()
    except KeyboardInterrupt:
        print(f"\n{'='*60}")
        print("🛑 STOPPING LISTENER")
        print(f"{'='*60}")
        streaming_pull_future.cancel()
        subscriber.close()
        print("✅ Listener stopped cleanly")
        print(f"📊 Total emails processed: {len(processed_ids)}")
    except Exception as e:
        print(f"\n⚠️  Streaming error: {e}")
        import traceback
        traceback.print_exc()
        streaming_pull_future.cancel()
        subscriber.close()
