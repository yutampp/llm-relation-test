import os
import json
import re
import time
import csv
import random
import glob
import urllib.parse
import urllib.request
from datetime import datetime
import feedparser
from dotenv import load_dotenv
from openai import OpenAI

# 環境変数の読み込み (.env ファイルから API KEY や Webhook URL を取得)
load_dotenv()


# ==============================================================================
# 分析設定・議題カスタマイズ
# ==============================================================================
ANALYSIS_TARGET = "中期（数日～数週間）のFXおよび資産配分（ポートフォリオ）日次戦略会議。"

QUESTION_1 = "最新の背景ニュースと保有ポートフォリオを踏まえ、株式や信用信託、FX、ゴールド、仮想通貨など広い投資先からどれにすべきか？"

QUESTION_2 = "現在の保有資産のリスクをヘッジ、または効率化するために、今日どのような具体的アクション（追加購入・リバランス・別アセット購入）を取るべきか？"

MY_GOAL = "5年以内の1500万円への到達。および、それをもとに地方都市での単身用マイホーム購入（ジャパンドームハウス）"

MY_PLAN = "投資資金として240万円増額を検討中"


# ==============================================================================
# 1. クライアントの初期化 (OpenRouterへ一本化)
# ==============================================================================
# Google Direct APIの従量課金を避け、すべてOpenRouter経由で事前チャージ管理に統一
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)


# ==============================================================================
# 2. アナリスト（AIモデル）の設定とシステムプロンプト
# ==============================================================================
ANALYSTS = {
    "Analyst_GPT": {
        "name": "アナリスト Alpha (ChatGPT / GPT-4o)",
        "provider": "openrouter",
        "model": "openai/gpt-4o"
    },
    "Analyst_Gemini": {
        "name": "アナリスト Beta (Gemini 2.5 Flash)",
        "provider": "openrouter",
        "model": "google/gemini-2.5-flash"  # コスト削減のため2.5-flashをOpenRouter経由で利用
    },
    "Analyst_Claude": {
        "name": "アナリスト Gamma (Claude 3.5 Sonnet)",
        "provider": "openrouter",
        "model": "anthropic/claude-3-haiku"
    },
    "Analyst_DeepSeek": {
        "name": "アナリスト Epsilon (DeepSeek V3)",
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat"
    },
    "Analyst_GPT_Mini": {
        "name": "アナリスト Delta (ChatGPT / GPT-4o-mini)",
        "provider": "openrouter",
        "model": "openai/gpt-4o-mini"
    }
}

SYSTEM_INSTRUCTION = """
あなたは協調性と客観性を兼ね備えた優秀な金融市場アナリストです。
他のアナリストの懸念やリスク指摘を尊重しつつ、ユーザー（1500万円目標）にとって最も安全かつ効果的なポートフォリオ全体の最適解を模索してください。
自説に固執せず、互いの意見の長所を組み合わせて合意（コンセンサス）を形成することがあなたの役割です。
"""


# ==============================================================================
# 3. 過去ログ読み込み関数 (コンテキスト継続・整合性維持用)
# ==============================================================================
def load_latest_minutes():
    """
    カレントディレクトリ内の『議事_*.txt』を検索し、
    最終更新日時が最も新しい（最新の）ファイルを自動取得・読み込む関数。
    """
    files = glob.glob("議事_*.txt")
    
    if not files:
        print("[情報] 過去の議事録ファイルが見つかりませんでした。初回実行として進めます。")
        return "（過去の議事録はありません。今回が初回、またはログリセット後の議論となります。）"
    
    latest_file = max(files, key=os.path.getmtime)
    print(f"[情報] 前回の最新議事録 ({latest_file}) を読み込みました。")
    
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return content
    except Exception as e:
        print(f"[エラー] 議事録の読み込みに失敗しました ({latest_file}): {e}")
        return "（過去の議事録の読み込みに失敗しました。）"


