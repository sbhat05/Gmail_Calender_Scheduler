# 📅 Gmail Calendar Scheduler

An intelligent Python application that automatically monitors your Gmail inbox and creates Google Calendar events from emails containing event information. Uses AI (Flan-T5) for smart event detection and regex patterns for date/time extraction.

## ✨ Features

- 🔔 **Real-time Gmail monitoring** using Google Cloud Pub/Sub
- 🤖 **AI-powered event detection** with Google's Flan-T5 model
- 📊 **Smart confidence scoring** to reduce false positives
- 📅 **Automatic calendar event creation** with proper timezone support
- 🔍 **Multi-pattern date/time extraction** (handles various formats)
- ⚡ **Processes existing unread emails** on startup
- 🛡️ **Past event filtering** to avoid creating outdated events

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Google Cloud Project with Gmail and Calendar APIs enabled
- Google Pub/Sub topic and subscription configured

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/sbhat05/Gmail_Calender_Scheduler.git
   cd Gmail_Calender_Scheduler
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Google Cloud credentials** (see [Setup Guide](#-detailed-setup-guide) below)

4. **Configure environment variables**
   ```bash
   # Copy the example env file
   cp .env.example .env
   
   # Edit .env with your configuration
   ```

5. **Run the application**
   ```bash
   python gmail_scheduler.py
   ```

## 📋 Requirements

Create a `requirements.txt` file with:

```txt
google-api-python-client>=2.100.0
google-auth-httplib2>=0.1.1
google-auth-oauthlib>=1.1.0
google-cloud-pubsub>=2.18.0
python-dateutil>=2.8.2
transformers>=4.35.0
torch>=2.0.0
```

## 🔧 Detailed Setup Guide

### 1. Google Cloud Console Setup

#### Enable APIs
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the following APIs:
   - Gmail API
   - Google Calendar API
   - Cloud Pub/Sub API

#### Create OAuth 2.0 Credentials
1. Navigate to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Choose **Desktop app** as application type
4. Download the JSON file
5. Rename it to `client_secret.json` and place in project root

#### Create Service Account (for Pub/Sub)
1. Go to **IAM & Admin** → **Service Accounts**
2. Click **Create Service Account**
3. Grant these roles:
   - **Pub/Sub Editor**
   - **Pub/Sub Subscriber**
4. Create a key (JSON format)
5. Download and save as `service-account-key.json`

### 2. Configure Pub/Sub

#### Create Topic
```bash
gcloud pubsub topics create gmail-push-topic
```

#### Create Subscription
```bash
gcloud pubsub subscriptions create gmail-push-topic-sub \
    --topic=gmail-push-topic
```

#### Grant Gmail Permission
```bash
gcloud pubsub topics add-iam-policy-binding gmail-push-topic \
    --member=serviceAccount:gmail-api-push@system.gserviceaccount.com \
    --role=roles/pubsub.publisher
```

### 3. Environment Configuration

Create a `.env` file in the project root:

```env
# Google Cloud Project Configuration
PROJECT_ID=your-project-id-here
TOPIC_NAME=gmail-push-topic
SUBSCRIPTION_ID=gmail-push-topic-sub

# OAuth Client Secret File
CLIENT_SECRET_FILE=client_secret.json

# Service Account Key (for Pub/Sub)
GOOGLE_APPLICATION_CREDENTIALS=service-account-key.json

# Timezone Configuration
TIMEZONE=Asia/Kolkata

# Optional: AI Model Configuration
USE_AI=true
AI_MODEL=google/flan-t5-small
```
Install `python-dotenv`:
```bash
pip install python-dotenv
```

## 🗂️ Project Structure

```
gmail-calendar-scheduler/
├── gmail_scheduler.py          # Main application file
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (DO NOT COMMIT)
├── .gitignore                 # Git ignore rules
├── README.md                  # This file
├── client_secret.json         # OAuth credentials (in .gitignore)
└── service-account-key.json   # Service account key (gitignore)
```
## 📖 How It Works

1. **Authentication**: Uses OAuth 2.0 to access Gmail and Calendar APIs
2. **Gmail Watch**: Sets up a webhook to receive push notifications
3. **Event Detection**: 
   - AI model classifies if email contains event info
   - Regex patterns extract dates and times
   - Confidence scoring determines if event should be created
4. **Calendar Creation**: Automatically creates 1-hour events with extracted details
5. **Continuous Monitoring**: Listens for new emails via Pub/Sub

## 🎯 Confidence Scoring System

Events are created when confidence score ≥ 2/6:

- **+2 points**: AI model detects event
- **+2 points**: Valid date/time found
- **+1 point**: Subject contains event keywords
- **+1 point**: Body contains event keywords

## 🤖 AI Mode

The application supports two modes:

1. **AI Mode** (Flan-T5): 80MB model, accurate event detection
2. **Regex-Only Mode**: Fallback if AI dependencies not installed

To use regex-only mode, simply don't install `transformers` and `torch`.



## 📊 Supported Date/Time Formats

- "Meeting on 25th December 2025 at 3:00 PM"
- "Call tomorrow at 10 AM"
- "Interview on Dec 15 at 2:30pm"
- "Event today at 5pm"
- "Workshop on January 10th, 2025 @ 11:00 AM"

