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

@app.route("/admin")
def admin():
    pw = request.args.get("pw", "")
    if pw != ADMIN_PASSWORD:
        return "🔒 權限不足，請輸入正確密碼： /admin?pw=你的密碼"

    try:
        with open(RESERVED_FILE, "r", encoding="utf-8") as f:
            reserved = json.load(f)
    except Exception as e:
        return f"❌ 無法讀取 reserved.json：{e}"

    grouped = defaultdict(list)
    for r in reserved:
        try:
            time_str = r.get('time', '').replace("我想預約 ", "").strip()
            date_part = time_str.split()[0]
            grouped[date_part].append(r)
        except Exception as e:
            print(f"⚠️ 分組失敗: {e}")
            continue

    section_html = ""
    for date_key in sorted(grouped.keys()):
        table_rows = ""
        try:
            sorted_reservations = sorted(
                grouped[date_key],
                key=lambda r: datetime.strptime(
                    r.get('time', '').replace("我想預約 ", "").strip(),
                    "%m/%d %H:%M"
                )
            )
        except Exception as e:
            print(f"⚠️ 日期排序失敗: {e}")
            sorted_reservations = grouped[date_key]

        for r in sorted_reservations:
            name = r.get('displayName', 'unknown')
            uid = r.get('userId', '')
            time = r.get('time', '未知時間')
            clean_time = time.replace("我想預約 ", "").strip()

            # 加上樣式判斷
            row_class = ""
            text_class = ""
            if r.get("status") == "missed":
                row_class = "table-danger"
                text_class = "text-danger fw-bold"
            elif r.get("status") == "done":
                row_class = "line-through-bold table-secondary"
                text_class = "text-muted"

            # 每一列 HTML
            phone = r.get("phone", "-")
            table_rows += f"""
                <tr class='{row_class}'>
                    <td class='{text_class}'>{name}</td>
                    <td class='{text_class}'>{time}</td>
                    <td class='{text_class}'>{phone}</td>
                    <td>
                        <a href='/delete?userId={uid}&time={clean_time}&pw={pw}' class='btn btn-sm btn-outline-danger'>刪除</a>
                        <a href='/mark_status?userId={uid}&time={clean_time}&status=missed&pw={pw}' class='btn btn-sm btn-outline-warning'>過號</a>
                        <a href='/mark_status?userId={uid}&time={clean_time}&status=done&pw={pw}' class='btn btn-sm btn-outline-success'>已體驗</a>
                    </td>
                </tr>
            """

        section_html += f"""
        <h4 class='mt-5'>📅 {date_key}</h4>
        <table class='table table-bordered table-striped'>
            <thead class='table-dark'>
                <tr>
                    <th>名稱</th>
                    <th>時間</th>
                    <th>📱 手機號碼</th>
                    <th>操作</th>
                </tr>
            </thead>
<tbody>{table_rows}</tbody>

            <tbody>{table_rows}</tbody>
        </table>"""

    # 整頁 HTML 結構
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset='UTF-8'>
        <title>Jenny 預約後台</title>
        <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css' rel='stylesheet'>
        <style>
            .line-through-bold {{
                text-decoration: line-through;
                text-decoration-thickness: 2px;
            }}
            .table-secondary td {{
                background-color: #f8f9fa !important;
            }}
            .text-muted {{
                color: #888 !important;
            }}
        </style>
    </head>
    <body class='container mt-4'>
        <h2 class='mb-4'>🌸 Jenny 預約後台 🌸</h2>
        {section_html}
        <h5 class='mt-4'>✏️ 修改名稱</h5>
        <form action='/edit' method='post' class='row g-2'>
            <div class='col-md-3'>
                <input type='text' name='displayName' class='form-control' placeholder='原本名稱' required>
            </div>
            <div class='col-md-3'>
                <input type='text' name='time' class='form-control' placeholder='時間（例如：4/25 13:00）' required>
            </div>
            <div class='col-md-3'>
                <input type='text' name='newName' class='form-control' placeholder='新名稱' required>
            </div>
            <div class='col-md-3'>
                <input type='text' name='phone' class='form-control' placeholder='手機號碼 (選填)'>
            </div>
            <input type='hidden' name='pw' value='{pw}'>
            <div class='col-md-3 mt-2'>
                <button type='submit' class='btn btn-primary'>送出修改</button>
            </div>
        </form>
    </body>
    </html>
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

@app.route("/mark_status")
def mark_status():
    user_id = request.args.get("userId")
    time = request.args.get("time")
    status = request.args.get("status")
    pw = request.args.get("pw")

    if pw != ADMIN_PASSWORD:
        return "❌ 權限錯誤"

    with open(RESERVED_FILE, "r", encoding="utf-8") as f:
        reserved = json.load(f)

    for r in reserved:
        if r["userId"] == user_id and r["time"].replace("我想預約 ", "").strip() == time:
            r["status"] = status

    with open(RESERVED_FILE, "w", encoding="utf-8") as f:
        json.dump(reserved, f, ensure_ascii=False, indent=2)

    return redirect(f"/admin?pw={pw}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
