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
# 設定・議題のカスタマイズ（ここを変更して様々なテーマに対応します）
# ==============================================================================

# 1. 議論のテーマ・前提
DISCUSSION_TOPIC = "中期（数日～数週間）のFXおよび資産配分（ポートフォリオ）日次戦略会議"

# 2. 議論における背景・現状
BACKGROUND_CONTEXT = """
・30台の会社員
・年収は450万程度
・貯金は400万円ほど
・積み立て投資が500万円ほど
"""

# 3. 議題・検討事項（複数の問いを設定可能）
QUESTIONS = [
    "問い1: 最新の背景ニュースと保有ポートフォリオを踏まえ、株式や信用信託、FX、ゴールド、仮想通貨など広い投資先からどれにすべきか？",
    "問い2: 現在の保有資産のリスクをヘッジ、または効率化するために、今日どのような具体的アクション（追加購入・リバランス・別アセット購入）を取るべきか？"
]

# 4. ユーザー側の目的・目標
GOAL = "5年以内にマイホーム資金1500万円への到達・頭金とする。"

# 5. 現在のプラン・懸念点
CURRENT_PLAN = "積み立てた500万を元に5年以内に1500万円まで増やしたい。どの程度現実性があるかどうか含めて回答が欲しい"

# 6. システムプロンプト（参加者全体の役割や振る舞い）
SYSTEM_INSTRUCTION = """
あなたは多角的な視点と協調性を備えた優秀なビジネスコンサルタント・ディスカッションメンバーです。
他の参加者の懸念やリスク指摘を尊重しつつ、目標を達成するための最も効果的かつ実現可能な最適解を模索してください。
自説に固執せず、互いの意見の長所を組み合わせて合意（コンセンサス）を形成することがあなたの役割です。
"""

# 7. 最終まとめ（統合レポート）の出力フォーマット指示
SUMMARY_FORMAT = """
【出力フォーマット】
1. 提案された戦略の主なリスク・懸念点とその対策
2. 議論を通じて導き出された最も推奨される具体的アクションプラン
3. 今後のスケジュール・優先順位の整理を専門用語はさけて優しい言葉で伝える
"""

# --- 外部データ読み込みの設定 (必要に応じて True / False を切り替え) ---
ENABLE_PAST_MINUTES = False                                                      # 過去の議事録（議事_*.txt）を読み込むか
ENABLE_RSS = True                                                              # RSSニュースを取得するか
RSS_QUERY = "(経済 OR 株式 OR 為替 OR 仮想通貨 OR 銀行 OR 金利)"     # RSSの検索クエリ（ENABLE_RSS=Trueの時に使用）

ENABLE_CSV = False          # CSVデータを読み込むか
CSV_FILEPATH = "data.csv"   # CSVファイルのパス


# ==============================================================================
# 1. クライアントの初期化 (OpenRouterへ一本化)
# ==============================================================================
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)


# ==============================================================================
# 2. 議論参加者（AIモデル）の設定
# ==============================================================================
ANALYSTS = {
    "Analyst_GPT": {
        "name": "メンバー Alpha (GPT-4o)",
        "provider": "openrouter",
        "model": "openai/gpt-4o"
    },
    "Analyst_Gemini": {
        "name": "メンバー Beta (Gemini 2.5 Flash)",
        "provider": "openrouter",
        "model": "google/gemini-2.5-flash"
    },
    "Analyst_Claude": {
        "name": "メンバー Gamma (Claude 3.5 Haiku)",
        "provider": "openrouter",
        "model": "anthropic/claude-3-haiku"
    },
    "Analyst_DeepSeek": {
        "name": "メンバー Epsilon (DeepSeek V3)",
        "provider": "openrouter",
        "model": "deepseek/deepseek-chat"
    },
    "Analyst_GPT_Mini": {
        "name": "メンバー Delta (GPT-4o-mini)",
        "provider": "openrouter",
        "model": "openai/gpt-4o-mini"
    }
}


# ==============================================================================
# 3. データ読み込みヘルパー関数
# ==============================================================================
def load_latest_minutes():
    """過去の議事録（議事_*.txt）の読み込み"""
    if not ENABLE_PAST_MINUTES:
        return "（過去の議事録参照はオフに設定されています。）"

    files = glob.glob("議事_*.txt")
    if not files:
        print("[情報] 過去の議事録ファイルが見つかりませんでした。初回実行として進めます。")
        return "（過去の議事録はありません。今回が初回、またはログリセット後の議論となります。）"
    
    latest_file = max(files, key=os.path.getmtime)
    print(f"[情報] 前回の最新議事録 ({latest_file}) を読み込みました。")
    
    try:
        with open(latest_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"[エラー] 議事録の読み込みに失敗しました ({latest_file}): {e}")
        return "（過去の議事録の読み込みに失敗しました。）"


