from flask import Flask, request, render_template_string, redirect
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import json
from datetime import datetime, timedelta
from sheet_logger import log_reservation

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

FLEX_FILE = "flex_booking.json"
RESERVED_FILE = "reserved.json"
ADMIN_PASSWORD = "jenny1111$"
OWNER_ID = "U6be2833d99bbaedc4a590d4f444f169a"

if not os.path.exists(RESERVED_FILE):
    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

def load_and_clean_reservations():
    if not os.path.exists(RESERVED_FILE):
        return []
    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def filter_flex_by_date(flex):
    today = datetime.today().date()
    filtered = []
    for bubble in flex.get("contents", []):
        header_text = bubble["header"]["contents"][0]["text"]
        try:
            bubble_date = datetime.strptime(header_text, "%Y-%m-%d").date()
            if bubble_date >= today:
                filtered.append(bubble)
        except:
            continue
    flex["contents"] = filtered
    return flex

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
    reserved = load_and_clean_reservations()

    if msg.startswith("我想預約"):
        if user_id != OWNER_ID:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="目前預約功能僅限主理人使用 ✋"))
            return
        time_str = msg.replace("我想預約 ", "").strip()
        reserved_times = [r["time"].replace("我想預約 ", "").strip() for r in reserved]
        if time_str in reserved_times:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="這個時段已經被預約囉～\n請選擇其他時段😢"))
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
                "time": msg,
                "phone": "",
                "status": "active"
            }
            reserved.append(new_reservation)
            with open(RESERVED_FILE, "w", encoding="utf-8") as f:
                json.dump(reserved, f, ensure_ascii=False, indent=2)
            try:
                log_reservation(display_name, user_id, time_str)
            except Exception as e:
                print(f"⚠️ 寫入 Google Sheet 失敗: {e}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"預約成功 🎉\n您預約的時間是：{time_str}\nJenny會記得您的名字哦～{display_name}！"))

    elif "體驗" in msg or "預約" in msg:
        if user_id != OWNER_ID:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="本預約功能尚未開\n敬請期待 👀"))
            return

        try:
            with open(FLEX_FILE, "r", encoding="utf-8") as f:
                flex = json.load(f)
            reserved_times = [r["time"].replace("我想預約 ", "").strip() for r in reserved]
            flex = filter_flex_by_date(flex)
            for bubble in flex["contents"]:
                try:
                    for content in bubble["body"]["contents"]:
                        if content["type"] == "box" and "contents" in content:
                            filtered_buttons = []
                            for btn in content["contents"]:
                                action_text = btn.get("action", {}).get("text", "")
                                clean_time = action_text.replace("我想預約 ", "").strip()
                                if btn.get("type") != "button" or clean_time not in reserved_times:
                                    filtered_buttons.append(btn)
                                else:
                                    print(f"❌ 已過濾按鈕：{clean_time}")
                            content["contents"] = filtered_buttons
                except Exception as e:
                    print(f"⚠️ Flex bubble 過濾按鈕失敗: {e}")
            flex_msg = FlexSendMessage(alt_text="請選擇預約時段", contents=flex)
            line_bot_api.reply_message(event.reply_token, flex_msg)
        except Exception as e:
            print(f"❌ Error sending Flex Message: {e}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="讀取預約資訊時發生錯誤，請稍後再試。"))
