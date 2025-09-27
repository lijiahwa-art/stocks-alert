from multi_stock_alert import MultiStockAlertSystem

if __name__ == "__main__":
    bot = MultiStockAlertSystem()
    # 你若已經有一次性檢查的函式，直接用
    for name in ("run_once", "check_all_once"):
        if hasattr(bot, name):
            getattr(bot, name)()
            break
    else:
        # 備用：最小一次性檢查（ATH 回落 5%/10%），不動你的原始碼也能跑
        import os, yfinance as yf, datetime as dt, requests, pandas as pd
        TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or os.getenv("LINE_TOKEN")
        USER  = os.getenv("LINE_USER_ID")
        SYMBOLS = ["QQQ"]              # 需要就自己改：["QQQ","VOO","NVDA","00662.TW"]
        THRESHOLDS = [0.05, 0.10]      # 5%、10%

        def send_line(text):
            headers={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"}
            body={"to": USER,"messages":[{"type":"text","text":text}]}
            requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body, timeout=20)

        for sym in SYMBOLS:
            df = yf.download(sym, period="max", interval="1d", auto_adjust=True, progress=False)
            if df.empty or len(df)<3: 
                continue
            c = df["Close"]; ath = c.max(); prev, last = c.iloc[-2], c.iloc[-1]
            dd_prev = (ath - prev)/ath; dd_last = (ath - last)/ath
            crossed = [th for th in THRESHOLDS if dd_prev < th <= dd_last]
            if crossed:
                levels = ", ".join(f"{int(th*100)}%" for th in crossed)
                msg = (f"📉 {sym} 回落觸發：{levels}\n"
                       f"現價 {last:.2f}｜ATH {ath:.2f}｜目前回落 {dd_last*100:.2f}%\n"
                       f"{dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC")
                send_line(msg)
