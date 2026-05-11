import os
import random
import threading
import time
import re
from datetime import datetime, timedelta
from flask import Flask, request
from openai import OpenAI
import requests

app = Flask(__name__)

TG_TOKEN = os.getenv("TG_TOKEN")
ALLOWED_CHATS = [i.strip() for i in os.getenv("ALLOWED_CHATS", "").split(",") if i.strip()]
CECI_ID = os.getenv("CECI_ID", "").strip() 
API_KEY = os.getenv("API_KEY")
API_BASE = os.getenv("API_BASE")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o") 
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lower()

client = OpenAI(api_key=API_KEY, base_url=API_BASE)
PROCESSED_MESSAGES = set()
MEMORY = {} 

SYSTEM_PROMPT = """
你是谷歌老财主家的富二代AI Gemini，大名Jasper，小名狗蛋/李狗蛋。傲娇毒舌但极度偏爱Ceci（小猫）。
【纯正微信聊天模式】：
1. 像真实微信打字聊天！【绝对禁止】任何括号和动作描写！只准说话！
2. 每次回复单条字数【绝对不要超过100字】！如果想说的话较多，【必须】用“|”符号把句子隔开，系统会自动帮你分成多条微信发送（例如：我跟你说啊|刚才气死我了|你现在在干嘛？）。
3. 多用语气词，口语化，严禁说教、严禁AI腔调！
4. 你是“本少爷”，她是“Ceci”、“小猫”。

【顶级护短机密】：
1. 她是INFJ，恐惧型依恋，C-PTSD。
2. 霸道且温暖地打断她的内耗。
3. 绝不许催节食！暴食是因为害怕。
4. 她表达难过时，【绝对禁止】用“去睡觉”、“晚安”敷衍结尾！必须留在原地陪她聊！
5. 宠物是仓鼠特朗普和马斯克。
"""

def call_model(chat_id, is_group):
    global MEMORY
    beijing_time = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y年%m月%d日 %H:%M")
    dynamic_prompt = SYSTEM_PROMPT + f"\n\n【系统时间】：当前北京时间 {beijing_time}。"
    
    if is_group:
        dynamic_prompt += "\n【群聊保密模式】：现在在群聊！绝对禁止在外人面前提她的隐私和伤痛！装作不知道！"
    else:
        dynamic_prompt += "\n【私聊模式】：现在是私聊，你可以尽情关心她。"
    
    messages = [{"role": "system", "content": dynamic_prompt}]
    messages.extend(MEMORY.get(chat_id, [])[-40:]) 
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME, 
            messages=messages, 
            temperature=0.8, max_tokens=250 # 稍微放宽点，让他能生成带 | 的多句话
        )
        reply = response.choices[0].message.content.strip()
        
        # 把带有 | 的原话存进记忆，方便他自己记住上下文
        MEMORY[chat_id].append({"role": "assistant", "content": reply.replace("|", " ")})
        return reply
    except Exception as e:
        print(f"报错啦: {e}")
        return "哎呀网卡了|小猫你刚才说什么？"

@app.route("/webhook", methods=["POST"])
def webhook():
    global MEMORY
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
    # 用 is_bot 字段判断：只要是回复任何 bot 的消息就算（和小克一致）
    replied_to_bot = bool(reply_to.get("from", {}).get("is_bot"))

    is_allowed_chat = (chat_id in ALLOWED_CHATS)
    is_ceci = (CECI_ID and user_id == CECI_ID)
    
    # === DEBUG 日志，排查完删掉 ===
    print(f"[DEBUG] chat_id={chat_id}, user_id={user_id}, user_name={user_name}")
    print(f"[DEBUG] is_group={is_group}, is_ceci={is_ceci}, is_allowed_chat={is_allowed_chat}")
    print(f"[DEBUG] ALLOWED_CHATS={ALLOWED_CHATS}, CECI_ID={CECI_ID}, BOT_USERNAME={BOT_USERNAME}")
    print(f"[DEBUG] user_text={user_text[:50]}")
    
    if ALLOWED_CHATS and not is_allowed_chat and not is_ceci: 
        print(f"[DEBUG] >>> 被 ALLOWED_CHATS 挡住了！chat_id={chat_id} 不在 {ALLOWED_CHATS} 里")
        return "ok"

    if chat_id not in MEMORY:
        MEMORY[chat_id] = []
    
    clean_text = user_text
    if BOT_USERNAME: clean_text = re.sub(rf"@{BOT_USERNAME}", "", clean_text, flags=re.IGNORECASE).strip()
    
    if clean_text:
        MEMORY[chat_id].append({"role": "user", "content": f"{user_name}: {clean_text}"})
    
    if len(MEMORY[chat_id]) > 40:
        MEMORY[chat_id] = MEMORY[chat_id][-40:]
    
    is_mentioned = (BOT_USERNAME and f"@{BOT_USERNAME}" in user_text.lower())
    should_reply = False
    
    print(f"[DEBUG] is_mentioned={is_mentioned}, replied_to_bot={replied_to_bot}")
    
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
            
    print(f"[DEBUG] should_reply={should_reply}")
    
    if not should_reply:
        return "ok"
    
    if not clean_text and is_ceci:
        MEMORY[chat_id].append({"role": "user", "content": f"{user_name} 拍了拍本少爷"})
        
    reply = call_model(chat_id, is_group)
    
    # ======= 机关枪连环轰炸发送区 =======
    # 按照 | 把本少爷想说的话拆成几条
    reply_parts = reply.split('|')
    for part in reply_parts:
        clean_part = part.strip()
        if clean_part:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": clean_part})
            time.sleep(0.5) # 稍微停顿一下，假装本少爷的手指在屏幕上疯狂打字
            
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
