# --- minimal one-shot runner: 不會 import 你的 multi_stock_alert.py ---
import os, datetime as dt, requests, yfinance as yf, pandas as pd

TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or os.getenv("LINE_TOKEN")
USER  = os.getenv("LINE_USER_ID")

# 監控清單與門檻（想改就改）
SYMBOLS    = ["QQQ"]          # 例：["QQQ","VOO","NVDA","00662.TW"]
THRESHOLDS = [0.05, 0.10]     # 5%、10%

def send_line(text: str):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type":"application/json"}
    body    = {"to": USER, "messages":[{"type":"text","text": text}]}
    r = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body, timeout=20)
    print("LINE:", r.status_code, r.text[:200])

def check_once(sym: str):
    df = yf.download(sym, period="max", interval="1d", auto_adjust=True, progress=False)
    if df.empty or len(df) < 3:
        print(f"[WARN] no data for {sym}"); return
    c = df["Close"]; ath = c.max()
    prev, last = c.iloc[-2], c.iloc[-1]
    dd_prev = (ath - prev)/ath
    dd_last = (ath - last)/ath
    print(f"{sym} | ATH={ath:.2f} prev={prev:.2f}({dd_prev*100:.2f}%) last={last:.2f}({dd_last*100:.2f}%)")
    crossed = [th for th in THRESHOLDS if dd_prev < th <= dd_last]
    if crossed:
        levels = ", ".join(f"{int(th*100)}%" for th in crossed)
        msg = (f"📉 {sym} 回落觸發：{levels}\n"
               f"現價 {last:.2f}｜ATH {ath:.2f}｜目前回落 {dd_last*100:.2f}%\n"
               f"{dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC")
        send_line(msg)

if __name__ == "__main__":
    for s in SYMBOLS:
        check_once(s)
