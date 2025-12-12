import os
from dotenv import load_dotenv

load_dotenv()

keys = [
    "OPENAI_API_KEY",
    "DATABASE_URL",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_SMS_FROM_NUMBER",
    "TWILIO_FROM_NUMBER",
    "SENDGRID_API_KEY"
]

print("--- Environment Variable Check ---")
for k in keys:
    val = os.environ.get(k)
    status = "SET" if val else "MISSING"
    masked = f"{val[:5]}..." if val else "N/A"
    print(f"{k}: {status} ({masked})")
