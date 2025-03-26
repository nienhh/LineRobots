from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, PostbackEvent, FlexSendMessage, TextSendMessage

import json
import os

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

@app.route("/")
def home():
    return "LINE Webhook is running on Railway!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    if event.message.text == "預約體驗":
        try:
            with open("flex_booking.json", "r", encoding="utf-8") as f:
                flex_json = json.load(f)
            message = FlexSendMessage(alt_text="預約時段", contents=flex_json)
            line_bot_api.reply_message(event.reply_token, message)
        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"讀取 Flex JSON 失敗：{e}"))

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"您點擊了 {data}"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))