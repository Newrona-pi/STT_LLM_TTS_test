import os
import time
import requests
import openai
from openai import OpenAI

# Environment Variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Initialize OpenAI Client
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

def transcribe_audio_url(audio_url: str, max_retries: int = 5, retry_delay: int = 3) -> str:
    """
    Downloads audio from URL and transcribes it using OpenAI Whisper.
    Retries download if file is not ready (Twilio lag).
    """
    if not client:
        print("[WARN] OpenAI API Key not set. STT skipped.")
        return "(STT disabled: API Key missing)"

    file_path = "temp_audio.wav" # Temporary file path
    
    # Download with retry
    for i in range(max_retries):
        try:
            # Authenticate with Twilio credentials to access recording
            auth = (os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN"))
            if not auth[0] or not auth[1]:
                 print("[WARN] Twilio creds missing for download")
                 
            # Add .mp3 extension if not present, though Twilio usually handles it (Or keep as is and rely on content-type)
            # Actually Twilio RecordingUrl is usually .json or .wav or .mp3 if specified. 
            # If plain URL, it might redirect. requests follows redirects by default.
            
            response = requests.get(audio_url, auth=auth)
            if response.status_code == 200:
                # Check Content-Type or size if needed, but 200 is usually good enough for MVP
                with open(file_path, "wb") as f:
                    f.write(response.content)
                break
            elif response.status_code == 404:
                print(f"[INFO] Audio not ready yet, retrying... ({i+1}/{max_retries})")
                time.sleep(retry_delay)
            else:
                print(f"[WARN] Audio download failed: {response.status_code}")
                return f"(STT failed: Download error {response.status_code})"
        except Exception as e:
            print(f"[ERROR] Audio download exception: {e}")
            return f"(STT failed: {str(e)})"
    else:
        return "(STT failed: Audio not accessible after retries)"

    # Transcribe
    try:
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file,
                language="ja",
                prompt="面接の志望動機や自己PR、質問回答です。専門用語や丁寧語が含まれます。「志望動機」を正しく変換してください。"
            )
        
        # Cleanup
        try:
            os.remove(file_path)
        except:
            pass
            
        return transcript.text
    except Exception as e:
        print(f"[ERROR] Whisper API error: {e}")
        return f"(STT failed: {str(e)})"
