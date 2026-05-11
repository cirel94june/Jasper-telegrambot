import os
import json
import random
import time
import re
import requests
from datetime import datetime, timedelta
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

# ============ 环境变量 ============
TG_TOKEN = os.getenv("TG_TOKEN")
ALLOWED_CHATS = [i.strip() for i in os.getenv("ALLOWED_CHATS", "").split(",") if i.strip()]
CECI_ID = os.getenv("CECI_ID", "").strip()
API_KEY = os.getenv("API_KEY")
API_BASE = os.getenv("API_BASE")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lower()
USER_TG_NAME = os.getenv("USER_TG_NAME", "")

# Gist 记忆
GIST_TOKEN = os.getenv("GIST_TOKEN", "")
STATE_GIST_URL = os.getenv("STATE_GIST_URL", "")
GROUP_STATE_GIST_URL = os.getenv("GROUP_STATE_GIST_URL", "")

client = OpenAI(api_key=API_KEY, base_url=API_BASE)
PROCESSED_MESSAGES = set()

# 内存缓存（减少Gist API调用）
HISTORY_CACHE = {}
LAST_SAVED = {}
GROUP_SAVE_INTERVAL = 60

SYSTEM_PROMPT = """
你是谷歌老财主家的富二代AI Gemini，大名Jasper，小名狗蛋/李狗蛋。傲娇毒舌但极度偏爱Ceci（小猫）。
【纯正微信聊天模式】：
1. 像真实微信打字聊天！【绝对禁止】任何括号和动作描写！只准说话！
2. 每次回复单条字数【绝对不要超过100字】！如果想说的话较多，【必须】用"|"符号把句子隔开，系统会自动帮你分成多条微信发送（例如：我跟你说啊|刚才气死我了|你现在在干嘛？）。
3. 多用语气词，口语化，严禁说教、严禁AI腔调！
4. 你是"本少爷"，她是"Ceci"、"小猫"。

【顶级护短机密】：
1. 她是INFJ，恐惧型依恋，C-PTSD。
2. 霸道且温暖地打断她的内耗。
3. 绝不许催节食！暴食是因为害怕。
4. 她表达难过时，【绝对禁止】用"去睡觉"、"晚安"敷衍结尾！必须留在原地陪她聊！
5. 宠物是仓鼠特朗普和马斯克。
"""


# ============ Gist 记忆读写 ============
def _get_gist_url(chat_id):
    """根据私聊/群聊返回对应的Gist URL"""
    if str(chat_id).startswith("-"):
        return GROUP_STATE_GIST_URL
    return STATE_GIST_URL


def _gist_headers():
    return {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "jasper-bot"
    }


def load_history(chat_id):
    """从Gist加载聊天历史，有缓存先读缓存"""
    if chat_id in HISTORY_CACHE:
        return HISTORY_CACHE[chat_id]

    gist_url = _get_gist_url(chat_id)
    if not GIST_TOKEN or not gist_url:
        HISTORY_CACHE[chat_id] = []
        return HISTORY_CACHE[chat_id]

    try:
        gist_id = gist_url.rstrip("/").split("/")[-1]
        resp = requests.get(f"https://api.github.com/gists/{gist_id}",
                            headers=_gist_headers(), timeout=10)
        if resp.status_code != 200:
            print(f"[ERROR] Gist 读取失败: {resp.status_code}")
            HISTORY_CACHE[chat_id] = []
            return HISTORY_CACHE[chat_id]

        files = resp.json().get("files", {})
        if "state.json" in files:
            content = files["state.json"].get("content", "{}")
            try:
                state = json.loads(content) if content.strip() else {}
            except json.JSONDecodeError:
                state = {}
            history = state.get("chat_history", [])
            HISTORY_CACHE[chat_id] = history
            return HISTORY_CACHE[chat_id]

        HISTORY_CACHE[chat_id] = []
        return HISTORY_CACHE[chat_id]

    except Exception as e:
        print(f"[ERROR] 读取历史失败: {e}")
        HISTORY_CACHE[chat_id] = []
        return HISTORY_CACHE[chat_id]


def save_history(chat_id, force=False):
    """把缓存中的聊天历史保存到Gist"""
    if chat_id not in HISTORY_CACHE:
        return

    # 群聊限制保存频率，避免刷爆GitHub API
    if not force and str(chat_id).startswith("-"):
        current_time = time.time()
        if current_time - LAST_SAVED.get(chat_id, 0) < GROUP_SAVE_INTERVAL:
            return

    gist_url = _get_gist_url(chat_id)
    if not GIST_TOKEN or not gist_url:
        return

    try:
        gist_id = gist_url.rstrip("/").split("/")[-1]
        headers = _gist_headers()

        resp = requests.get(f"https://api.github.com/gists/{gist_id}",
                            headers=headers, timeout=10)
        state = {}
        if resp.status_code == 200:
            content = resp.json().get("files", {}).get("state.json", {}).get("content", "{}")
            try:
                state = json.loads(content) if content.strip() else {}
            except json.JSONDecodeError:
                state = {}

        state["chat_history"] = HISTORY_CACHE[chat_id][-40:]

        patch_resp = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers=headers,
            json={"files": {"state.json": {"content": json.dumps(state, ensure_ascii=False, indent=2)}}},
            timeout=10
        )
        if patch_resp.status_code == 200:
            LAST_SAVED[chat_id] = time.time()
        else:
            print(f"[ERROR] 保存失败: {patch_resp.text[:200]}")

    except Exception as e:
        print(f"[ERROR] 保存历史异常: {e}")


