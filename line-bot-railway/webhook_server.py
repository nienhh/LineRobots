from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import json

app = Flask(__name__)

# LINE credentials from environment variables
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# File paths
FLEX_FILE = "flex_booking.json"
RESERVED_FILE = "reserved.json"

# Ensure reserved.json exists
if not os.path.exists(RESERVED_FILE):
    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "Invalid signature", 400
    except Exception as e:
        print(f"❌ Error in callback: {e}")
        return "Error", 500

    return "OK", 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    user_id = event.source.user_id

    # Load reserved time list
    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = json.load(f)  # List of dicts: {userId, displayName, time}

    if msg == "我要預約":
        try:
            with open(FLEX_FILE, "r", encoding="utf-8") as f:
                flex = json.load(f)

            reserved_times = [r["time"] for r in reserved]

            # 移除已預約的時間按鈕
            for bubble in flex["contents"]:
                button_box = bubble["body"]["contents"][3]["contents"]
                button_box = [
                    btn for btn in button_box
                    if btn.get("action", {}).get("text") not in reserved_times
                ]
                bubble["body"]["contents"][3]["contents"] = button_box

            flex_msg = FlexSendMessage(alt_text="請選擇預約時段", contents=flex)
            line_bot_api.reply_message(event.reply_token, flex_msg)
        except Exception as e:
            print(f"❌ Error sending Flex Message: {e}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="讀取預約資訊時發生錯誤，請稍後再試。"))

    elif msg.startswith("我想預約"):
        time_str = msg.replace("我想預約 ", "").strip()
        reserved_times = [r["time"] for r in reserved]

        if time_str in reserved_times:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="這個時段已經被預約囉～請選擇其他時段 💔"))
        else:
            try:
                profile = line_bot_api.get_profile(user_id)
                display_name = profile.display_name
            except Exception as e:
                print(f"⚠️ 無法取得使用者名稱: {e}")
                display_name = "unknown"

            new_reservation = {
                "userId": user_id,
                "displayName": display_name,
                "time": time_str
            }
            reserved.append(new_reservation)
            with open(RESERVED_FILE, "w", encoding="utf-8") as f:
                json.dump(reserved, f, ensure_ascii=False, indent=2)

            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"預約成功 🎉\n妳預約的時間是：{time_str}\n我們會記得妳的名字喔，{display_name}！"))

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入『我要預約』開始選擇時段 🕰️"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