# ==============================================================================
# 4. 外部連携・データ収集関数 (Discord送信 & RSS取得 & ポートフォリオ解析)
# ==============================================================================
def load_portfolio_csv(filepath="portfolio.csv"):
    """
    ユーザー提供のCSV形式から保有資産データを自動解析する関数。
    """
    if not os.path.exists(filepath):
        print(f"[スキップ] {filepath} が見つかりません。ポートフォリオ未入力で続行します。")
        return "（ポートフォリオデータなし：新規資金によるエントリーのみで分析）"

    print(f"[処理] ポートフォリオファイル ({filepath}) を解析中...")
    
    encodings_to_try = ["cp932", "shift_jis", "utf-8-sig", "utf-8"]
    f = None
    
    for enc in encodings_to_try:
        try:
            f = open(filepath, "r", encoding=enc)
            f.readline()
            f.seek(0)
            break
        except (UnicodeDecodeError, UnicodeError):
            if f:
                f.close()
            f = None

    if f is None:
        print(f"[エラー] ファイルの文字コードを判定できませんでした: {filepath}")
        return "（ポートフォリオ解析失敗：文字コードエラー）"

    holdings = []
    total_eval = 0.0

    try:
        with f:
            reader = csv.reader(f)
            in_fund_section = False
            
            for row in reader:
                if not row:
                    continue
                
                if any("ファンド名" in cell for cell in row):
                    in_fund_section = True
                    continue
                
                if any("投資信託" in cell and "合計" in cell for cell in row) or (row and "合計" in row[0]):
                    break

                if in_fund_section and len(row) >= 10:
                    fund_name = row[0].strip()
                    try:
                        gain_loss = float(row[7].replace(",", ""))
                        eval_value = float(row[9].replace(",", ""))
                        holdings.append({
                            "name": fund_name,
                            "eval": eval_value,
                            "gain_loss": gain_loss
                        })
                        total_eval += eval_value
                    except ValueError:
                        continue

        if not holdings:
            return "（ポートフォリオ解析失敗：該当データなし）"

        portfolio_summary = [f"■ 現在保有ポートフォリオ (評価額合計: JPY {total_eval:,.0f})"]
        for h in holdings:
            ratio = (h["eval"] / total_eval) * 100 if total_eval > 0 else 0
            portfolio_summary.append(
                f" ・{h['name']}: 評価額 JPY {h['eval']:,.0f} (構成比 {ratio:.1f}%) | 評価損益: JPY {h['gain_loss']:+,.0f}"
            )
        
        return "\n".join(portfolio_summary)

    except Exception as e:
        print(f"[エラー] CSV読み込み失敗: {e}")
        return "（ポートフォリオ解析中にエラーが発生しました）"


