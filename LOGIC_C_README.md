# Logic C: AI一次面接システム (MVP)

## 概要
AIが自動で一次面接を行うシステムです。
候補者が予約日時を選択すると、指定時刻にシステムから電話がかかってきます。
質問への回答は録音・文字起こしされ、管理画面で確認できます。

## 機能一覧
- **候補者**: 固有URLからの日時予約、SMS/Email通知
- **AI面接**: 自動架電、質問読み上げ、回答録音(各180秒)、中断復帰
- **管理者**: 候補者CSV一括登録、質問セット管理、録音・文字起こし確認
- **システム**: 不通時のリトライ(3回)、データ自動削除(オプション)

## エンドポイント一覧

### Public
- `GET /book?token={token}`: 予約画面
- `POST /book`: 予約確定
- `POST /voice/call` (Webhook): 架電開始
- `POST /voice/question` (Webhook): 質問再生
- `POST /voice/record` (Webhook): 録音保存
- `POST /voice/status` (Webhook): 通話ステータス受信（リトライ判断）

### Admin (Basic Auth: admin / pines)
- `POST /admin/candidates/upload`: CSVアップロード
  - フォーマット: `氏名,電話番号,メールアドレス,質問セット名(任意)`
- `POST /admin/question-sets`: 質問セット作成
- `POST /admin/question-sets/{id}/questions`: 質問追加
- `GET /admin/interviews`: 予約状況確認

## 環境変数設定
以下の環境変数をRailway等に設定してください。

```ini
DATABASE_URL=postgresql://user:pass@host:port/dbname
OPENAI_API_KEY=sk-...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+8150... (発信元電話番号)
TWILIO_SMS_FROM_NUMBER=+1... (SMS送信元)
SENDGRID_API_KEY=SG...
SENDGRID_FROM_EMAIL=pineseigyousyo@gmail.com
BASE_URL=https://your-railway-app-url.up.railway.app
```

## 初期セットアップ手順

1. **質問セットの作成**
   - APIクライアント(Postman等)またはSwagger UI (`/docs`) から `/admin/question-sets` を叩いてセットを作成する（例: "営業"）。
   - 作成したセットIDに対して `/admin/question-sets/{id}/questions` で質問を追加する。

2. **候補者の登録**
   - `/admin/candidates/upload` にCSVをアップロードする。
   - `question_set_id` が必要な場合はCSVの4列目にセット名を指定するか、DBを直接編集する（MVP仕様）。

3. **予約と面接**
   - 登録されたメールアドレス/SMSにURLが届くので予約する。
   - 時間になると電話がかかってくる。

## 補足
- 録音データはTwilio上に保存され、URLのみDBに記録されます。
- 文字起こし(STT)は録音完了後、非同期で実行されます。
- `logic-a` や `logic-b` の古いコードは `legacy/` ディレクトリに退避されています。

## データ永続化に関する重要事項
現在の構成（SQLite）では、アプリケーションの再デプロイ（更新）を行うたびに **データベースのデータ（候補者、面接履歴、ログなど）がリセット（削除）されます**。
本番運用や、長期間のデータ保持が必要な段階になった際は、PostgreSQLなどの外部データベースへの移行が必要です。
**次回本格実装フェーズに入る際に、このデータベース移行について必ず再協議してください。**
