import os
import requests
from flask import Flask, request
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import io
import json
import time
from datetime import datetime, timezone

app = Flask(__name__)

# --- Environment Variables ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID')
JSONBIN_API_KEY = os.environ.get('JSONBIN_API_KEY')
JSONBIN_BIN_ID = os.environ.get('JSONBIN_BIN_ID')
BOT_USERNAME = os.environ.get('BOT_USERNAME')
# CHANNEL_USERNAME is now optional/fallback
DEFAULT_CHANNEL = os.environ.get('CHANNEL_USERNAME') 

# --- Constants ---
INVITE_CREDIT_AWARD = 5 # ጋባዡ የሚያገኘው
EDIT_COST = 1
DAILY_BONUS_AMOUNT = 5 # ሁሉም ተጠቃሚ በቀን የሚያገኘው

# --- Database Functions ---
def get_db():
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY: return {'users': {}, 'settings': {'channels': []}}
    headers = {'X-Master-Key': JSONBIN_API_KEY, 'X-Bin-Meta': 'false'}
    try:
        req = requests.get(f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest', headers=headers)
        data = req.json() if req.status_code == 200 else {'users': {}, 'settings': {'channels': []}}
        if 'settings' not in data: data['settings'] = {'channels': []}
        if 'channels' not in data['settings']: data['settings']['channels'] = []
        if not data['settings']['channels'] and DEFAULT_CHANNEL:
            data['settings']['channels'].append(DEFAULT_CHANNEL)
        return data
    except: return {'users': {}, 'settings': {'channels': []}}

def update_db(data):
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY: return
    headers = {'Content-Type': 'application/json', 'X-Master-Key': JSONBIN_API_KEY}
    try: requests.put(f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}', json=data, headers=headers)
    except: pass

# --- Telegram Helper Functions ---
def send_telegram_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    try: requests.post(url, json=payload)
    except Exception as e: print(f"Error sending msg: {e}")

def copy_message(chat_id, from_chat_id, message_id, reply_markup=None):
    """Copies any message exactly as is, including buttons."""
    url = f"https://api.telegram.org/bot{TOKEN}/copyMessage"
    payload = {
        'chat_id': chat_id, 
        'from_chat_id': from_chat_id, 
        'message_id': message_id
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
        
    try: 
        res = requests.post(url, json=payload)
        return res.json().get('ok')
    except: return False

def forward_message(chat_id, from_chat_id, message_id):
    url = f"https://api.telegram.org/bot{TOKEN}/forwardMessage"
    payload = {'chat_id': chat_id, 'from_chat_id': from_chat_id, 'message_id': message_id}
    try: requests.post(url, json=payload)
    except: pass

def answer_callback_query(callback_query_id, text=None, show_alert=False):
    url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
    payload = {'callback_query_id': callback_query_id, 'show_alert': show_alert}
    if text: payload['text'] = text
    try: requests.post(url, json=payload)
    except: pass

def edit_message_reply_markup(chat_id, message_id, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/editMessageReplyMarkup"
    payload = {'chat_id': chat_id, 'message_id': message_id}
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    try: requests.post(url, json=payload)
    except: pass

def delete_message(chat_id, message_id):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteMessage", json={'chat_id': chat_id, 'message_id': message_id})

def send_or_edit_photo(chat_id, image, caption, message_id=None, reply_markup=None):
    output_buffer = io.BytesIO()
    image.save(output_buffer, format='JPEG', quality=95)
    output_buffer.seek(0)
    final_reply_markup = reply_markup if reply_markup is not None else {'inline_keyboard': []}
    
    try:
        if message_id:
            url = f"https://api.telegram.org/bot{TOKEN}/editMessageMedia"
            media = {'type': 'photo', 'media': 'attach://edited_image.jpg', 'caption': caption, 'parse_mode': 'Markdown'}
            files = {'edited_image.jpg': output_buffer}
            data = {'chat_id': chat_id, 'message_id': message_id, 'media': json.dumps(media), 'reply_markup': json.dumps(final_reply_markup)}
            requests.post(url, data=data, files=files)
            return message_id
        else:
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            files = {'photo': ('edited_image.jpg', output_buffer, 'image/jpeg')}
            data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'Markdown', 'reply_markup': json.dumps(final_reply_markup)}
            response = requests.post(url, files=files, data=data)
            if response.ok: return response.json()['result']['message_id']
    except Exception as e: print(f"Error sending photo: {e}")
    return None

# --- Force Join Logic ---
def get_missing_channels(user_id, channels_list):
    missing = []
    for channel in channels_list:
        url = f"https://api.telegram.org/bot{TOKEN}/getChatMember?chat_id={channel}&user_id={user_id}"
        try:
            res = requests.get(url).json()
            if res.get('ok'):
                status = res['result']['status']
                if status not in ['creator', 'administrator', 'member']:
                    missing.append(channel)
        except: pass
    return missing

def get_join_channels_markup(missing_channels):
    buttons = []
    for channel in missing_channels:
        clean_name = channel.replace('@', '')
        buttons.append([{"text": f"📢 Join {channel}", "url": f"https://t.me/{clean_name}"}])
    buttons.append([{"text": "✅ ተቀላቅያለሁ (Check)", "callback_data": "check_subscription"}])
    return {"inline_keyboard": buttons}

# --- Image Processing Functions ---
def get_image_from_telegram(file_id):
    try:
        res = requests.get(f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}").json()
        if not res.get('ok'): return None
        path = res['result']['file_path']
        img_res = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}")
        return Image.open(io.BytesIO(img_res.content)).convert("RGB")
    except: return None

def apply_adjustment(image, adjustment_type, value):
    if adjustment_type == 'brightness': return ImageEnhance.Brightness(image).enhance(1 + 0.1 * value)
    elif adjustment_type == 'contrast': return ImageEnhance.Contrast(image).enhance(1 + 0.1 * value)
    elif adjustment_type == 'saturation': return ImageEnhance.Color(image).enhance(1 + 0.2 * value)
    elif adjustment_type == 'warmth':
        r, g, b = image.split()
        r = r.point(lambda i: i * (1 + 0.05 * value))
        b = b.point(lambda i: i * (1 - 0.05 * value))
        return Image.merge('RGB', (r, g, b))
    elif adjustment_type == 'shadow': return ImageEnhance.Brightness(image).enhance(1 + 0.1 * value)
    return image

def reapply_adjustments(original_image, adjustments):
    img = original_image.copy()
    for adj in adjustments: img = apply_adjustment(img, adj['tool'], adj['value'])
    return img

def apply_filter(image, filter_type):
    if filter_type == 'saturate': return ImageEnhance.Color(image).enhance(1.5)
    elif filter_type == 'enhance':
        e = ImageEnhance.Contrast(image).enhance(1.4)
        e = ImageEnhance.Color(e).enhance(1.2)
        return ImageEnhance.Sharpness(e).enhance(1.3)
    elif filter_type == 'dynamic': return ImageEnhance.Contrast(image).enhance(1.5).filter(ImageFilter.SHARPEN)
    elif filter_type == 'airy': return ImageEnhance.Color(ImageEnhance.Brightness(image).enhance(1.2)).enhance(0.8)
    elif filter_type == 'cinematic':
        d = ImageEnhance.Color(image).enhance(0.6)
        c = ImageEnhance.Contrast(d).enhance(1.4)
        return Image.blend(c, Image.new('RGB', c.size, '#001122'), alpha=0.2)
    elif filter_type == 'noir': return ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(1.8)
    return image

# --- UI Menus ---
def get_start_menu():
    return {"inline_keyboard": [
        [{"text": "💰 ክሬዲቴን አሳይ", "callback_data": "mycredit"}, {"text": "🔗 መጋበዣ ሊንክ", "callback_data": "mylink"}],
        [{"text": "🆘 እርዳታ (Support)", "callback_data": "support"}]
    ]}

def get_admin_menu():
    return {"inline_keyboard": [
        [{"text": "➕ ቻናል ጨምር", "callback_data": "admin_add_channel"}, {"text": "➖ ቻናል ቀንስ", "callback_data": "admin_list_remove"}],
        [{"text": "📋 የቻናል ዝርዝር", "callback_data": "admin_list_view"}, {"text": "📊 Status", "callback_data": "admin_status"}]
    ]}

def get_main_menu():
    return {"inline_keyboard": [[{"text": "🎨 ማጣሪያዎች (Filters)", "callback_data": "menu_filters"}, {"text": "🛠️ ማስተካከያዎች (Adjust)", "callback_data": "menu_adjust"}]]}

def get_filters_menu():
    return {"inline_keyboard": [
        [{"text": "🌈 Saturation", "callback_data": "filter_saturate"}, {"text": "✨ Enhance", "callback_data": "filter_enhance"}],
        [{"text": "⚡ Dynamic", "callback_data": "filter_dynamic"}, {"text": "💨 Airy", "callback_data": "filter_airy"}],
        [{"text": "🎬 Cinematic", "callback_data": "filter_cinematic"}, {"text": "⚫ Noir (B&W)", "callback_data": "filter_noir"}],
        [{"text": "↩️ ወደ ዋና ማውጫ ተመለስ", "callback_data": "menu_main"}]
    ]}

def get_adjust_menu():
    return {"inline_keyboard": [
        [{"text": "☀️ Brightness", "callback_data": "adjust_brightness"}, {"text": "🌗 Contrast", "callback_data": "adjust_contrast"}],
        [{"text": "🎨 Saturation", "callback_data": "adjust_saturation"}, {"text": "🌡️ Warmth", "callback_data": "adjust_warmth"}],
        [{"text": "🌒 Shadow", "callback_data": "adjust_shadow"}, {"text": "🔄 ሁሉንም መልስ", "callback_data": "adjust_reset"}],
        [{"text": "✅ ተግብር እና ላክ", "callback_data": "adjust_send"}, {"text": "↩️ ወደ ዋና ማውጫ ተመለስ", "callback_data": "menu_main"}]
    ]}

def get_adjust_submenu(tool):
    return {"inline_keyboard": [
        [{"text": "➕ ጨምር", "callback_data": f"do_{tool}_1"}, {"text": "➖ ቀንስ", "callback_data": f"do_{tool}_-1"}],
        [{"text": "↩️ ወደ ማስተካከያ ማውጫ ተመለስ", "callback_data": "menu_adjust"}]
    ]}

def process_daily_bonus(user_data):
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    last_bonus = user_data.get('last_bonus_date')
    bonus_given = False
    if last_bonus != today_str:
        user_data['credits'] = user_data.get('credits', 0) + DAILY_BONUS_AMOUNT
        user_data['last_bonus_date'] = today_str
        bonus_given = True
    user_data['last_seen'] = today_str
    return user_data, bonus_given

# --- Webhook ---
@app.route('/favicon.ico')
def favicon(): return '', 204

@app.route('/', methods=['POST'])
def webhook():
    update = request.get_json()
    db_changed = False
    
    # --- Callback Query Handler ---
    if 'callback_query' in update:
        cq = update['callback_query']
        chat_id = cq['message']['chat']['id']
        message_id = cq['message']['message_id']
        user_id = str(cq['from']['id'])
        data = cq['data']
        
        db_data = get_db()
        user_data = db_data.get('users', {}).get(user_id)
        current_channels = db_data.get('settings', {}).get('channels', [])

        # 1. Force Join Check (Button)
        if data == 'check_subscription':
            missing = get_missing_channels(user_id, current_channels)
            if not missing:
                delete_message(chat_id, message_id)
                send_telegram_message(chat_id, "✅ አመሰግናለሁ! አሁን ቦቱን መጠቀም ይችላሉ። ፎቶ ይላኩ!")
            else:
                answer_callback_query(cq['id'], text=f"❌ አሁንም {len(missing)} ቻናል አልተቀላቀሉም።", show_alert=True)
            return 'ok'

        # 2. Admin Panel Actions
        if str(user_id) == ADMIN_ID:
            if data == 'admin_add_channel':
                answer_callback_query(cq['id'])
                if not user_data: user_data = {'credits': 999, 'session': {}}
                user_data.setdefault('session', {})['status'] = 'waiting_for_channel_add'
                db_data['users'][user_id] = user_data
                update_db(db_data)
                send_telegram_message(chat_id, "➕ የቻናሉን Username (ለምሳሌ @havivss) ይላኩ።")
                return 'ok'
            
            elif data == 'admin_list_remove':
                answer_callback_query(cq['id'])
                if not current_channels:
                    send_telegram_message(chat_id, "📭 ምንም የተመዘገበ ቻናል የለም።")
                else:
                    keyboard = []
                    for ch in current_channels:
                        keyboard.append([{"text": f"🗑 Remove {ch}", "callback_data": f"admin_del_{ch}"}])
                    keyboard.append([{"text": "🔙 Back", "callback_data": "admin_home"}])
                    edit_message_reply_markup(chat_id, message_id, {"inline_keyboard": keyboard})
                return 'ok'
            
            elif data.startswith('admin_del_'):
                channel_to_remove = data.replace('admin_del_', '')
                if channel_to_remove in current_channels:
                    current_channels.remove(channel_to_remove)
                    db_data['settings']['channels'] = current_channels
                    update_db(db_data)
                    answer_callback_query(cq['id'], text=f"{channel_to_remove} ተወግዷል።")
                    keyboard = [[{"text": f"🗑 Remove {ch}", "callback_data": f"admin_del_{ch}"}] for ch in current_channels]
                    keyboard.append([{"text": "🔙 Back", "callback_data": "admin_home"}])
                    edit_message_reply_markup(chat_id, message_id, {"inline_keyboard": keyboard})
                else:
                    answer_callback_query(cq['id'], text="ቻናሉ አልተገኘም።")
                return 'ok'

            elif data == 'admin_list_view':
                answer_callback_query(cq['id'])
                ch_text = "\n".join(current_channels) if current_channels else "None"
                send_telegram_message(chat_id, f"📋 *የተመዘገቡ ቻናሎች:*\n{ch_text}")
                return 'ok'
            
            elif data == 'admin_status':
                total = len(db_data.get('users', {}))
                today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                active = sum(1 for u in db_data.get('users', {}).values() if u.get('last_seen') == today)
                answer_callback_query(cq['id'], text=f"Users: {total}\nActive Today: {active}", show_alert=True)
                return 'ok'
            
            elif data == 'admin_home':
                edit_message_reply_markup(chat_id, message_id, get_admin_menu())
                return 'ok'

        if not user_data:
            answer_callback_query(cq['id'], text="Session expired.")
            return 'ok'

        # Regular Menu Logic
        if data == 'mycredit':
            answer_callback_query(cq['id'])
            send_telegram_message(chat_id, f"💰 አሁን ያለዎት *{user_data.get('credits', 0)}* ክሬዲት ነው።")
            return 'ok'
        elif data == 'mylink':
            answer_callback_query(cq['id'])
            invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
            send_telegram_message(chat_id, f"🔗 የእርስዎ የግል መጋበዣ ሊንክ ይኸውና:\n\n`{invite_link}`\n\nይህንን ሊንክ ለጓደኞችዎ ሲልኩ ለአንድ ሰው *{INVITE_CREDIT_AWARD}* ክሬዲት ያገኛሉ!")
            return 'ok'
        elif data == 'support':
            answer_callback_query(cq['id'])
            user_data['session']['status'] = 'waiting_for_support'
            db_data['users'][user_id] = user_data
            update_db(db_data)
            send_telegram_message(chat_id, "📩 *የእርዳታ ማዕከል*\n\nአስተያየት ወይም ጥያቄ ካለዎት፣ አሁን መልዕክቶን ይጻፉ እና ይላኩ። በቀጥታ ለአድሚኑ ይደርሳል።")
            return 'ok'

        # Photo Editing Logic
        session = user_data.get('session', {})
        if not session.get('file_id'): return 'ok'
        original_image = get_image_from_telegram(session['file_id'])
        if not original_image: return 'ok'
        answer_callback_query(cq['id'])
        current_image = reapply_adjustments(original_image, session.get('adjustments', []))

        if data == 'menu_main':
            send_or_edit_photo(chat_id, current_image, "የማስተካከያ አይነት ይምረጡ:", message_id=message_id, reply_markup=get_main_menu())
        elif data == 'menu_filters':
            send_or_edit_photo(chat_id, current_image, "አንድ ማጣሪያ ይምረጡ:", message_id=message_id, reply_markup=get_filters_menu())
        elif data == 'menu_adjust':
            send_or_edit_photo(chat_id, current_image, "የማስተካከያ መሳሪያ ይምረጡ:", message_id=message_id, reply_markup=get_adjust_menu())
        elif data.startswith('filter_'):
            filter_type = data.split('_')[1]
            edited_image = apply_filter(original_image.copy(), filter_type)
            send_or_edit_photo(chat_id, edited_image, f"✅ *{filter_type.capitalize()}* ማጣሪያ ተተግብሯል!", message_id=message_id, reply_markup=None)
            user_data['session'] = {}
            db_changed = True
        elif data.startswith('adjust_'):
            tool = data.split('_')[1]
            if tool == 'send':
                send_or_edit_photo(chat_id, current_image, "✅ የእርስዎ የመጨረሻ ፎቶ ዝግጁ ነው!", message_id=message_id, reply_markup=None)
                user_data['session'] = {}
                db_changed = True
            elif tool == 'reset':
                session['adjustments'] = []
                user_data['session'] = session
                db_changed = True
                send_or_edit_photo(chat_id, original_image, "🔄 ፎቶው ወደ መጀመሪያው ተመልሷል።", message_id=message_id, reply_markup=get_adjust_menu())
            else:
                send_or_edit_photo(chat_id, current_image, f"*{tool.capitalize()}* በማስተካከል ላይ...", message_id=message_id, reply_markup=get_adjust_submenu(tool))
        elif data.startswith('do_'):
            parts = data.split('_')
            tool, value = parts[1], int(parts[2])
            session.setdefault('adjustments', []).append({'tool': tool, 'value': value})
            user_data['session'] = session
            db_changed = True
            newly_adjusted_image = apply_adjustment(current_image, tool, value)
            send_or_edit_photo(chat_id, newly_adjusted_image, "ቅድመ-እይታ ታድሷል።", message_id=message_id, reply_markup=get_adjust_submenu(tool))
        
        if db_changed:
            db_data['users'][user_id] = user_data
            update_db(db_data)
        return 'ok'

    # --- Message Handler ---
    if 'message' in update:
        msg = update['message']
        chat_id = msg['chat']['id']
        user_id = str(msg['from']['id'])
        text = msg.get('text', '')
        
        db_data = get_db()
        users_data = db_data.get('users', {})
        user_data = users_data.get(user_id)
        current_channels = db_data.get('settings', {}).get('channels', [])

        # 1. Force Join Check
        is_admin = str(user_id) == ADMIN_ID
        if current_channels and not is_admin:
            missing = get_missing_channels(user_id, current_channels)
            if missing:
                send_telegram_message(chat_id, "⚠️ ቦቱን ለመጠቀም መጀመሪያ የሚከተሉትን ቻናሎች መቀላቀል አለብዎት።", reply_markup=get_join_channels_markup(missing))
                return 'ok'

        # 2. User Init & Daily Bonus
        if not user_data:
            invited_by = text.split()[1] if text.startswith('/start ') and len(text.split()) > 1 else None
            # Initialize with 0 credits.
            user_data = {'credits': 0, 'invited_by': invited_by, 'session': {}, 'last_bonus_date': ''}
            users_data[user_id] = user_data
            db_changed = True
            # Award credit ONLY to the inviter
            if invited_by and users_data.get(invited_by):
                users_data[invited_by]['credits'] = users_data[invited_by].get('credits', 0) + INVITE_CREDIT_AWARD
                send_telegram_message(invited_by, f"🎉 ሰው ስለጋበዙ {INVITE_CREDIT_AWARD} ክሬዲት አግኝተዋል!")

        user_data, bonus_given = process_daily_bonus(user_data)
        users_data[user_id] = user_data
        if bonus_given:
            send_telegram_message(chat_id, f"🎁 *የዕለታዊ ቦነስ!* ዛሬ {DAILY_BONUS_AMOUNT} ነጻ ክሬዲት አግኝተዋል! አሁን ፎቶ ማስተካከል ይችላሉ።")
            db_changed = True

        # 3. Admin Logic
        if is_admin:
            # Broadcast State Handling
            if user_data.get('session', {}).get('status') == 'waiting_for_broadcast':
                broadcast_msg_id = msg['message_id']
                reply_markup = msg.get('reply_markup')
                
                count = 0
                send_telegram_message(chat_id, "⏳ ብሮድካስት እየተላከ ነው... (ይህ ትንሽ ጊዜ ሊወስድ ይችላል)")
                
                for uid in users_data.keys():
                    try:
                        success = copy_message(uid, chat_id, broadcast_msg_id, reply_markup)
                        if success: count += 1
                        time.sleep(0.05) 
                    except: pass
                
                send_telegram_message(chat_id, f"✅ ብሮድካስት ለ {count} ተጠቃሚዎች ተዳርሷል!")
                user_data['session']['status'] = '' 
                users_data[user_id] = user_data
                update_db(db_data)
                return 'ok'

            # Add Channel State Handling
            if user_data.get('session', {}).get('status') == 'waiting_for_channel_add':
                new_channel = text.strip()
                if new_channel.startswith('@'):
                    try:
                        res = requests.get(f"https://api.telegram.org/bot{TOKEN}/getChatMember?chat_id={new_channel}&user_id={user_id}").json()
                        if res.get('ok'):
                            if new_channel not in current_channels:
                                current_channels.append(new_channel)
                                db_data['settings']['channels'] = current_channels
                                send_telegram_message(chat_id, f"✅ {new_channel} በተሳካ ሁኔታ ተጨምሯል።")
                                update_db(db_data)
                            else: send_telegram_message(chat_id, "⚠️ ይህ ቻናል አስቀድሞ ተመዝግቧል።")
                        else: send_telegram_message(chat_id, "❌ ስህተት! ቦቱ የቻናሉ አድሚን መሆኑን ያረጋግጡ።")
                    except: send_telegram_message(chat_id, "❌ ስህተት ተፈጠረ።")
                else:
                    send_telegram_message(chat_id, "❌ ትክክለኛ Username አይደለም። በ @ ይጀምሩ።")
                user_data['session']['status'] = ''
                users_data[user_id] = user_data
                update_db(db_data)
                return 'ok'

            if text == '/admin':
                send_telegram_message(chat_id, "🛠 *Admin Control Panel*", reply_markup=get_admin_menu())
                return 'ok'

            if text == '/broadcast':
                user_data['session']['status'] = 'waiting_for_broadcast'
                users_data[user_id] = user_data
                update_db(db_data)
                send_telegram_message(chat_id, "📢 *ብሮድካስት*\n\nመላክ የሚፈልጉትን ማስታወቂያ (ጽሁፍ፣ ፎቶ፣ ቪዲዮ፣ ወዘተ) አሁን ይላኩ። ቦቱ እንዳለ ገልብጦ ለሁሉም ይልከዋል።")
                return 'ok'
            
            if text.startswith('/addcredit'):
                parts = text.split()
                if len(parts) == 3:
                    tid, amt = parts[1], int(parts[2])
                    if tid in users_data:
                        users_data[tid]['credits'] += amt
                        db_changed = True
                        send_telegram_message(chat_id, f"✅ Added {amt} to {tid}")
                        send_telegram_message(tid, f"🎉 Admin added {amt} credits!")
                return 'ok'

        # 4. Support Logic (Forwarding to Admin)
        if user_data.get('session', {}).get('status') == 'waiting_for_support':
            if ADMIN_ID:
                forward_message(ADMIN_ID, chat_id, msg['message_id'])
                context_msg = f"ℹ️ *New Support Message*\nFrom: {msg['from'].get('first_name')} (ID: `{user_id}`)"
                send_telegram_message(ADMIN_ID, context_msg)
            
            send_telegram_message(chat_id, "✅ መልዕክትዎ ለአድሚኑ ተልኳል! በቅርቡ ምላሽ ያገኛሉ።")
            user_data['session']['status'] = ''
            users_data[user_id] = user_data
            db_changed = True

        # 5. Commands
        if text == '/start':
            send_telegram_message(chat_id, f"👋 ሰላም {msg['from'].get('first_name')}!\n\nወደ ፎቶ ማስተካከያ ቦት እንኳን በደህና መጡ።\n\nፎቶ በመላክ ይጀምሩ ወይም ከታች ያሉትን አማራጮች ይጠቀሙ።", reply_markup=get_start_menu())
        
        # 6. Photo Handler
        if 'photo' in msg:
            if user_data.get('credits', 0) < EDIT_COST:
                no_credit_msg = (
                    "🚫 *ይቅርታ! በቂ ነጥብ የሎትም!*\n"
                    "📸 ምስል ለመስራት፣ ከዚህ አንዱን ይከተሉ፦\n\n"
                    f"🔗 በ invite link *{INVITE_CREDIT_AWARD}* ክሬዲት ያግኙ 🎯\n"
                    f"🎁 ወይም ነገ ሲመለሱ *{DAILY_BONUS_AMOUNT}* ነጻ ክሬዲት ያገኛሉ!\n\n"
                    "🚀 ከዚያ photo ይላኩ። 🤖✨"
                )
                send_telegram_message(chat_id, no_credit_msg)
            else:
                user_data['credits'] -= EDIT_COST
                db_changed = True
                file_id = msg['photo'][-1]['file_id']
                send_telegram_message(chat_id, "⏳ ፎቶዎን በማዘጋጀት ላይ ነው...")
                
                img = get_image_from_telegram(file_id)
                if img:
                    mid = send_or_edit_photo(chat_id, img, "የማስተካከያ አይነት ይምረጡ።", reply_markup=get_main_menu())
                    if mid:
                        user_data['session'] = {'file_id': file_id, 'message_id': mid, 'adjustments': []}
                    else:
                        user_data['credits'] += EDIT_COST
                        send_telegram_message(chat_id, "❌ Error sending photo.")
                else:
                    user_data['credits'] += EDIT_COST
                    send_telegram_message(chat_id, "❌ Error downloading photo.")
            
            users_data[user_id] = user_data
            db_changed = True

        if db_changed:
            update_db({'users': users_data, 'settings': db_data.get('settings', {})})

    return 'ok'

@app.route('/')
def index():
    return "Advanced Photo Editor Bot is running!"
