# Multi-LLM 投資戦略・ポートフォリオ最適化エージェント

複数のAIアナリスト（GPT-4o, Gemini, Claude, DeepSeek）が最新ニュースと保有ポートフォリオを踏まえて自動で議論を行い、コンセンサス（合意）に基づいた日次投資戦略レポートを生成・Discordへ自動送信するスクリプトです。

---

## 🛠️ 事前準備

### 1. 設定ファイルの作成 (.env)
プロジェクトのルートディレクトリに `.env` という名前のファイルを作成し、以下の内容を設定してください。

    OPENROUTER_API_KEY=your_openrouter_api_key_here
    DISCORD_WEBHOOK_URL=your_discord_webhook_url_here

※ DISCORD_WEBHOOK_URL は任意です（Discordへレポートを自動送信したい場合のみ設定）。

### 2. ポートフォリオデータの準備 (portfolio.csv)
証券会社等からダウンロードしたポートフォリオデータ（CSV形式）を `portfolio.csv` というファイル名でルートディレクトリに配置します。

---

## 🚀 起動方法

ターミナル（またはコマンドプロンプト）を開き、以下の手順で実行します。

### 1. 仮想環境の作成・有効化

Mac / Linux の場合:
    python3 -m venv venv
    source venv/bin/activate

Windows の場合:
    python -m venv venv
    venv\Scripts\activate

### 2. pipの更新・依存パッケージのインストール（初期セットアップ）

初回実行時やパッケージの初期化を行う際は、まず pip（パッケージ管理ツール）を最新に更新してから依存ライブラリをインストールします。

    python -m pip install --upgrade pip
    pip install -r requirements.txt

### 3. プログラムの実行

    python app.py

---

## 📁 出力ファイルについて

実行が成功すると、以下のファイルが自動作成・更新されます：

・ RSS_YYYYMMDD_HHMM.txt : 取得した最新のファイナンスニュース
・ 議事_YYYYMMDD_HHMM.txt : アナリスト同士の討論ログおよび最終レポート（次回実行時に過去コンテキストとして自動読み込みされます）
