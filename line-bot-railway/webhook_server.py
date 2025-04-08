from flask import Flask, request, render_template_string, redirect
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import json
from datetime import datetime
from sheet_logger import log_reservation

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

FLEX_FILE = "flex_booking.json"
RESERVED_FILE = "reserved.json"
ADMIN_PASSWORD = "jenny1111$"

# 確保 reserved.json 存在
if not os.path.exists(RESERVED_FILE):
    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

# 自動清除過期的預約資料
def load_and_clean_reservations():
    today = datetime.today().date()
    if not os.path.exists(RESERVED_FILE):
        return []

    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = json.load(f)

    cleaned_reserved = []
    for r in reserved:
        try:
            time_text = r["time"].replace("我想預約 ", "").strip()
            date_str = time_text.split()[0]
            dt = datetime.strptime(date_str, "%m/%d").replace(year=today.year)
            if dt.date() >= today:
                cleaned_reserved.append(r)
        except:
            cleaned_reserved.append(r)

    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned_reserved, f, ensure_ascii=False, indent=2)

    return cleaned_reserved

# 過濾 Flex bubble 中過期的日期

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
                "time": msg
            }
            reserved.append(new_reservation)
            with open(RESERVED_FILE, "w", encoding="utf-8") as f:
                json.dump(reserved, f, ensure_ascii=False, indent=2)
            try:
                log_reservation(display_name, user_id, time_str)
            except Exception as e:
                print(f"⚠️ 寫入 Google Sheet 失敗: {e}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"預約成功 🎉\n 您預約的時間是：{time_str}\n Jenny會記得您的名字哦～～{display_name}！"))

    elif "體驗" in msg:
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

    elif msg in ["您好", "請問", "不好意思", "我想問"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="感謝您的訊息！\nbroqué 忙線中，稍候回覆您🤧"))

@app.route("/debug/reserved")
def debug_reserved():
    try:
        with open(RESERVED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.route("/admin")
def admin():
    pw = request.args.get("pw", "")
    if pw != ADMIN_PASSWORD:
        return "🔒 權限不足，請輸入正確密碼： /admin?pw=你的密碼"
    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = json.load(f)
    table = ""
    for r in reserved:
        table += f"""
        <tr>
            <td>{r['displayName']}</td>
            <td>{r['time']}</td>
            <td><a href=\"/delete?userId={r['userId']}&time={r['time'].replace('我想預約 ', '').strip()}&pw={pw}\">🗑️ 刪除</a></td>
        </tr>"""
    html = f"""
    <h2>🌸 Jenny 預約後台 🌸</h2>
    <table border=\"1\" cellpadding=\"8\">
        <tr><th>名稱</th><th>時間</th><th>操作</th></tr>
        {table}
    </table>
    """
    return render_template_string(html)

@app.route("/delete")
def delete_reservation():
    user_id = request.args.get("userId")
    time = request.args.get("time")
    pw = request.args.get("pw")
    if pw != ADMIN_PASSWORD:
        return "❌ 權限錯誤"
    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = json.load(f)
    new_reserved = [
        r for r in reserved
        if not (r["userId"] == user_id and r["time"].replace("我想預約 ", "").strip() == time)
    ]
    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump(new_reserved, f, ensure_ascii=False, indent=2)
    return redirect(f"/admin?pw={pw}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
