import gspread
import os
import json
import datetime
from oauth2client.service_account import ServiceAccountCredentials

# Google Sheets 設定
SHEET_ID = "1JhRJhdQmZ2PA0mM3g3RGXr5Upt8glr0_rH3yT0gqcqM"
SHEET_NAME = "LineBot預約記錄"  # 如果妳的表單名稱不是 Sheet1 請改這裡

# 從環境變數取得 JSON 金鑰
json_content = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
if not json_content:
    raise Exception("❌ GOOGLE_SERVICE_ACCOUNT_JSON 環境變數不存在，請確認已設定")

# 初始化連線
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(json_content), scope)
client = gspread.authorize(credentials)
sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

def log_reservation(name, user_id, time):
    now = datetime.datetime.now().isoformat()
    row = [name, user_id, time, now]
    sheet.append_row(row)
    print(f"✅ 已寫入 Google Sheet：{row}")
