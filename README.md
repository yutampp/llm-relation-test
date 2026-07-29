# Multi-LLM 投資戦略・ポートフォリオ最適化エージェント

複数のAIアナリスト（GPT-4o, Gemini, Claude, DeepSeek）が最新ニュースと保有ポートフォリオを踏まえて自動で議論を行い、コンセンサス（合意）に基づいた日次投資戦略レポートを生成・Discordへ自動送信するスクリプトです。

---

## ⚠️ 注意事項（ご利用前に必ずお読みください）

* **OpenRouter のアカウントおよびクレジットチャージが必須です**
  * 本プログラムはすべてのLLM（Gemini含む）を **OpenRouter** 経由で呼び出す仕様になっています。
  * 実行前に OpenRouter にてアカウントを作成し、**事前にクレジットをチャージ（最低 $5〜 推奨）** の上、APIキーを発行してください。
  * クレジット残高が不足している場合、プログラムの実行時にAPIエラーが発生します。

---

## 🛠️ 事前準備

### 1. 設定ファイルの作成 (.env)
プロジェクトのルートディレクトリに `.env` という名前のファイルを作成し、以下の内容を設定してください。

    OPENROUTER_API_KEY=your_openrouter_api_key_here
    DISCORD_WEBHOOK_URL=your_discord_webhook_url_here

※ DISCORD_WEBHOOK_URL は任意です（Discordへレポートを自動送信したい場合のみ設定）。

### 2. (任意）外部データの準備 (data.csv)
証券会社等からダウンロードしたポートフォリオデータなどを `data.csv` というファイル名でルートディレクトリに配置します。
 app.pyの ---外部データ読み込みの設定 (必要に応じて True / False を切り替え) --- の部分を編集しましょう。

### 3. 自動実行用ファイルの準備 (kick.bat) ※Windowsの場合
Windows環境で毎朝自動実行したい場合は、プロジェクトのルートディレクトリに `kick.bat` という名前のファイルを作成し、以下の内容を記述します。

    @echo off
    cd /d %~dp0
    call venv\Scripts\activate
    python app.py
    pause

---

## 🚀 起動方法

### 手動で実行する場合

ターミナル（またはコマンドプロンプト）を開き、以下の手順で実行します。

1. 仮想環境の作成・有効化

   Mac / Linux の場合:
       python3 -m venv venv
       source venv/bin/activate

   Windows の場合:
       python -m venv venv
       venv\Scripts\activate

2. pipの更新・依存パッケージのインストール（初期セットアップ）

   初回実行時やパッケージの初期化を行う際は、まず pip（パッケージ管理ツール）を最新に更新してから依存ライブラリをインストールします。

       (venv) python -m pip install --upgrade pip
       (venv) pip install -r requirements.txt

3. プログラムの実行

       python app.py

### 自動で毎朝実行する場合 (Windows)

Windowsであれば、作成した `kick.bat` を**タスクスケジューラ**に登録して毎朝（例：朝7:00など）自動で動かす設定をしておくと便利です。

---

## 📁 出力ファイルについて

実行が成功すると、以下のファイルが自動作成・更新されます：

・ RSS_YYYYMMDD_HHMM.txt : 取得した最新のニュース
・ 議事_YYYYMMDD_HHMM.txt : アナリスト同士の討論ログおよび最終レポート（次回実行時に過去コンテキストとして自動読み込みされます）
