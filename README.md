# Twilio + OpenAI Voice Bot

Render + Twilio + OpenAI API を使用した、AIと音声対話するボットの最小構成です。

## 概要

1. 人間が電話をかける (Twilio)
2. 音声を録音
3. **OpenAI Whisper** でテキスト化
4. **OpenAI Chat (GPT-4o)** で返答生成
5. **OpenAI TTS** で音声合成
6. Twilio で再生
7. ループ

## デプロイ手順 (Render)

### 1. 準備

- GitHub リポジトリにこのコードをプッシュしてください。
- [Render](https://render.com/) のアカウントを作成してください。
- [Twilio](https://twilio.com/) のアカウントを作成し、電話番号を取得してください。
- [OpenAI](https://openai.com/) のAPIキーを取得してください。

### 2. Render Web Service の作成

1. Render ダッシュボードで **New +** -> **Web Service** を選択。
2. GitHub リポジトリを選択。
3. 設定項目:
    - **Name**: 任意の名前 (例: `my-voice-bot`)
    - **Runtime**: `Python 3`
    - **Build Command**: `pip install -r requirements.txt`
    - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Environment Variables** (環境変数) を設定:
    - `PYTHON_VERSION`: `3.11.9`
    - `OPENAI_API_KEY`: (OpenAIのAPIキー `sk-...`)
    - `TWILIO_ACCOUNT_SID`: (TwilioのAccount SID)
    - `TWILIO_AUTH_TOKEN`: (TwilioのAuth Token)
    - `BASE_URL`: `https://あなたのアプリ名.onrender.com` (生成されるURLが決まってから設定してもOKですが、初回デプロイ後に必ず設定してください。末尾の `/` は無し)

5. **Create Web Service** をクリック。

### 3. Twilio の設定

1. Render のデプロイが完了し、URL (例: `https://my-voice-bot.onrender.com`) が発行されたことを確認。
2. Twilio コンソールの **Phone Numbers** -> **Manage** -> **Active numbers** から対象の電話番号を選択。
3. **Voice & Fax** セクションの **A Call Comes In** を設定:
    - **Webhook** を選択
    - URL: `https://YOUR-RENDER-URL.onrender.com/voice/entry`
    - Method: `HTTP POST`
4. **Save** で保存。

## 確認方法

設定した電話番号に電話をかけてください。「お電話ありがとうございます」とAIが応答すれば成功です。

## 注意点

- **コスト**: OpenAI API (Whisper, GPT, TTS) および Twilio 通話料がかかります。
- **ログ**: 会話内容は `logs.sqlite3` に保存されますが、Render の無料プラン等はディスクが永続化されないため、再起動すると消える可能性があります。永続化が必要な場合は Render Disk を利用するか、外部DB (PostgreSQLなど) を検討してください。
