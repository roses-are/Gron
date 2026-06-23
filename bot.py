import requests
from bs4 import BeautifulSoup
import hashlib
import threading
import time
import re
import os
import sys
import html
from collections import deque
from flask import Flask, jsonify

# Suppress all console output
sys.stdout = open(os.devnull, 'w')
sys.stderr = open(os.devnull, 'w')

app = Flask(__name__)

# Configuration - Read from environment variables
USERNAME = os.environ.get('PORTAL_USERNAME', '3202')
PASSWORD = os.environ.get('PORTAL_PASSWORD', 'xoxo')
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8956255769:AAFOd4Opa2-v3WFdaVJCERP1U5fjL4LrLKQ')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '-1003909386800')

class SMSPortal:
    def __init__(self, username, password):
        self.session = requests.Session()
        self.username = username
        self.password = password
        self.base_url = "https://mysmsportal.com"
        self.seen_hashes = set()
        self.running = True
        self.message_queue = deque()
        
    def login(self):
        """Login to the portal"""
        login_url = f"{self.base_url}/index.php?login=1"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        login_data = {'user': self.username, 'password': self.password}
        
        self.session.headers.update(headers)
        response = self.session.post(login_url, data=login_data)
        
        return "User name and password needed" not in response.text
    
    def convert_date_to_digits(self, date_str):
        """Convert date from '31-MAY-2026' to '31-05-2026' format"""
        month_map = {
            'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
            'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
            'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
        }
        
        for month_name, month_num in month_map.items():
            if month_name in date_str.upper():
                return date_str.upper().replace(month_name, month_num)
        return date_str
    
    def escape_html(self, text):
        """Escape HTML special characters to prevent parsing errors"""
        if not text:
            return text
        return html.escape(text)
    
    def mask_phone_number(self, phone):
        """Mask phone number - show only first 3 and last 4 digits"""
        if not phone:
            return "N/A"
        
        # Remove any non-digit characters
        digits = re.sub(r'\D', '', str(phone))
        
        if len(digits) <= 7:
            return phone
        
        # Show first 3 and last 4 digits, mask the rest with *
        first_3 = digits[:3]
        last_4 = digits[-4:]
        masked = '*' * (len(digits) - 7)
        
        return f"{first_3}{masked}{last_4}"
    
    def submit_form_and_get_table2(self, form, form_action, form_method, form_data):
        """Submit a single form and extract TABLE 2 messages"""
        try:
            if form_action:
                if form_action.startswith('/'):
                    submit_url = f"{self.base_url}{form_action}"
                elif form_action.startswith('http'):
                    submit_url = form_action
                else:
                    submit_url = f"{self.base_url}/{form_action}"
            else:
                submit_url = f"{self.base_url}/index.php?opt=shw_sum"
            
            if form_method == 'POST':
                response = self.session.post(submit_url, data=form_data, timeout=30)
            else:
                response = self.session.get(submit_url, params=form_data, timeout=30)
            
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            tables = soup.find_all('table')
            
            if len(tables) < 2:
                return []
            
            table = tables[1]
            rows = table.find_all('tr')
            messages = []
            
            for row in rows[1:]:
                cells = row.find_all('td')
                if len(cells) >= 5:
                    date_time = cells[0].get_text(strip=True)
                    date_time = self.convert_date_to_digits(date_time)
                    
                    range_name = cells[1].get_text(strip=True)
                    sender = cells[2].get_text(strip=True)
                    receiver = cells[3].get_text(strip=True)
                    message_body = cells[4].get_text(strip=True)
                    
                    # Mask the phone number
                    receiver = self.mask_phone_number(receiver)
                    
                    # Escape HTML characters in message body
                    message_body = self.escape_html(message_body)
                    
                    country = range_name.split('-')[0].strip() if '-' in range_name else "Unknown"
                    
                    message_string = f"{date_time}_{receiver}_{message_body}"
                    message_hash = hashlib.md5(message_string.encode()).hexdigest()
                    
                    messages.append({
                        'hash': message_hash,
                        'date_time': date_time,
                        'range': range_name,
                        'country': country,
                        'sender': sender,
                        'receiver': receiver,
                        'message': message_body
                    })
            
            return messages
            
        except Exception as e:
            return []
    
    def get_all_forms_and_submit(self, html_content):
        """Extract all forms and submit each one to get TABLE 2 messages"""
        if not html_content:
            return []
        
        soup = BeautifulSoup(html_content, 'html.parser')
        forms = soup.find_all('form')
        
        if not forms:
            return []
        
        all_messages = []
        
        for form in forms:
            form_action = form.get('action', '')
            form_method = form.get('method', 'POST').upper()
            
            base_form_data = {}
            for inp in form.find_all('input', type='hidden'):
                name = inp.get('name')
                value = inp.get('value', '')
                if name:
                    base_form_data[name] = value
            
            selects = form.find_all('select')
            
            if selects:
                for select in selects:
                    select_name = select.get('name')
                    if select_name:
                        options = select.find_all('option')
                        for option in options:
                            opt_value = option.get('value', '')
                            if opt_value:
                                form_data = base_form_data.copy()
                                form_data[select_name] = opt_value
                                
                                submit_btn = form.find(['button', 'input'], type='submit')
                                if submit_btn:
                                    btn_name = submit_btn.get('name')
                                    btn_value = submit_btn.get('value', 'Submit')
                                    if btn_name:
                                        form_data[btn_name] = btn_value
                                
                                messages = self.submit_form_and_get_table2(
                                    form, form_action, form_method, form_data
                                )
                                all_messages.extend(messages)
            else:
                submit_btn = form.find(['button', 'input'], type='submit')
                if submit_btn:
                    btn_name = submit_btn.get('name')
                    btn_value = submit_btn.get('value', 'Submit')
                    if btn_name:
                        base_form_data[btn_name] = btn_value
                
                messages = self.submit_form_and_get_table2(
                    form, form_action, form_method, base_form_data
                )
                all_messages.extend(messages)
        
        return all_messages
    
    def get_all_messages_from_all_forms(self):
        """Get ALL messages from ALL forms' TABLE 2"""
        summary_url = f"{self.base_url}/index.php?opt=shw_sum"
        response = self.session.get(summary_url, timeout=30)
        
        if response.status_code != 200:
            return []
        
        all_messages = []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all('table')
        if len(tables) >= 2:
            table = tables[1]
            rows = table.find_all('tr')
            for row in rows[1:]:
                cells = row.find_all('td')
                if len(cells) >= 5:
                    date_time = cells[0].get_text(strip=True)
                    date_time = self.convert_date_to_digits(date_time)
                    
                    range_name = cells[1].get_text(strip=True)
                    sender = cells[2].get_text(strip=True)
                    receiver = cells[3].get_text(strip=True)
                    message_body = cells[4].get_text(strip=True)
                    
                    # Mask the phone number
                    receiver = self.mask_phone_number(receiver)
                    
                    # Escape HTML characters
                    message_body = self.escape_html(message_body)
                    
                    country = range_name.split('-')[0].strip() if '-' in range_name else "Unknown"
                    message_string = f"{date_time}_{receiver}_{message_body}"
                    message_hash = hashlib.md5(message_string.encode()).hexdigest()
                    
                    all_messages.append({
                        'hash': message_hash,
                        'date_time': date_time,
                        'range': range_name,
                        'country': country,
                        'sender': sender,
                        'receiver': receiver,
                        'message': message_body
                    })
        
        form_messages = self.get_all_forms_and_submit(response.text)
        all_messages.extend(form_messages)
        
        seen = set()
        unique_messages = []
        for msg in all_messages:
            if msg['hash'] not in seen:
                seen.add(msg['hash'])
                unique_messages.append(msg)
        
        unique_messages.sort(key=lambda x: x['date_time'], reverse=True)
        return unique_messages
    
    def format_telegram_message(self, message):
        """Format message with blockquote style"""
        
        country_name = message['country']
        flag = "🏳️"
        
        formatted = f"""<blockquote>⏰ <b>Time:</b> {message['date_time']}</blockquote>
<blockquote>🌍 <b>Country:</b> {country_name} {flag}</blockquote>
<blockquote>📌 <b>Sender:</b> ❓ {message['sender']}</blockquote>
<blockquote>☎️ <b>Number:</b> {message['receiver']}</blockquote>
<blockquote>🌐 <b>Range:</b> {message['range']}</blockquote>

<b>💬 Message:</b>
<blockquote>{message['message']}</blockquote>

Panel - Mediatel"""
        
        return formatted
    
    def send_to_telegram(self, bot_token, chat_id, message):
        """Send message to Telegram"""
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        BUTTON1_TEXT = "👨‍💻 Developer"
        BUTTON1_URL = "https://t.me/prince_ACTIVE1"
        
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": BUTTON1_TEXT, "url": BUTTON1_URL}
                ]
            ]
        }
        
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
            'reply_markup': reply_markup
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            return False
    
    def send_last_message(self, bot_token, chat_id):
        """Send only ONE last message"""
        all_messages = self.get_all_messages_from_all_forms()
        
        if not all_messages:
            return 0
        
        # Get only the most recent message
        last_message = all_messages[:1]
        
        sent_count = 0
        for msg in last_message:
            formatted_msg = self.format_telegram_message(msg)
            
            if self.send_to_telegram(bot_token, chat_id, formatted_msg):
                sent_count += 1
                self.seen_hashes.add(msg['hash'])
            
            time.sleep(0.5)
        
        # Mark all messages as seen
        for msg in all_messages:
            self.seen_hashes.add(msg['hash'])
        
        return sent_count
    
    def monitor_all_forms_forever(self, bot_token, chat_id):
        """Monitor ALL forms continuously"""
        message_buffer = []
        
        all_messages = self.get_all_messages_from_all_forms()
        for msg in all_messages:
            self.seen_hashes.add(msg['hash'])
        
        last_hash = all_messages[0]['hash'] if all_messages else None
        
        while self.running:
            try:
                fresh_messages = self.get_all_messages_from_all_forms()
                
                if fresh_messages:
                    current_hash = fresh_messages[0]['hash']
                    
                    if current_hash != last_hash:
                        for msg in fresh_messages:
                            if msg['hash'] not in self.seen_hashes:
                                self.seen_hashes.add(msg['hash'])
                                message_buffer.append(msg)
                        
                        if message_buffer:
                            message_buffer.sort(key=lambda x: x['date_time'])
                            
                            for msg in message_buffer:
                                formatted_msg = self.format_telegram_message(msg)
                                self.send_to_telegram(bot_token, chat_id, formatted_msg)
                            
                            message_buffer.clear()
                            last_hash = current_hash
                
                time.sleep(0.5)
                
            except Exception as e:
                time.sleep(0.005)

# Start monitoring in background
portal = SMSPortal(USERNAME, PASSWORD)
if portal.login():
    portal.send_last_message(BOT_TOKEN, CHAT_ID)
    monitor_thread = threading.Thread(target=portal.monitor_all_forms_forever, args=(BOT_TOKEN, CHAT_ID))
    monitor_thread.daemon = True
    monitor_thread.start()

@app.route('/')
def index():
    return jsonify({'status': 'active', 'service': 'SMS Monitor'})

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