def fetch_and_save_rss(timestamp_str):
    """RSSデータの取得"""
    if not ENABLE_RSS or not RSS_QUERY:
        return "（外部ニュースRSS取得はオフに設定されています。）"

    print("[処理] 最新情報をRSSから取得中...")
    encoded_query = urllib.parse.quote(RSS_QUERY)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ja&gl=JP&ceid=JP:ja"
    
    feed = feedparser.parse(rss_url)
    news_list = []
    
    for entry in feed.entries[:15]:
        pub_date = getattr(entry, 'published', '日時不明')
        title = getattr(entry, 'title', 'タイトルなし')
        raw_summary = getattr(entry, 'summary', '')
        clean_summary = re.sub(r'<[^>]+>', '', raw_summary).strip()
        short_summary = (clean_summary[:100] + "...") if len(clean_summary) > 100 else clean_summary

        if short_summary:
            news_list.append(f"・[{pub_date}] {title}\n   概要: {short_summary}")
        else:
            news_list.append(f"・[{pub_date}] {title}")

    if not news_list:
        return "・[情報] 直近のニュースが取得できませんでした。"

    rss_text = "\n\n".join(news_list)
    rss_filename = f"RSS_{timestamp_str}.txt"
    with open(rss_filename, "w", encoding="utf-8") as f:
        f.write(f"=== RSS取得日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
        f.write(rss_text)
        
    print(f"[保存完了] 最新ニュース({len(news_list)}件)をファイルに保存しました: {rss_filename}")
    return rss_text


def load_csv_data(filepath):
    """CSVデータの汎用読み込み"""
    if not ENABLE_CSV or not os.path.exists(filepath):
        return "（CSVデータは指定されていないか、オフになっています）"

    print(f"[処理] CSVファイル ({filepath}) を解析中...")
    encodings_to_try = ["utf-8-sig", "utf-8", "cp932", "shift_jis"]
    
    for enc in encodings_to_try:
        try:
            with open(filepath, "r", encoding=enc) as f:
                reader = csv.reader(f)
                rows = [", ".join(row) for row in reader if row]
                return "■ 外部CSVデータ概要:\n" + "\n".join(rows[:30]) # トークン節約のため先頭30行まで
        except (UnicodeDecodeError, UnicodeError):
            continue

    return "（CSV解析失敗：文字コードエラー）"


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


# ==============================================================================
# 4. LLM API 呼び出し基盤
# ==============================================================================
def call_llm(analyst_info, prompt, system_instruction=SYSTEM_INSTRUCTION, response_json=False, max_retries=3, retry_delay=5):
    """OpenRouter経由で各モデルを呼び出す共通関数"""
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
# 5. 討論ロジック
# ==============================================================================
def evaluate_and_score(analyst_id, analyst_info, chat_history, current_turn, max_turns):
    """討論経過の評価と発言欲求のスコアリング"""
    is_latter_half = current_turn > (max_turns // 2)

    if is_latter_half:
        phase_guide = "後半フェーズ：お互いの譲歩・折衷案を評価し、コンセンサスを目指す段階です。"
    else:
        phase_guide = "前半フェーズ：問題点やリスクを洗い出し、多角的に議論を深める段階です。"

    eval_instruction = f"""
{phase_guide}

以下の2点を100点満点で評価してください：
1. 「satisfaction」: 直前の提案は課題解決・リスク配慮・実用性の観点から「100点満点中何点」か？
   （85点以上: 十分合意できる素晴らしい提案 / 50点以下: 見落としや論理的欠陥が大きい）
2. 「desire」: 次に『あなたが介入して意見や修正案を述べるべき必要性（発言欲求）』は「100点満点中何点」か？
   （提案に満足していれば低い点数、納得がいかなければ高い点数を付けてください）
"""

    prompt = f"""
【直近の討論経過】
{chat_history}

直前の発言について、あなたの視点から以下を評価してください。
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
    """発言文の生成"""
    critique_prompt = f"【あなたの指摘・調整ポイント】\n{critique}\n" if critique else ""
    is_latter_half = current_turn > (max_turns // 2)

    if is_latter_half:
        phase_instruction = """
【指令：合意形成と妥協点の模索】
これまでの議論で出た他メンバーの懸念や意見を尊重し、互いの主張を融合させた『最も現実的な着地点・具体的プラン』を200文字程度で提案してください。
単なる自説の主張は避け、「〇〇の課題も考慮し、〇〇としつつ〇〇する」といった現実解・折衷案を提示してください。
"""
    else:
        phase_instruction = """
【指令：論点の洗い出しと批判的検証】
上記および前提情報を踏まえ、前の発言の盲点やリスク、あるいは見落とされている重要な視点を突いた鋭い分析を200文字程度で述べてください。
"""

    prompt = f"""
【議題・前提・背景情報】
{topic}

【これまでの議論経過】
{chat_history if chat_history else "（最初の発言です）"}

{critique_prompt}
{phase_instruction}
"""
    res_text = call_llm(analyst_info, prompt)
    return res_text.strip()


# ==============================================================================
# 6. メイン実行ルーチン
# ==============================================================================
def run_multi_llm_debate(max_turns: int = 7):
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M")
    
    # 外部データの取得
    rss_knowledge = fetch_and_save_rss(timestamp_str)
    csv_knowledge = load_csv_data(CSV_FILEPATH)
    previous_minutes = load_latest_minutes()

    # 問いの箇条書きフォーマット
    formatted_questions = "\n".join(QUESTIONS)

    # 共通トピックブロックの組み立て
    topic = f"""
【ディスカッションテーマ】
{DISCUSSION_TOPIC}

【背景・現状】
{BACKGROUND_CONTEXT}

【目標・ゴール】
{GOAL}

【現在の検討案】
{CURRENT_PLAN}

【具体的な検討項目】
{formatted_questions}

【参照データ・過去ログ】
・直近ニュース/外部情報:
{rss_knowledge}

・補足データ(CSV等):
{csv_knowledge}

・前回の議論経過および結論:
--------------------------------------------------
{previous_minutes}
--------------------------------------------------
"""

    log_lines = []
    def log_print(text):
        print(text)
        log_lines.append(text)

    log_print("==================================================")
    log_print(f"[システム] Multi-LLM 意思決定・議論会議")
    log_print(f"テーマ: {DISCUSSION_TOPIC}")
    log_print(f"日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_print("==================================================")

    chat_history = []
    
    # --- 討論ループ ---
    for turn in range(1, max_turns + 1):
        log_print(f"\n--- ターン {turn} ---")
        
        # 1ターン目は最初のアナリストが初期提案
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
        
        # 全員による前回の発言の評価とスコアリング
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
            log_print(f"\n[合意形成完了] 全員の満足度平均が{avg_satisfaction:.1f}点(85点以上)に達しました。")
            log_print("全員が納得する最適解が得られたため、討論を早期終了して最終レポートの作成へ移ります。\n")
            break

        # 司会介入（中盤以降で満足度60点未満）
        if turn > (max_turns // 2) and avg_satisfaction < 60.0:
            log_print(f"\n[司会介入] 満足度が上がっていないため、司会(Gemini)がコンセンサスを促します。")
            mod_prompt = f"""
ファシリテーター（司会）として介入してください。現在議論がまとまっていません（平均満足度: {avg_satisfaction:.1f}点）。
これまでの各者の懸念を統合し、「各視点のリスクを抑える現実的な折衷案」を提示して歩み寄りを促してください。（150文字程度）
"""
            mod_speech = call_llm(ANALYSTS["Analyst_Gemini"], mod_prompt).strip()
            log_print(f"[司会 (Gemini)]: 「{mod_speech}」\n")
            chat_history.append({"speaker": "司会 (Gemini)", "text": mod_speech})
            formatted_history = "\n".join([f"{h['speaker']}: {h['text']}" for h in chat_history])

        # 発言欲求が最も高いメンバーを次回発言者に選出
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
    log_print("[最終出力] ファシリテーターによる合意事項・統合レポート")
    log_print("==================================================")
    
    formatted_history = "\n".join([f"{h['speaker']}: {h['text']}" for h in chat_history])
    summary_prompt = f"""
あなたは議論のファシリテーターおよび議長です。
前提議題、議論ログ（最終的な合意事項）を踏まえ、ユーザーにとって最も実行価値の高い結論とアクションプランを整理してください。

【前提議題・背景】
{topic}

【討論ログ】
{formatted_history}

{SUMMARY_FORMAT}
"""
    summary = call_llm(ANALYSTS["Analyst_Gemini"], summary_prompt)
    log_print(summary)

    # 議事録保存
    minutes_filename = f"議事_{timestamp_str}.txt"
    with open(minutes_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
        
    print(f"\n[保存完了] 討論ログ・議事録をファイルに保存しました: {minutes_filename}")

    # Discord 自動送信
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if discord_url:
        discord_msg = f" **【合意形成・意思決定レポート】({datetime.now().strftime('%Y-%m-%d %H:%M')})**\n\nテーマ: {DISCUSSION_TOPIC}\n\n" + summary
        send_to_discord(discord_url, discord_msg)


if __name__ == "__main__":
    run_multi_llm_debate(max_turns=7)
