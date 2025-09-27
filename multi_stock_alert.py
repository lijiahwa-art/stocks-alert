import yfinance as yf
import requests
import json
import time
import schedule
from datetime import datetime
import os
import psycopg2
from decimal import Decimal

class MultiStockAlertSystem:
    def __init__(self):
        self.line_channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
        self.line_user_id = os.getenv('LINE_USER_ID')
        self.database_url = os.getenv('DATABASE_URL')
        
        # Migrate legacy data if needed
        self.migrate_legacy_data()
        
        # Initialize database and stocks
        self.init_stocks()
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.database_url)
    
    def migrate_legacy_data(self):
        """Migrate data from legacy qqq_all_time_high.json file"""
        legacy_file = 'qqq_all_time_high.json'
        if os.path.exists(legacy_file):
            try:
                with open(legacy_file, 'r') as f:
                    legacy_data = json.load(f)
                
                # Migrate QQQ data to database
                with self.get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO stock_tracking (symbol, name, all_time_high, last_alert_5_percent, last_alert_10_percent)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (symbol) DO UPDATE SET
                                all_time_high = COALESCE(EXCLUDED.all_time_high, stock_tracking.all_time_high),
                                last_alert_5_percent = EXCLUDED.last_alert_5_percent,
                                last_alert_10_percent = EXCLUDED.last_alert_10_percent
                        """, ('QQQ', 'Invesco QQQ Trust', 
                              legacy_data.get('all_time_high'), 
                              legacy_data.get('last_alert_5_percent', False),
                              legacy_data.get('last_alert_10_percent', False)))
                    conn.commit()
                
                # Backup and remove legacy file
                backup_name = f'{legacy_file}.migrated'
                os.rename(legacy_file, backup_name)
                print(f"📦 Migrated legacy QQQ data from {legacy_file} (backed up as {backup_name})")
                
            except Exception as e:
                print(f"⚠️ Error migrating legacy data: {e}")
    
    def get_stocks_to_track(self):
        """Get list of stocks to track from database configuration"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT symbol, name FROM tracked_stocks_config 
                        WHERE enabled = true 
                        ORDER BY symbol
                    """)
                    return [{'symbol': row[0], 'name': row[1]} for row in cur.fetchall()]
        except Exception as e:
            print(f"❌ Error getting stocks to track: {e}")
            # Fallback to default stocks if database query fails
            return [
                {'symbol': 'QQQ', 'name': 'Invesco QQQ Trust'}
            ]
    
    def init_stocks(self):
        """Initialize stocks in database if they don't exist"""
        try:
            stocks_to_track = self.get_stocks_to_track()
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    for stock in stocks_to_track:
                        # Check if stock exists in tracking table
                        cur.execute("SELECT symbol FROM stock_tracking WHERE symbol = %s", (stock['symbol'],))
                        if not cur.fetchone():
                            # Add new stock
                            cur.execute("""
                                INSERT INTO stock_tracking (symbol, name, all_time_high, last_alert_5_percent, last_alert_10_percent)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (stock['symbol'], stock['name'], None, False, False))
                            print(f"➕ Added {stock['symbol']} ({stock['name']}) to tracking")
                        else:
                            print(f"✅ {stock['symbol']} already being tracked")
                conn.commit()
        except Exception as e:
            print(f"❌ Error initializing stocks: {e}")
    
    def get_stock_price(self, symbol):
        """Get current stock price using Yahoo Finance"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            current_price = info.get('regularMarketPrice') or info.get('previousClose')
            
            if current_price is None:
                # Fallback: get from historical data
                hist = yf.download(symbol, period="1d", interval="1m")
                if hist is not None and not hist.empty:
                    current_price = hist['Close'].iloc[-1]
            
            return float(current_price) if current_price else None
        except Exception as e:
            print(f"Error getting {symbol} price: {e}")
            return None
    
    def get_stock_data(self, symbol):
        """Get stock tracking data from database"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT symbol, name, all_time_high, last_alert_5_percent, last_alert_10_percent
                        FROM stock_tracking WHERE symbol = %s
                    """, (symbol,))
                    result = cur.fetchone()
                    if result:
                        return {
                            'symbol': result[0],
                            'name': result[1],
                            'all_time_high': float(result[2]) if result[2] else None,
                            'last_alert_5_percent': result[3],
                            'last_alert_10_percent': result[4]
                        }
            return None
        except Exception as e:
            print(f"❌ Error getting stock data for {symbol}: {e}")
            return None
    
    def update_stock_data(self, symbol, all_time_high=None, alert_5=None, alert_10=None):
        """Update stock tracking data in database"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    updates = []
                    params = []
                    
                    if all_time_high is not None:
                        updates.append("all_time_high = %s")
                        params.append(Decimal(str(all_time_high)))
                    
                    if alert_5 is not None:
                        updates.append("last_alert_5_percent = %s")
                        params.append(alert_5)
                    
                    if alert_10 is not None:
                        updates.append("last_alert_10_percent = %s")
                        params.append(alert_10)
                    
                    if updates:
                        updates.append("last_updated = CURRENT_TIMESTAMP")
                        params.append(symbol)
                        
                        query = f"UPDATE stock_tracking SET {', '.join(updates)} WHERE symbol = %s"
                        cur.execute(query, params)
                conn.commit()
        except Exception as e:
            print(f"❌ Error updating stock data for {symbol}: {e}")
    
    def send_line_message(self, message):
        """Send notification via LINE Messaging API"""
        if not self.line_channel_access_token or not self.line_user_id:
            print(f"LINE credentials not configured. Would send: {message}")
            return False
        
        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Authorization": f"Bearer {self.line_channel_access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "to": self.line_user_id,
            "messages": [
                {
                    "type": "text",
                    "text": message
                }
            ]
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                print(f"✅ LINE message sent: {message[:50]}...")
                return True
            else:
                print(f"❌ Failed to send LINE message: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ Error sending LINE message: {e}")
            return False
    
    def check_stock_alerts(self, symbol):
        """Check alerts for a specific stock"""
        # Get current price
        current_price = self.get_stock_price(symbol)
        if current_price is None:
            print(f"❌ Could not fetch {symbol} price")
            return
        
        # Get tracking data
        stock_data = self.get_stock_data(symbol)
        if not stock_data:
            print(f"❌ No tracking data for {symbol}")
            return
        
        stock_name = stock_data['name']
        all_time_high = stock_data['all_time_high']
        last_alert_5 = stock_data['last_alert_5_percent']
        last_alert_10 = stock_data['last_alert_10_percent']
        
        print(f"📊 {symbol} ({stock_name}): ${current_price:.2f}")
        
        # Update all-time high if current price is higher
        if all_time_high is None or current_price > all_time_high:
            if all_time_high is not None:
                print(f"🎉 {symbol} NEW ALL-TIME HIGH! Previous: ${all_time_high:.2f}, New: ${current_price:.2f}")
            all_time_high = current_price
            # Reset alert flags when new high is reached
            self.update_stock_data(symbol, all_time_high=all_time_high, alert_5=False, alert_10=False)
            return
        
        # Calculate percentage drop from all-time high
        drop_percentage = ((all_time_high - current_price) / all_time_high) * 100
        
        print(f"📉 {symbol} drop from ATH (${all_time_high:.2f}): {drop_percentage:.2f}%")
        
        # Check for 10% drop alert
        if drop_percentage >= 10.0 and not last_alert_10:
            message = f"🚨 {symbol} ALERT: 10% Drop!\n\n{stock_name}\nCurrent: ${current_price:.2f}\nAll-Time High: ${all_time_high:.2f}\nDrop: {drop_percentage:.2f}%\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_line_message(message)
            self.update_stock_data(symbol, alert_5=True, alert_10=True)  # Mark both as sent
        
        # Check for 5% drop alert (only if 10% hasn't been triggered)
        elif drop_percentage >= 5.0 and not last_alert_5:
            message = f"⚠️ {symbol} ALERT: 5% Drop!\n\n{stock_name}\nCurrent: ${current_price:.2f}\nAll-Time High: ${all_time_high:.2f}\nDrop: {drop_percentage:.2f}%\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.send_line_message(message)
            self.update_stock_data(symbol, alert_5=True)
        
        # Reset alerts if price recovers above thresholds
        if drop_percentage < 5.0:
            if last_alert_5 or last_alert_10:
                print(f"📈 {symbol} price recovered above 5% drop threshold - resetting alerts")
                self.update_stock_data(symbol, alert_5=False, alert_10=False)
    
    def ensure_stock_initialized(self, symbol, name):
        """Ensure a stock exists in tracking table, initialize if not"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Check if stock exists in tracking table
                    cur.execute("SELECT symbol FROM stock_tracking WHERE symbol = %s", (symbol,))
                    if not cur.fetchone():
                        # Add new stock
                        cur.execute("""
                            INSERT INTO stock_tracking (symbol, name, all_time_high, last_alert_5_percent, last_alert_10_percent)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (symbol, name, None, False, False))
                        conn.commit()
                        print(f"🆕 Initialized new stock {symbol} ({name}) for tracking")
                        return True
            return False
        except Exception as e:
            print(f"❌ Error ensuring stock {symbol} is initialized: {e}")
            return False
    
    def check_all_stock_alerts(self):
        """Main function to check all stocks and send alerts"""
        stocks_to_track = self.get_stocks_to_track()
        
        print(f"\n🔍 Checking {len(stocks_to_track)} stocks at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        for stock in stocks_to_track:
            try:
                # Ensure stock is initialized in tracking table (handles new stocks added at runtime)
                self.ensure_stock_initialized(stock['symbol'], stock['name'])
                
                # Check alerts for this stock
                self.check_stock_alerts(stock['symbol'])
            except Exception as e:
                print(f"❌ Error checking {stock['symbol']}: {e}")
        
        print("=" * 60)

def main():
    """Main function to run the Multi-Stock Alert System"""
    print("🚀 Starting Multi-Stock Alert System")
    print("=" * 60)
    
    # Check for required environment variables
    if not os.getenv('LINE_CHANNEL_ACCESS_TOKEN') or not os.getenv('LINE_USER_ID'):
        print("⚠️  LINE credentials not found in environment variables.")
        print("Please set LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID to enable notifications.")
        print("For now, alerts will be printed to console.")
    
    alert_system = MultiStockAlertSystem()
    
    # Schedule checks every 15 minutes
    schedule.every(15).minutes.do(alert_system.check_all_stock_alerts)
    
    # Run initial check
    alert_system.check_all_stock_alerts()
    
    stocks_count = len(alert_system.get_stocks_to_track())
    print(f"\n⏰ Scheduler started. Checking {stocks_count} stocks every 15 minutes...")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute for scheduled tasks
    except KeyboardInterrupt:
        print("\n👋 Multi-Stock Alert System stopped")

if __name__ == "__main__":
    main()
