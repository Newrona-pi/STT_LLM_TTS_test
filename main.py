
import os
import time
import json
import sqlite3
import asyncio
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, BackgroundTasks, Request, Response, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import openai
# twilio
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.request_validator import RequestValidator
# httpx for downloading audio
import httpx

from dotenv import load_dotenv

# 環境変数の読み込み (ローカル用)
load_dotenv()

# 設定
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
BASE_URL = os.environ.get("BASE_URL")  # 例: https://<render-url>.onrender.com (末尾スラッシュなし)

if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

app = FastAPI()

# 音声ファイル保存用ディレクトリ
AUDIO_DIR = "audio"
os.makedirs(AUDIO_DIR, exist_ok=True)
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")

# データベース初期化 (SQLite)
DB_PATH = "logs.sqlite3"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS conversation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            call_sid TEXT,
            turn_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_log(call_sid: str, turn_id: int, role: str, content: str):
    """
    会話ログをSQLiteに保存する関数
    将来的に予約システムなどへの拡張を想定して分離
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        created_at = datetime.now().isoformat()
        c.execute(
            "INSERT INTO conversation_logs (call_sid, turn_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (call_sid, turn_id, role, content, created_at)
        )
        conn.commit()
        conn.close()
        print(f"[LOG] Saved: {role} - {content[:20]}...")
    except Exception as e:
        print(f"[ERROR] Failed to save log: {e}")

# 起動時に音声素材を生成
GREETING_FILE = "greeting.mp3"
GREETING_TEXT = "お電話ありがとうございます。AIアシスタントです。ご用件をお話しください。"
BYE_FILE = "bye.mp3"
BYE_TEXT = "お電話ありがとうございました。失礼いたします。"

def generate_static_audio():
    # 挨拶
    path_greet = os.path.join(AUDIO_DIR, GREETING_FILE)
    if not os.path.exists(path_greet):
        try:
            print("[INFO] Generating greeting audio...")
            resp = openai.audio.speech.create(model="tts-1", voice="alloy", input=GREETING_TEXT, response_format="mp3")
            resp.stream_to_file(path_greet)
        except Exception as e:
            print(f"[ERROR] Failed to generate greeting: {e}")
    # 終了
    path_bye = os.path.join(AUDIO_DIR, BYE_FILE)
    if not os.path.exists(path_bye):
        try:
            print("[INFO] Generating bye audio...")
            resp = openai.audio.speech.create(model="tts-1", voice="alloy", input=BYE_TEXT, response_format="mp3")
            resp.stream_to_file(path_bye)
        except Exception as e:
            print(f"[ERROR] Failed to generate bye: {e}")

generate_static_audio()

# --- エンドポイント ---

@app.post("/voice/entry")
async def voice_entry(request: Request):
    """
    Twilio: 着信時に呼び出されるWebhook (Start)
    """
    response = VoiceResponse()
    
    # 挨拶再生
    if BASE_URL:
        clean_base_url = BASE_URL.rstrip("/")
        # URLキャッシュ対策でクエリつける? いったんそのまま
        greeting_url = f"{clean_base_url}/audio/{GREETING_FILE}"
        response.play(greeting_url)
    else:
        response.say(GREETING_TEXT, language="ja-JP", voice="alice")

    # 録音開始 (ピー音なし)
    response.record(
        action="/voice/handle-recording",
        method="POST",
        timeout=5,
        max_length=30,
        play_beep=False # ピー音削除
    )
    
    # 録音がなかった場合
    response.say("音声が確認できませんでした。お電話ありがとうございました。", language="ja-JP")
    
    return Response(content=str(response), media_type="application/xml")

@app.post("/voice/handle-recording")
async def handle_recording(
    CallSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingDuration: str = Form(None)
):
    """
    Twilio: 録音完了後に呼び出されるWebhook
    """
    print(f"[INFO] RecordingUrl: {RecordingUrl}, CallSid: {CallSid}")
    
    resp = VoiceResponse()

    try:
        # 1. 音声ファイルのダウンロード
        # TwilioのWebhookタイムアウト(15s)を考慮し、なるべく高速に処理したい
        # Basic認証を追加 (Twilioのセキュリティ設定によっては必須)
        auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN else None
        
        # 1. 音声ファイルのダウンロード
        # TwilioのWebhookタイムアウト(15s)を考慮し、なるべく高速に処理したい
        # Basic認証を追加 (Twilioのセキュリティ設定によっては必須)
        auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN) if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN else None
        
        # Twilio仕様対策: 録音完了直後はファイル生成待ちのラグがあるため、リトライ処理を入れる
        # 高速化のため、リトライ間隔を短縮 (0.2秒)
        
        target_url = RecordingUrl 
        audio_content = None
        max_retries = 10 # 間隔を短くした分、回数を増やす
        retry_interval = 0.2 # 秒 (高速化)
        min_audio_bytes = 1000 

        async with httpx.AsyncClient(follow_redirects=True) as client:
            print(f"[DEBUG] Start downloading audio from: {target_url}")
            
            for attempt in range(max_retries):
                try:
                    http_resp = await client.get(target_url, auth=auth, timeout=5.0)
                    
                    content_type = http_resp.headers.get("content-type", "")
                    content_len = len(http_resp.content)
                    status_code = http_resp.status_code
                    
                    # 成功判定
                    if status_code == 200 and "audio" in content_type and content_len > min_audio_bytes:
                        audio_content = http_resp.content
                        print(f"[DEBUG] Audio download success on attempt {attempt+1}")
                        break
                    
                    # 失敗
                    # print(f"[DEBUG] Retry... (status={status_code})")
                except Exception as e:
                    print(f"[WARNING] Exception during download: {e}")

                await asyncio.sleep(retry_interval)
        
        if audio_content is None:
            print(f"[ERROR] Failed to download audio after retries.")
            # エラー時も切断せず
            resp.say("すみません、聞き取れませんでした。もう一度お願いします。", language="ja-JP")
            resp.record(action="/voice/handle-recording", method="POST", timeout=5, max_length=30, play_beep=False)
            return Response(content=str(resp), media_type="application/xml")

        temp_input_filename = f"{AUDIO_DIR}/input_{CallSid}_{int(time.time())}.wav"
        with open(temp_input_filename, "wb") as f:
            f.write(audio_content)

        # 2. STT (OpenAI Whisper)
        try:
            with open(temp_input_filename, "rb") as audio_file:
                transcript_response = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="ja"
                )
            user_text = transcript_response.text
            print(f"[STT] User: {user_text}")
        except Exception as e:
            print(f"[ERROR] STT failed: {e}")
            if "insufficient_quota" in str(e):
                resp.say("OpenAIのAPI利用枠を超過しています。プランを確認してください。", language="ja-JP", voice="alice")
                return Response(content=str(resp), media_type="application/xml")
            user_text = ""

        if not user_text:
            resp.say("すみません、聞こえませんでした。もう一度お願いします。", language="ja-JP")
            resp.record(action="/voice/handle-recording", method="POST", timeout=5, max_length=30, play_beep=False)
            return Response(content=str(resp), media_type="application/xml")

        # 終了判定
        end_keywords = ["終了", "終わり", "バイバイ", "さようなら", "切って", "大丈夫", "以上です"]
        if any(w in user_text for w in end_keywords):
            # 終了音声を再生
            if BASE_URL:
                clean_base_url = BASE_URL.rstrip("/")
                bye_url = f"{clean_base_url}/audio/{BYE_FILE}"
                resp.play(bye_url)
            else:
                resp.say("お電話ありがとうございました。失礼いたします。", language="ja-JP", voice="alice")
            
            resp.hangup()
            return Response(content=str(resp), media_type="application/xml")

        # 履歴取得 (今回の発言を保存する前に取得することで重複回避)
        conn = sqlite3.connect(DB_PATH)
        log_count = conn.execute("SELECT COUNT(*) FROM conversation_logs WHERE call_sid = ?", (CallSid,)).fetchone()[0]
        history_rows = conn.execute(
            "SELECT role, content FROM conversation_logs WHERE call_sid = ? ORDER BY id ASC", 
            (CallSid,)
        ).fetchall()
        conn.close()
        
        # 3. LLM (OpenAI Chat)
        now_str = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        messages = [
            {"role": "system", "content": (
                "あなたは親切な電話対応AIです。"
                "日本語で話します。"
                f"現在は {now_str} です。"
                "ユーザーの質問には的確に答えてください。"
                "回答の最後には必ず「他にご用件はありますか？」と付け加えてください。"
                "返答は1〜2文で短くしてください。"
                "フィラーは入れないでください。"
            )}
        ]
        # 過去ログ追加
        for r, c in history_rows:
            messages.append({"role": r, "content": c})
        
        # 今回のUser発言を明示的に追加 (これで最新の話題に答える)
        messages.append({"role": "user", "content": user_text})

        try:
            chat_completion = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=150,
                temperature=0.7
            )
            ai_text = chat_completion.choices[0].message.content
            print(f"[LLM] AI: {ai_text}")
        except Exception as e:
            print(f"[ERROR] LLM failed: {e}")
            if "insufficient_quota" in str(e):
                ai_text = "OpenAIの利用枠が超過しています。"
            else:
                ai_text = "すみません、少し聞き取れませんでした。"

        # ログ保存 (User と Assistant をまとめて保存)
        # ※DBには保存しておく(次回以降の履歴のため)
        current_turn = (log_count // 2) + 1
        save_log(CallSid, current_turn, "user", user_text)
        save_log(CallSid, current_turn, "assistant", ai_text)

        # 4. TTS (OpenAI TTS)
        audio_url = None
        try:
            speech_response = openai.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=ai_text,
                response_format="mp3"
            )
            output_filename = f"response_{CallSid}_{int(time.time())}.mp3"
            output_path = os.path.join(AUDIO_DIR, output_filename)
            speech_response.stream_to_file(output_path)
            
            if BASE_URL:
                clean_base_url = BASE_URL.rstrip("/")
                audio_url = f"{clean_base_url}/audio/{output_filename}"
            else:
                print("[WARNING] BASE_URL not set")

        except Exception as e:
            print(f"[ERROR] TTS failed: {e}")
        
        # TwiML構築
        if audio_url:
            resp.play(audio_url)
        else:
            # TTS失敗時
            resp.say(ai_text, language="ja-JP", voice="alice")

        # 継続するためにRecord
        resp.record(
            action="/voice/handle-recording",
            method="POST",
            timeout=5,
            max_length=30,
            play_beep=False # ピー音削除
        )
        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print(f"[CRITICAL ERROR] {e}")
        import traceback
        traceback.print_exc()
        
        # エラー詳細をログに出す
        print(f"--- TRACEBACK ---")
        print(traceback.format_exc())
        print(f"-----------------")
        
        # 致命的なエラーでも切断せず、標準音声で詫びて録音再開
        emergency_resp = VoiceResponse()
        emergency_resp.say("システムエラーが発生しましたが、会話を続けます。もう一度お願いします。", language="ja-JP")
        emergency_resp.record(action="/voice/handle-recording", method="POST", timeout=5, max_length=30, play_beep=True)
        return Response(content=str(emergency_resp), media_type="application/xml")

@app.get("/")
def index():
    return {"message": "Twilio Voice Bot is running!"}
