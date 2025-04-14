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

@app.route("/admin")
def admin():
    pw = request.args.get("pw", "")
    if pw != ADMIN_PASSWORD:
        return "🔒 權限不足，請輸入正確密碼： /admin?pw=你的密碼"

    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = sorted(json.load(f), key=lambda x: x["time"])

    sections = {"04/25": [], "04/26": [], "04/27": [], "04/28": []}
    for r in reserved:
        day = r["time"].split()[0]
        sections.setdefault(day, []).append(r)

    section_html = ""
    for day, items in sections.items():
        section_html += f"<h3>📅 {day}</h3><table border='1' cellpadding='8'>"
        section_html += "<tr><th>名稱</th><th>時間</th><th>電話</th><th>狀態</th><th>操作</th></tr>"
        for r in items:
            style = "text-decoration: line-through;" if r.get("status") == "done" else ""
            color = "color: red;" if r.get("status") == "missed" else ""
            section_html += f"""
            <tr style='{style} {color}'>
                <td>{r['displayName']}</td>
                <td>{r['time']}</td>
                <td><form method='post' action='/update_phone'><input name='phone' value='{r.get('phone', '')}'><input type='hidden' name='userId' value='{r['userId']}'><input type='hidden' name='time' value='{r['time']}'><input type='submit' value='✔️'></form></td>
                <td>{r.get('status', 'active')}</td>
                <td>
                    <a href='/delete?userId={r['userId']}&time={r['time'].replace('我想預約 ', '').strip()}&pw={pw}'>🗑️ 刪除</a> |
                    <a href='/mark_status?userId={r['userId']}&time={r['time'].replace('我想預約 ', '').strip()}&status=done&pw={pw}'>✅ 完成</a> |
                    <a href='/mark_status?userId={r['userId']}&time={r['time'].replace('我想預約 ', '').strip()}&status=missed&pw={pw}'>❌ 過號</a>
                </td>
            </tr>"""
        section_html += "</table><br>"

    return render_template_string(f"""
    <h2>🌸 Jenny 預約後台 🌸</h2>
    {section_html}
    <hr>
    <form action='/edit' method='post'>
        <p>✏️ 修改名稱</p>
        <input type='text' name='displayName' placeholder='原本名稱（例如：心薇）' required>
        <input type='text' name='time' placeholder='時間（例如：04/25 13:00）' required>
        <input type='text' name='newName' placeholder='新名稱' required>
        <input type='hidden' name='pw' value='{pw}'>
        <button type='submit'>送出修改</button>
    </form>
    """)

@app.route("/update_phone", methods=["POST"])
def update_phone():
    user_id = request.form.get("userId")
    time = request.form.get("time")
    phone = request.form.get("phone")
    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = json.load(f)
    for r in reserved:
        if r["userId"] == user_id and r["time"] == time:
            r["phone"] = phone
    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump(reserved, f, ensure_ascii=False, indent=2)
    return redirect("/admin?pw=" + ADMIN_PASSWORD)

@app.route("/mark_status")
def mark_status():
    user_id = request.args.get("userId")
    time = request.args.get("time")
    status = request.args.get("status")
    pw = request.args.get("pw")
    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = json.load(f)
    for r in reserved:
        if r["userId"] == user_id and r["time"].replace("我想預約 ", "").strip() == time:
            r["status"] = status
    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump(reserved, f, ensure_ascii=False, indent=2)
    return redirect("/admin?pw=" + pw)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