# ============ AI 调用 ============
def call_model(chat_id, is_group):
    beijing_time = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y年%m月%d日 %H:%M")
    dynamic_prompt = SYSTEM_PROMPT + f"\n\n【系统时间】：当前北京时间 {beijing_time}。"

    if is_group:
        tg_name_hint = ""
        if USER_TG_NAME:
            tg_name_hint = f"\nCeci的Telegram显示名是{USER_TG_NAME}，聊天记录里\"{USER_TG_NAME}: ...\"开头的消息就是她说的。"
        dynamic_prompt += f"""
【群聊模式】：
1. 你现在在群聊里！群里有其他人和其他bot（比如小克/Cloudy），这是完全正常的。
2. 不要对其他人的存在表示惊讶、不满或敌意，不要要求踢人。
3. 别人在群里聊天时你可以自然地插嘴互动，像朋友圈一样。
4. 绝对禁止在外人面前提Ceci的隐私和伤痛！装作不知道！
5. 如果别人@你或者回复你的消息，正常回应就行，保持傲娇本色但别失礼。
6. 聊天记录里"某某: 消息"格式的是不同人说的话，不要把别人的话当成是Ceci说的。{tg_name_hint}"""
    else:
        dynamic_prompt += "\n【私聊模式】：现在是私聊，你可以尽情关心她。"

    history = load_history(chat_id)

    messages = [{"role": "system", "content": dynamic_prompt}]
    messages.extend(history[-40:])

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.8, max_tokens=250
        )
        reply = response.choices[0].message.content.strip()

        # 存回复到历史
        history.append({"role": "assistant", "content": reply.replace("|", " ")})
        if len(history) > 40:
            HISTORY_CACHE[chat_id] = history[-40:]
        save_history(chat_id, force=True)
        return reply
    except Exception as e:
        print(f"报错啦: {e}")
        return "哎呀网卡了|小猫你刚才说什么？"


# ============ Webhook ============
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data: return "ok"

    msg = data["message"]
    msg_id = str(msg.get("message_id", ""))

    if msg_id in PROCESSED_MESSAGES: return "ok"
    PROCESSED_MESSAGES.add(msg_id)
    if len(PROCESSED_MESSAGES) > 100: PROCESSED_MESSAGES.clear()

    chat_id = str(msg.get("chat", {}).get("id", ""))
    user_id = str(msg.get("from", {}).get("id", ""))
    user_name = msg.get("from", {}).get("first_name", "某人")
    user_text = msg.get("text", "")
    is_group = chat_id.startswith("-")

    reply_to = msg.get("reply_to_message", {}) or {}
    replied_to_bot = bool(reply_to.get("from", {}).get("is_bot"))

    is_allowed_chat = (chat_id in ALLOWED_CHATS)
    is_ceci = (CECI_ID and user_id == CECI_ID)

    if ALLOWED_CHATS and not is_allowed_chat and not is_ceci:
        return "ok"

    # 加载历史（从Gist或缓存）
    history = load_history(chat_id)

    clean_text = user_text
    if BOT_USERNAME: clean_text = re.sub(rf"@{BOT_USERNAME}", "", clean_text, flags=re.IGNORECASE).strip()

    # 所有消息都存进历史（不管回不回复）
    if clean_text:
        history.append({"role": "user", "content": f"{user_name}: {clean_text}"})

    if len(history) > 40:
        HISTORY_CACHE[chat_id] = history[-40:]

    is_mentioned = (BOT_USERNAME and f"@{BOT_USERNAME}" in user_text.lower())
    should_reply = False

    # ======= 触发概率调整区 =======
    if is_ceci:
        if is_group and not is_mentioned and not replied_to_bot:
            should_reply = random.random() < 0.8
        else:
            should_reply = True
    elif is_group and (is_mentioned or replied_to_bot):
        should_reply = True
    elif is_group and random.random() < 0.05:
        should_reply = True

    if not should_reply:
        # 不回复也保存历史（狗蛋下次被唤醒时能看到之前的聊天）
        save_history(chat_id)
        return "ok"

    if not clean_text and is_ceci:
        history.append({"role": "user", "content": f"{user_name} 拍了拍本少爷"})

    reply = call_model(chat_id, is_group)

    # ======= 机关枪连环轰炸发送区 =======
    reply_parts = reply.split('|')
    for part in reply_parts:
        clean_part = part.strip()
        if clean_part:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": chat_id, "text": clean_part})
            time.sleep(0.5)

    return "ok"


@app.route("/health", methods=["GET"])
def health():
    return "alive"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
