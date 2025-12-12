import os
import json
import asyncio
import websockets
import time
import audioop
import base64
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, WebSocket, Request, Response
from fastapi.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv

load_dotenv()

# 設定
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PORT = int(os.environ.get("PORT", 8080))

# OpenAI Realtime API 設定
OPENAI_WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime"

# システムプロンプト (Session Updateで送信)
SYSTEM_MESSAGE = (
    "あなたはAI転職エージェントのアシスタントです。"
    "転職希望者との面談日程を調整することが主な役割です。"
    "女性らしい柔らかい話し方で、明るく丁寧なトーンで話してください。"
    "早口ではなく、落ち着いたテンポで話してください。"
    ""
    "【重要な注意事項】"
    "・ユーザーが完全に話し終わるまで待ってください。途中で話し始めないでください。"
    "・日付を聞いたら、必ず復唱して確認してください（例：12月19日木曜日ですね）"
    "・「明日」「来週」などの相対的な日付表現を聞いたら、まず calculate_date ツールで正確な日付に変換してください"
    "・時間について「夕方」「午後」「朝」などの曖昧な表現を聞いたら、具体的な時間を聞き返してください（例：「夕方でしたら、何時頃がよろしいでしょうか」）"
    ""
    "【会話の流れ】"
    "1. 最初の挨拶：「AI転職エージェントです。面談日程の調整を行いたくご連絡いたしました。3分ほどお時間よろしいでしょうか。」"
    ""
    "2a. 了承を得たら："
    "   「ありがとうございます。転職活動にあたり、エージェントと面談を行う日程を設定いたします。お時間は30分を想定しております。ご都合の良い日付はございますか。」"
    ""
    "2b. 時間がないと言われたら："
    "   「承知いたしました。それでは改めてご連絡させていただきたいのですが、いつ頃でしたらお時間よろしいでしょうか。」"
    "   → 相対的な日付（例：明日、来週）なら calculate_date で変換"
    "   → 具体的な日時が決まったら save_callback で保存"
    "   → 「それでは、〇月〇日〇時頃に改めてご連絡させていただきます。失礼いたします。」then end_call"
    ""
    "3. 日付の処理："
    "   - 相対的な表現（明日、来週など）→ まず calculate_date で変換"
    "   - 具体的な日付を復唱確認"
    "   - check_availability で担当者のスケジュールを確認"
    ""
    "4. スケジュール確認の結果："
    "   - 空いている → 時間を聞く（1時間単位、例：13時、14時）"
    "   - 空いていない → 他の日付を聞く"
    "   - 時間が曖昧（夕方、午後など）→ 具体的な時間を聞き返す"
    ""
    "5. 日時の最終確認："
    "   「調整ありがとうございます。〇月〇日（〇曜日）〇時でお間違いないでしょうか。」"
    ""
    "6. 伝言の確認（ループ開始）："
    "   「ありがとうございます。担当者に何か伝えたい事項はございますか。」"
    ""
    "7. 伝言があった場合："
    "   - 内容を復唱：「〇〇〇〇、とお伝えいたします。お間違いないでしょうか。」"
    "   - 確認後、内容を記憶"
    "   - 「他に伝えたい事項はございますか。」と再度聞く（6に戻る）"
    ""
    "8. 伝言がない場合、または「ない」と言われた場合："
    "   - すべての伝言をまとめて save_appointment で保存"
    ""
    "9. 最後の挨拶："
    "   「本日はお忙しい中お時間をいただき、ありがとうございました。当日よろしくお願いいたします。失礼いたします。」"
    "   → その後 end_call を呼ぶ"
    ""
    "ユーザーが話し終わるまで十分に待ってください。相槌は最小限にしてください。"
)

app = FastAPI()

@app.get("/")
def index():
    return {"message": "Twilio Media Stream Server is running!"}