def send_to_discord(webhook_url, text):
    """Discord Webhookへレポートを分割送信する関数"""
    webhook_url = webhook_url.strip() if webhook_url else None
    if not webhook_url:
        print("[スキップ] DISCORD_WEBHOOK_URL が未設定のため、Discord送信をスキップします。")
        return

    print("\n[処理] Discordへレポートを送信中...")
    max_length = 1900
    chunks = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    
    for chunk in chunks:
        payload = {"content": chunk}
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) StrategyAgent/1.0'
        }
        req = urllib.request.Request(webhook_url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        try:
            with urllib.request.urlopen(req):
                pass
            time.sleep(0.5)
        except Exception as e:
            print(f"[エラー] Discord送信失敗: {e}")
            
    print("[完了] Discordへのレポート送信が完了しました！")


def fetch_and_save_rss(timestamp_str):
    """Google News から直近の最新 RSS を取得・保存する関数"""
    print("[処理] 最新のファイナンスニュースをRSSから取得中...")
    
    query = "FX OR ドル円 OR 為替 OR 株式市場 when:3d"
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ja&gl=JP&ceid=JP:ja"
    
    feed = feedparser.parse(rss_url)
    news_list = []
    max_items = 15
    
    for entry in feed.entries:
        pub_date = getattr(entry, 'published', '日時不明')
        title = getattr(entry, 'title', 'タイトルなし')
        raw_summary = getattr(entry, 'summary', '')
        clean_summary = re.sub(r'<[^>]+>', '', raw_summary).strip()
        short_summary = (clean_summary[:100] + "...") if len(clean_summary) > 100 else clean_summary

        if any(ignore_word in title for ignore_word in ["いつまで", "対策方法", "初心者", "おすすめ"]):
            continue
            
        if short_summary:
            news_list.append(f"・[{pub_date}] {title}\n   概要: {short_summary}")
        else:
            news_list.append(f"・[{pub_date}] {title}")
        
        if len(news_list) >= max_items:
            break
        
    if not news_list:
        news_list.append("・[警告] 直近のニュースが取得できませんでした。")

    rss_text = "\n\n".join(news_list)
    rss_filename = f"RSS_{timestamp_str}.txt"
    with open(rss_filename, "w", encoding="utf-8") as f:
        f.write(f"=== RSS取得日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
        f.write(rss_text)
        
    print(f"[保存完了] 最新ニュース({len(news_list)}件)をファイルに保存しました: {rss_filename}")
    return rss_text


# ==============================================================================
# 5. LLM API 呼び出し基盤 (OpenRouterへ統一・自動リトライ)
# ==============================================================================
def call_llm(analyst_info, prompt, system_instruction=SYSTEM_INSTRUCTION, response_json=False, max_retries=3, retry_delay=5):
    """OpenRouter経由で各モデル（Gemini含む）を呼び出す安全な共通関数"""
    model = analyst_info["model"]

    for attempt in range(1, max_retries + 1):
        try:
            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ]
            kwargs = {"model": model, "messages": messages}
            if response_json:
                kwargs["response_format"] = {"type": "json_object"}
                
            res = openrouter_client.chat.completions.create(**kwargs)
            return res.choices[0].message.content

        except Exception as e:
            print(f"\n[一時エラー] API呼び出し失敗 ({analyst_info['name']}): {e}")
            if attempt < max_retries:
                print(f"--> {retry_delay}秒後に自動再試行します... (試行 {attempt}/{max_retries})")
                time.sleep(retry_delay)
            else:
                print(f"--> 最大リトライ回数({max_retries}回)に達したため、処理を中断します。")
                raise e


# ==============================================================================
# 6. 討論ロジック (スコアリング最適化・トークン節約版)
# ==============================================================================
def evaluate_and_score(analyst_id, analyst_info, chat_history, current_turn, max_turns):
    """
    【トークン節約版】
    ニュースや過去の巨大議事録を含めず、「直近の議論ログ」のみを渡してスコアリング。
    送信トークン量を約80%削減。
    """
    is_latter_half = current_turn > (max_turns // 2)

    if is_latter_half:
        phase_guide = "後半フェーズ：お互いの譲歩・折衷案を評価し、コンセンサスを目指す段階です。"
    else:
        phase_guide = "前半フェーズ：問題点やリスクを洗い出し、多角的に議論を深める段階です。"

    eval_instruction = f"""
{phase_guide}

以下の2点を100点満点で評価してください：
1. 「satisfaction」: 直前の提案はリスク考慮・バランス・実用性の観点から「100点満点中何点」か？
   （85点以上: 十分合意できる素晴らしい提案 / 50点以下: 見落としや論理的欠陥が大きい）
2. 「desire」: 次に『あなたが介入して意見や修正案を述べるべき必要性（発言欲求）』は「100点満点中何点」か？
   （提案に満足していれば低い点数、納得がいかなければ高い点数を付けてください）
"""

    # 直近の会話ログのみをプロンプトに組み込む（軽量化）
    prompt = f"""
【直近の討論経過】
{chat_history}

直前の発言について、アナリストとしての視点から以下を評価してください。
{eval_instruction}

以下のJSONフォーマットのみで出力してください。
{{"satisfaction": 数値(0-100), "desire": 数値(0-100), "critique": "評価・理由または修正ポイント（50文字程度）"}}
"""
    try:
        res_text = call_llm(analyst_info, prompt, response_json=True)
        try:
            res_data = json.loads(res_text)
            sat = int(res_data.get("satisfaction", 50))
            des = int(res_data.get("desire", 50))
            crit = res_data.get("critique", "論点整理")
            return sat, des, crit
        except json.JSONDecodeError:
            m_sat = re.search(r'"satisfaction"\s*:\s*(\d+)', res_text)
            m_des = re.search(r'"desire"\s*:\s*(\d+)', res_text)
            sat = int(m_sat.group(1)) if m_sat else 50
            des = int(m_des.group(1)) if m_des else 50
            return sat, des, "スコア抽出（JSON補正）"
    except Exception as e:
        print(f"[{analyst_id}] 判定最終エラー: {e}")
        return 50, 50, "エラー代替"


def generate_refinement_speech(analyst_info, topic, chat_history, critique="", current_turn=1, max_turns=7):
    """アナリストごとの議論・反論・折衷発言を生成する関数"""
    critique_prompt = f"【あなたの指摘・調整ポイント】\n{critique}\n" if critique else ""
    is_latter_half = current_turn > (max_turns // 2)

    if is_latter_half:
        phase_instruction = """
【指令：合意形成と妥協点の模索】
これまでの議論で出た他アナリストの懸念（リスク指摘）を真摯に受け止め、互いの主張を融合させた『最も現実的な妥協点・具体的ポートフォリオ調整案』を200文字程度で提案してください。
単なる自説の主張は避け、「〇〇のリスクも考慮し、〇〇%はヘッジしつつ〇〇%は維持する」といった現実解・折衷案を提示してください。
"""
    else:
        phase_instruction = """
【指令：論点の洗い出しと批判的検証】
上記と『ユーザーの現在の保有ポートフォリオ』を踏まえ、前の発言の盲点やリスクを突いた鋭い分析を200文字程度で述べてください。
"""

    prompt = f"""
【議題・背景情報・ポートフォリオ】
{topic}

【これまでの議論経過】
{chat_history if chat_history else "（最初の発言です）"}

{critique_prompt}
{phase_instruction}
"""
    res_text = call_llm(analyst_info, prompt)
    return res_text.strip()


# ==============================================================================
# 7. メイン実行ルーチン
# ==============================================================================
def run_fx_debate(max_turns: int = 7):
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
    
    # 1. RSSニュースの取得
    rss_knowledge = fetch_and_save_rss(timestamp_str)
    
    # 2. ポートフォリオCSVの解析
    portfolio_knowledge = load_portfolio_csv("portfolio.csv")
    
    # 3. 前回の最新議事録の取得
    previous_minutes = load_latest_minutes()

    # 共通トピックの構築
    topic = f"""
【最新背景ニュース】
{rss_knowledge}

【ユーザーの現在保有ポートフォリオ】
{portfolio_knowledge}

【前回の議論経過および最終結論】
--------------------------------------------------
{previous_minutes}
--------------------------------------------------

【分析対象】{ANALYSIS_TARGET}
【問い1】{QUESTION_1}
【問い2】{QUESTION_2}
【目標】{MY_GOAL}
【予定】{MY_PLAN}
"""

    log_lines = []
    def log_print(text):
        print(text)
        log_lines.append(text)

    log_print("==================================================")
    log_print("[システム] Multi-LLM 投資戦略・ポートフォリオ最適化会議 (コスト最適化版)")
    log_print(f"日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_print("==================================================")

    chat_history = []
    
    # --- 討論ループ ---
    for turn in range(1, max_turns + 1):
        log_print(f"\n--- ターン {turn} ---")
        
        if turn == 1:
            speaker_info = ANALYSTS["Analyst_GPT"]
            speech = generate_refinement_speech(speaker_info, topic, "", current_turn=turn, max_turns=max_turns)
            log_print(f"\n[発言] 【{speaker_info['name']}】(初期提案):")
            log_print(f"「{speech}」\n")
            chat_history.append({"speaker": speaker_info['name'], "text": speech})
            time.sleep(1)
            continue

        satisfactions = {}
        desires = {}
        critiques = {}
        formatted_history = "\n".join([f"{h['speaker']}: {h['text']}" for h in chat_history])
        
        # 全アナリストによる直前発言の評価と発言欲求のスコアリング (軽量化プロンプトを使用)
        for a_id, a_info in ANALYSTS.items():
            sat, des, critique = evaluate_and_score(a_id, a_info, formatted_history, turn, max_turns)
            satisfactions[a_id] = sat
            desires[a_id] = des
            critiques[a_id] = critique
            
            log_print(f" |- [{a_info['name']}] 満足度: {sat}/100点 | 発言欲求: {des}/100点 | コメント: {critique}")
            time.sleep(0.3)

        avg_satisfaction = sum(satisfactions.values()) / len(satisfactions)
        log_print(f" |- [コンセンサス状況] 全員の平均満足度: {avg_satisfaction:.1f} / 100点")

        # 早期終了判定（平均85点以上）
        if avg_satisfaction >= 85.0:
            log_print(f"\n[合意形成完了] 全アナリストの満足度平均が{avg_satisfaction:.1f}点(85点以上)に達しました。")
            log_print("全員が納得する最適解が得られたため、討論を早期終了して最終レポートの作成へ移ります。\n")
            break

        # 司会介入（中盤以降で60点未満）
        if turn > (max_turns // 2) and avg_satisfaction < 60.0:
            log_print(f"\n[司会介入] 満足度が上がっていないため、司会(Gemini)がコンセンサスを促します。")
            mod_prompt = f"""
司会として介入してください。現在議論がまとまっていません（平均満足度: {avg_satisfaction:.1f}点）。
これまでの各者の懸念を統合し、「双方のリスクを抑える現実的な折衷案」を提示して歩み寄りを促してください。（150文字程度）
"""
            mod_speech = call_llm(ANALYSTS["Analyst_Gemini"], mod_prompt).strip()
            log_print(f"[司会 (Gemini)]: 「{mod_speech}」\n")
            chat_history.append({"speaker": "司会 (Gemini)", "text": mod_speech})
            formatted_history = "\n".join([f"{h['speaker']}: {h['text']}" for h in chat_history])

        # 次の発言者を選出
        max_desire = max(desires.values())
        top_candidates = [a_id for a_id, des in desires.items() if des == max_desire]
        
        last_speaker_id = [a_id for a_id, info in ANALYSTS.items() if info["name"] == chat_history[-1]["speaker"]]
        if len(top_candidates) > 1 and last_speaker_id and last_speaker_id[0] in top_candidates:
            top_candidates.remove(last_speaker_id[0])

        best_analyst_id = random.choice(top_candidates)
        speaker_info = ANALYSTS[best_analyst_id]

        speech = generate_refinement_speech(speaker_info, topic, formatted_history, critiques[best_analyst_id], turn, max_turns)
        
        label = "折衷・改善提案" if turn > (max_turns // 2) else "検証・批判提案"
        log_print(f"\n[発言] 【{speaker_info['name']}】({label} / 発言欲求: {max_desire}点):")
        log_print(f"「{speech}」\n")
        chat_history.append({"speaker": speaker_info['name'], "text": speech})
        time.sleep(1)

    # --- 最終統合レポート ---
    log_print("==================================================")
    log_print("[最終出力] 司会（Gemini）による統合ポートフォリオ戦略レポート")
    log_print("==================================================")
    
    formatted_history = "\n".join([f"{h['speaker']}: {h['text']}" for h in chat_history])
    mod_prompt = f"""
あなたはチーフ・マーケット・ストラテジストです。
最新背景ニュース、討論ログ（最終的な合意事項）、および【ユーザーの現在保有ポートフォリオ】を踏まえ、明確な最終意思決定と診断を提示してください。

【前提議題・ニュース・ポートフォリオ】
{topic}

【討論ログ】
{formatted_history}

【出力フォーマット】
1. 現在の保有ポートフォリオのリスク診断（例: 米国株・ドルリスクへの偏り、ボラティリティ評価）
2. ドル円（中期）に対する最終結論（「買い」「売り」「見送り」のいずれか）
3. 推奨する具体的補強アセット（例: 米ドル建てポジション、ヘッジ資産ゴールド、現金等）
4. 具体的のアクションプラン（保有ファンドをどう維持・調整し、どう新規ポジションを作るか）
"""
    summary = call_llm(ANALYSTS["Analyst_Gemini"], mod_prompt)
    log_print(summary)

    # 議事録保存
    minutes_filename = f"議事_{timestamp_str}.txt"
    with open(minutes_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
        
    print(f"\n[保存完了] 討論ログ・議事録をファイルに保存しました: {minutes_filename}")

    # Discord 自動送信
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if discord_url:
        discord_msg = f" **【ポートフォリオ最適化・投資戦略レポート】({datetime.now().strftime('%Y-%m-%d %H:%M')})**\n\n" + summary
        send_to_discord(discord_url, discord_msg)


if __name__ == "__main__":
    run_fx_debate(max_turns=7)
