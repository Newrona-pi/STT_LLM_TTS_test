# Twilio + OpenAI Voice Bot (Railway Version)

Railway + Twilio + OpenAI API を使用した、AIと音声対話するボットの最小構成です。

## 概要

1. 人間が電話をかける (Twilio)
2. 音声を録音
3. **OpenAI Whisper** でテキスト化
4. **OpenAI Chat (GPT-4o)** で返答生成
5. **OpenAI TTS** で音声合成
6. Twilio で再生
7. ループ

## デプロイ手順 (Railway)

### 1. 準備

- このリポジトリを自身のGitHubアカウントにフォークまたはプッシュしてください。
- [Railway](https://railway.app/) のアカウントを作成してください。
- [Twilio](https://twilio.com/) のアカウントを作成し、電話番号を取得してください。
- [OpenAI](https://openai.com/) のAPIキーを取得してください。

### 2. Railway Project の作成

1. Railway ダッシュボードで **New Project** -> **Deploy from GitHub repository** を選択。
2. このリポジトリ (`STT_LLM_TTS_test` など) を選択。
3. **Deploy Now** をクリックしてデプロイを開始（初回は失敗する可能性がありますが、環境設定後に再デプロイすればOKです）。

### 3. 環境変数の設定 (Variables)

Railway のプロジェクト画面から作成された Service をクリックし、**Variables** タブを選択して以下の変数を追加してください。

| Variable Name | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAIのAPIキー (`sk-...`) |
| `TWILIO_ACCOUNT_SID` | TwilioのAccount SID |
| `TWILIO_AUTH_TOKEN` | TwilioのAuth Token |
| `BASE_URL` | Generate Domainで発行されたURL (例: `https://xxx.up.railway.app`)。<br>末尾の `/` は含めないでください。 |
| `PORT` | Railwayによって自動設定されますが、念のため追加も可 (通常不要) |

※ `BASE_URL` は、Service の **Settings** タブにある **Networking** セクションで **Generate Domain** をクリックして発行されたURLを使用してください。

### 4. Twilio の設定

1. Railway で発行されたURLを確認 (例: `https://my-voice-bot.up.railway.app`)。
2. Twilio コンソールの **Phone Numbers** -> **Manage** -> **Active numbers** から対象の電話番号を選択。
3. **Voice & Fax** セクションの **A Call Comes In** を設定:
    - **Webhook** を選択
    - URL: `https://YOUR-RAILWAY-URL.up.railway.app/voice/entry`
    - Method: `HTTP POST`
4. **Save** で保存。

## 確認方法

設定したTwilioの電話番号に電話をかけてください。「お電話ありがとうございます」とAIが応答すれば成功です。

## 注意点

- **コスト**: OpenAI API (Whisper, GPT, TTS) および Twilio 通話料がかかります。
- **ログ**: 会話内容は `logs.sqlite3` に保存されますが、Railway の一時的なファイルシステムでは再起動（デプロイ）のたびにデータが消えます。永続化したい場合は Railway の **Volume** を設定するか、PostgreSQL プラグインなどを利用してください。