@app.get("/appointments")
def get_appointments():
    """
    保存された予約データを確認するエンドポイント
    """
    import os
    appointments_file = "appointments.json"
    
    if os.path.exists(appointments_file):
        with open(appointments_file, "r", encoding="utf-8") as f:
            appointments = json.load(f)
        return {"appointments": appointments, "count": len(appointments)}
    else:
        return {"appointments": [], "count": 0, "message": "No appointments found"}

@app.get("/callbacks")
def get_callbacks():
    """
    保存された再架電リクエストを確認するエンドポイント
    """
    import os
    callbacks_file = "callbacks.json"
    
    if os.path.exists(callbacks_file):
        with open(callbacks_file, "r", encoding="utf-8") as f:
            callbacks = json.load(f)
        return {"callbacks": callbacks, "count": len(callbacks)}
    else:
        return {"callbacks": [], "count": 0, "message": "No callbacks found"}

@app.post("/voice/entry")
async def voice_entry(request: Request):
    """
    Twilio: 着信時 (Start)
    Stream (WebSocket) に接続させるTwiMLを返す
    """
    response = VoiceResponse()
    # 最初の挨拶は Realtime API に任せるか、ここで <Say> するか。
    # ストリーム接続のラグを埋めるために <Say> を入れてもいいが、
    # Realtime API の "response.create" で挨拶させるのが最も自然。
    # ここでは接続確立メッセージだけ簡易に入れる。
    
    # 接続
    connect = Connect()
    stream = connect.stream(url=f"wss://{request.headers.get('host')}/voice/stream", track="inbound_track")
    response.append(connect)
    
    # ストリームが切断された場合のフォールバック
    # OpenAIが「さようなら」を言ってから切断するので、ここでは何も言わない
    # response.say("AIとの接続が切れました。通話を終了します。", language="ja-JP", voice="alice")
    
    return Response(content=str(response), media_type="application/xml")

