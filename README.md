# Multi-LLM 投資戦略・ポートフォリオ最適化エージェント

複数のAIアナリスト（GPT-4o, Gemini, Claude, DeepSeek）が最新ニュースと保有ポートフォリオを踏まえて自動で議論を行い、コンセンサス（合意）に基づいた日次投資戦略レポートを生成・Discordへ自動送信するスクリプトです。

---

## 🛠️ 事前準備

### 1. 設定ファイルの作成 (`.env`)
プロジェクトのルートディレクトリに `.env` ファイルを作成し、各種キーを設定してください。

```env
# OpenRouter API Key (必須)
OPENROUTER_API_KEY=your_openrouter_api_key_here

# Discord Webhook URL (任意: レポートをDiscordへ送信したい場合)
DISCORD_WEBHOOK_URL=your_discord_webhook_url_here
