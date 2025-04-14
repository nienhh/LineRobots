from flask import Flask, request, render_template_string, redirect
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import json
from datetime import datetime
from sheet_logger import log_reservation
from collections import defaultdict


app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

FLEX_FILE = "flex_booking.json"
RESERVED_FILE = "reserved.json"
ADMIN_PASSWORD = "jenny1111$"
OWNER_ID = "U6be2833d99bbaedc4a590d4f444f169a"

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

    # ✅ 不清除任何資料，只是讀取
    return reserved

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
                text=f"預約成功 🎉\n您預約的時間是：{time_str}\nJenny會記得您的名字哦～{display_name}！"))

    elif "體驗" in msg:
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

    # 🔸 按日期分組
    grouped = defaultdict(list)
    for r in reserved:
        try:
            time_str = r['time'].replace("我想預約 ", "").strip()
            date_part = time_str.split()[0]  # 例如 "4/25"
            grouped[date_part].append({
                "displayName": r["displayName"],
                "time": time_str,
                "userId": r["userId"]
            })
        except Exception as e:
            print(f"⚠️ 分組失敗: {e}")
            continue

    # 🔸 產生 HTML 區塊（每個日期一張表）
    section_html = ""
    for date_key in sorted(grouped.keys()):
        table_rows = ""
        for r in grouped[date_key]:
            delete_link = f"/delete?userId={r['userId']}&time={r['time']}&pw={pw}"
            table_rows += f"""
            <tr>
                <td>{r['displayName']}</td>
                <td>{r['time']}</td>
                <td><a href="{delete_link}">🗑️ 刪除</a></td>
            </tr>"""

        section_html += f"""
        <h3>📅 {date_key}</h3>
        <table border="1" cellpadding="8" cellspacing="0">
            <tr><th>名稱</th><th>時間</th><th>操作</th></tr>
            {table_rows}
        </table>
        <br>
        """

    # 🔸 修改名稱表單區塊
    form_html = f"""
    <hr>
    <h3>✏️ 修改名稱</h3>
    <form action='/edit' method='post'>
        <input type='text' name='displayName' placeholder='原本名稱（例如：心薇）' required>
        <input type='text' name='time' placeholder='時間（例如：4/25 13:00）' required>
        <input type='text' name='newName' placeholder='新名稱' required>
        <input type='hidden' name='pw' value='{pw}'>
        <button type='submit'>送出修改</button>
    </form>
    """

    html = f"""
    <h2>🌸 Jenny 預約後台 🌸</h2>
    {section_html}
    {form_html}
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

@app.route("/edit", methods=["POST"])
def edit_display_name():
    name = request.form.get("displayName")
    time = request.form.get("time")
    new_name = request.form.get("newName")
    pw = request.form.get("pw")

    if pw != ADMIN_PASSWORD:
        return "❌ 權限錯誤"

    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = json.load(f)

    for r in reserved:
        if r["displayName"] == name and r["time"].replace("我想預約 ", "").strip() == time:
            r["displayName"] = new_name

    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump(reserved, f, ensure_ascii=False, indent=2)

    return redirect(f"/admin?pw={pw}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