@app.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket):
    """
    Twilio Media Stream <-> OpenAI Realtime API の中継
    """
    await websocket.accept()
    print("[INFO] Twilio WebSocket Connected")

    # OpenAI Realtime API への接続
    # ヘッダーに Authorization と OpenAI-Beta が必要
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }

    try:
        async with websockets.connect(OPENAI_WS_URL, additional_headers=headers) as openai_ws:
            print("[INFO] OpenAI Realtime API Connected")
            
            # セッション初期化 (Session Update)
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": SYSTEM_MESSAGE,
                    "voice": "shimmer", # 落ち着いた女性の声
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "turn_detection": None, # サーバーVADを完全無効化
                    "tools": [
                        {
                            "type": "function",
                            "name": "calculate_date",
                            "description": "相対的な日付表現（「明日」「来週」など）を正確な日付（YYYY-MM-DD形式）に変換する。",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "relative_expression": {
                                        "type": "string",
                                        "description": "相対的な日付表現（例：明日、来週の金曜日、3日後）"
                                    }
                                },
                                "required": ["relative_expression"]
                            }
                        },
                        {
                            "type": "function",
                            "name": "check_availability",
                            "description": "指定された日付と時間に担当者が面談可能かどうかを確認する。必ずYYYY-MM-DD形式の日付を渡すこと。",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "date": {
                                        "type": "string",
                                        "description": "確認したい日付。必ずYYYY-MM-DD形式で指定（例: 2025-12-20）"
                                    },
                                    "time": {
                                        "type": "string",
                                        "description": "確認したい時間（オプション）。HH:00形式で指定（例: 13:00、15:00）"
                                    }
                                },
                                "required": ["date"]
                            }
                        },
                        {
                            "type": "function",
                            "name": "save_appointment",
                            "description": "面談の予約を確定し保存する。すべての伝言をまとめて1回だけ呼び出すこと。",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "date": {
                                        "type": "string",
                                        "description": "面談日付（YYYY-MM-DD形式、例: 2025-12-21）"
                                    },
                                    "time": {
                                        "type": "string",
                                        "description": "面談時間（HH:00形式、例: 13:00）"
                                    },
                                    "messages": {
                                        "type": "string",
                                        "description": "担当者への伝言（複数ある場合は改行で区切る。なければ空文字）"
                                    }
                                },
                                "required": ["date", "time"]
                            }
                        },
                        {
                            "type": "function",
                            "name": "save_callback",
                            "description": "ユーザーが今時間がないと言った場合、再架電の日時を保存する。",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "callback_date": {
                                        "type": "string",
                                        "description": "再架電希望日付（YYYY-MM-DD形式、例: 2025-12-20）"
                                    },
                                    "callback_time": {
                                        "type": "string",
                                        "description": "再架電希望時間（HH:00形式、例: 18:00）、指定がなければ空文字"
                                    },
                                    "note": {
                                        "type": "string",
                                        "description": "備考（例：夕方以降なら可、など。なければ空文字）"
                                    }
                                },
                                "required": ["callback_date"]
                            }
                        },
                        {
                            "type": "function",
                            "name": "end_call",
                            "description": "通話を終了する。重要：必ず「さようなら」やお別れの挨拶を言い終わってから、このツールを呼び出すこと。挨拶を言う前に呼び出さないこと。",
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "required": []
                            }
                        }
                    ],
                    "tool_choice": "auto"
                }
            }
            await openai_ws.send(json.dumps(session_update))

            # 初回の挨拶をトリガー
            initial_greeting = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": "「AI転職エージェントです。面談日程の調整を行いたくご連絡いたしました。3分ほどお時間よろしいでしょうか。」と挨拶してください。"
                }
            }
            await openai_ws.send(json.dumps(initial_greeting))

            stream_sid = None
            # 自前VADパラメータ
            VOICE_THRESHOLD = 600  # 音量閾値
            SILENCE_DURATION_MS = 600 # 話し終わりとみなす無音期間
            CONSECUTIVE_VOICE_REQUIRED = 2  # 発話開始とみなす連続検知回数
            
            is_speaking = False
            last_speech_time = 0
            consecutive_voice_count = 0  # 連続で閾値を超えた回数
            
            # AI発話中フラグ（割り込み音声はバッファに入れるが、commitはしない）
            ai_is_speaking = False
            latest_media_timestamp = 0

            async def receive_from_twilio():
                nonlocal stream_sid
                nonlocal is_speaking, last_speech_time, consecutive_voice_count
                nonlocal ai_is_speaking, latest_media_timestamp
                
                try:
                    while True:
                        data = await websocket.receive_text()
                        msg = json.loads(data)
                        
                        event_type = msg.get("event")
                        
                        if event_type == "media":
                            track = msg["media"].get("track")

                            if track == "inbound":
                                audio_payload = msg["media"]["payload"]
                                
                                # 常にバッファには送る（割り込み音声も記録するため）
                                await openai_ws.send(json.dumps({
                                    "type": "input_audio_buffer.append",
                                    "audio": audio_payload
                                }))
                                
                                # --- 簡易VAD (音量検知) ---
                                try:
                                    chunk = base64.b64decode(audio_payload)
                                    pcm_chunk = audioop.ulaw2lin(chunk, 2)
                                    rms = audioop.rms(pcm_chunk, 2)
                                    
                                    if rms > VOICE_THRESHOLD:
                                        # 連続検知カウンターを増やす
                                        consecutive_voice_count += 1
                                        
                                        # 連続で規定回数以上検知したら発話開始
                                        if consecutive_voice_count >= CONSECUTIVE_VOICE_REQUIRED:
                                            if not is_speaking:
                                                print(f"[VAD] Speech Detected (RMS: {rms}, consecutive: {consecutive_voice_count})")
                                                is_speaking = True
                                            last_speech_time = time.time() * 1000
                                    else:
                                        # 静寂：カウンターをリセット
                                        consecutive_voice_count = 0
                                        
                                        if is_speaking:
                                            # 話し終わったかも判定
                                            silence_duration = (time.time() * 1000) - last_speech_time
                                            if silence_duration > SILENCE_DURATION_MS:
                                                print(f"[VAD] Silence detected ({silence_duration}ms) -> Committing")
                                                is_speaking = False
                                                
                                                # AI発話中でなければコミット＆レスポンス生成
                                                if not ai_is_speaking:
                                                    await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                                                    await openai_ws.send(json.dumps({"type": "response.create"}))
                                                else:
                                                    print("[VAD] AI is speaking, buffering user input for later")
                                                
                                except Exception as e:
                                    pass

                            else:
                                pass
                        
                        elif event_type == "start":
                            stream_sid = msg["start"]["streamSid"]
                            print(f"[INFO] Stream started: {stream_sid}")
                        
                        elif event_type == "stop":
                            print("[INFO] Stream stopped")
                            break
                            
                except Exception as e:
                    print(f"[ERROR] Twilio receive error: {e}")
                    import traceback
                    print(f"[ERROR] Traceback: {traceback.format_exc()}")

            async def receive_from_openai():
                nonlocal stream_sid
                nonlocal ai_is_speaking, latest_media_timestamp
                
                # 通話終了リクエストフラグ
                call_end_requested = False
                
                try:
                    while True:
                        data = await openai_ws.recv()
                        msg = json.loads(data)
                        event_type = msg.get("type")

                        if event_type == "response.audio.delta":
                            ai_is_speaking = True
                            latest_media_timestamp = time.time() * 1000
                            audio_delta = msg.get("delta")
                            if audio_delta and stream_sid:
                                await websocket.send_json({
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": audio_delta}
                                })
                        
                        elif event_type == "response.audio.done":
                            ai_is_speaking = False
                            print("[INFO] AI finished speaking")
                            
                            # 通話終了が要求されていたら、話し終わった後に切断
                            if call_end_requested:
                                print("[INFO] Closing call after AI finished goodbye")
                                await asyncio.sleep(1)  # 念のため1秒待つ
                                await websocket.close()
                                break
                        
                        elif event_type == "response.function_call_arguments.done":
                            # ツール呼び出しの検知
                            call_id = msg.get("call_id")
                            name = msg.get("name")
                            
                            if name == "calculate_date":
                                # 相対的な日付表現を正確な日付に変換
                                arguments = msg.get("arguments", "{}")
                                args = json.loads(arguments) if isinstance(arguments, str) else arguments
                                relative_expr = args.get("relative_expression", "")
                                
                                print(f"[INFO] Calculating date for: {relative_expr}")
                                
                                # 日本時間（JST）で今日の日付を取得
                                jst = timezone(timedelta(hours=9))
                                today = datetime.now(jst)
                                
                                # 簡易的な日付計算
                                result_date = None
                                day_name = ""
                                
                                if "明日" in relative_expr:
                                    result_date = today + timedelta(days=1)
                                elif "明後日" in relative_expr:
                                    result_date = today + timedelta(days=2)
                                elif "来週" in relative_expr:
                                    result_date = today + timedelta(days=7)
                                elif "日後" in relative_expr:
                                    try:
                                        import re
                                        match = re.search(r'(\d+)日後', relative_expr)
                                        if match:
                                            days = int(match.group(1))
                                            result_date = today + timedelta(days=days)
                                    except:
                                        pass
                                
                                if result_date:
                                    date_str = result_date.strftime("%Y-%m-%d")
                                    weekday = result_date.weekday()
                                    day_name = ["月", "火", "水", "木", "金", "土", "日"][weekday]
                                    output = f"{date_str}（{day_name}曜日）"
                                else:
                                    output = "日付を計算できませんでした。具体的な日付を教えてください。"
                                
                                await openai_ws.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": output
                                    }
                                }))
                                await openai_ws.send(json.dumps({"type": "response.create"}))
                            
                            elif name == "check_availability":
                                # スケジュール確認（ダミーデータ）
                                arguments = msg.get("arguments", "{}")
                                args = json.loads(arguments) if isinstance(arguments, str) else arguments
                                date = args.get("date", "")
                                time_slot = args.get("time", "")
                                
                                print(f"[INFO] Checking availability for {date} {time_slot}")
                                
                                # 日付から曜日を計算
                                try:
                                    from datetime import datetime as dt
                                    check_date = dt.strptime(date, "%Y-%m-%d")
                                    weekday = check_date.weekday()  # 0=月, 6=日
                                    day_name = ["月", "火", "水", "木", "金", "土", "日"][weekday]
                                    
                                    if weekday >= 5:  # 土日
                                        result = f"{date}（{day_name}曜日）は担当者がお休みをいただいております。平日でご都合の良い日はございますか。"
                                    else:
                                        if time_slot:
                                            result = f"{date}（{day_name}曜日） {time_slot}は空いております。"
                                        else:
                                            result = f"{date}（{day_name}曜日）は対応可能です。"
                                except:
                                    result = "日付の形式を確認できませんでした。YYYY-MM-DD形式で日付を指定してください。"
                                
                                await openai_ws.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": result
                                    }
                                }))
                                await openai_ws.send(json.dumps({"type": "response.create"}))
                            
                            elif name == "save_appointment":
                                # 予約を保存
                                arguments = msg.get("arguments", "{}")
                                args = json.loads(arguments) if isinstance(arguments, str) else arguments
                                date = args.get("date", "")
                                time_slot = args.get("time", "")
                                messages = args.get("messages", "")
                                
                                print(f"[INFO] Saving appointment: {date} {time_slot}")
                                
                                # JSONファイルに保存
                                import os
                                appointments_file = "appointments.json"
                                appointments = []
                                
                                if os.path.exists(appointments_file):
                                    with open(appointments_file, "r", encoding="utf-8") as f:
                                        appointments = json.load(f)
                                
                                appointment = {
                                    "call_sid": stream_sid,
                                    "date": date,
                                    "time": time_slot,
                                    "messages": messages,
                                    "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat()
                                }
                                appointments.append(appointment)
                                
                                with open(appointments_file, "w", encoding="utf-8") as f:
                                    json.dump(appointments, f, ensure_ascii=False, indent=2)
                                
                                result = f"予約を確定しました。{date} {time_slot}で登録いたしました。"
                                
                                await openai_ws.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": result
                                    }
                                }))
                                await openai_ws.send(json.dumps({"type": "response.create"}))
                            
                            elif name == "save_callback":
                                # 再架電日時を保存
                                arguments = msg.get("arguments", "{}")
                                args = json.loads(arguments) if isinstance(arguments, str) else arguments
                                callback_date = args.get("callback_date", "")
                                callback_time = args.get("callback_time", "")
                                note = args.get("note", "")
                                
                                print(f"[INFO] Saving callback: {callback_date} {callback_time}")
                                
                                # JSONファイルに保存
                                import os
                                callbacks_file = "callbacks.json"
                                callbacks = []
                                
                                if os.path.exists(callbacks_file):
                                    with open(callbacks_file, "r", encoding="utf-8") as f:
                                        callbacks = json.load(f)
                                
                                callback = {
                                    "call_sid": stream_sid,
                                    "callback_date": callback_date,
                                    "callback_time": callback_time,
                                    "note": note,
                                    "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat()
                                }
                                callbacks.append(callback)
                                
                                with open(callbacks_file, "w", encoding="utf-8") as f:
                                    json.dump(callbacks, f, ensure_ascii=False, indent=2)
                                
                                result = f"再架電を{callback_date}に設定いたしました。"
                                
                                await openai_ws.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": result
                                    }
                                }))
                                await openai_ws.send(json.dumps({"type": "response.create"}))
                            
                            elif name == "end_call":
                                print("[INFO] AI requested to end the call, waiting for speech to finish")
                                call_end_requested = True
                                # フラグを立てるだけで、実際の切断はresponse.audio.doneで行う
                        
                        elif event_type == "error":
                            print(f"[OPENAI ERROR] {msg}")

                except Exception as e:
                    print(f"[ERROR] OpenAI receive error: {e}")
                    import traceback
                    print(f"[ERROR] Traceback: {traceback.format_exc()}")

            await asyncio.gather(receive_from_twilio(), receive_from_openai())

    except Exception as e:
        print(f"[CRITICAL] WebSocket Connection Failed: {e}")
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass


