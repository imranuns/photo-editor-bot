import os
import requests
from flask import Flask, request
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import io
import json
import time

app = Flask(__name__)

# --- Environment Variables ---
# These must be set in your Vercel project settings
TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID')
JSONBIN_API_KEY = os.environ.get('JSONBIN_API_KEY')
JSONBIN_BIN_ID = os.environ.get('JSONBIN_BIN_ID')
BOT_USERNAME = os.environ.get('BOT_USERNAME')

# --- Constants ---
CREDITS_FOR_ADDING_MEMBERS = 15
MEMBERS_TO_ADD = 10
INVITE_CREDIT_AWARD = 1
EDIT_COST = 1

# --- Optimized Database Functions (JSONBin.io) ---
def get_db():
    """Fetches the entire database from JSONBin.io ONCE."""
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY:
        print("ስህተት: የJSONBin ኤፒአይ ቁልፍ ወይም የቢን መለያ ጠፍቷል።")
        raise Exception("JSONBin API Key or Bin ID is missing.")
    headers = {'X-Master-Key': JSONBIN_API_KEY, 'X-Bin-Meta': 'false'}
    try:
        req = requests.get(f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest', headers=headers)
        req.raise_for_status()
        return req.json()
    except requests.exceptions.RequestException as e:
        print(f"ዳታቤዙን በማምጣት ላይ ስህተት ተፈጥሯል: {e}")
        return {'users': {}} # On failure, return a valid empty structure

def update_db(data):
    """Updates the entire database on JSONBin.io ONCE."""
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY:
        print("ስህተት: የJSONBin ኤፒአይ ቁልፍ ወይም የቢን መለያ ጠፍቷል።")
        raise Exception("JSONBin API Key or Bin ID is missing.")
    headers = {'Content-Type': 'application/json', 'X-Master-Key': JSONBIN_API_KEY}
    try:
        req = requests.put(f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}', json=data, headers=headers)
        req.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"ዳታቤዙን በማዘመን ላይ ስህተት ተፈጥሯል: {e}")

# --- Telegram API Functions ---
def send_telegram_message(chat_id, text, reply_markup=None):
    """Sends a text message using the Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"መልዕክት በመላክ ላይ ስህተት ተፈጥሯል: {e}")

def answer_callback_query(callback_query_id):
    """Answers a callback query to remove the loading state on the button."""
    url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
    payload = {'callback_query_id': callback_query_id}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Callback query በመመለስ ላይ ስህተት: {e}")

def send_or_edit_photo(chat_id, image, caption, message_id=None, reply_markup=None):
    """Sends or edits a photo message with an inline keyboard."""
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
            response = requests.post(url, data=data, files=files)
            response.raise_for_status()
            return message_id
        else:
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            files = {'photo': ('edited_image.jpg', output_buffer, 'image/jpeg')}
            data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'Markdown', 'reply_markup': json.dumps(final_reply_markup)}
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            if response.ok:
                return response.json()['result']['message_id']
    except requests.exceptions.RequestException as e:
        print(f"ፎቶ በመላክ/በማስተካከል ላይ ስህተት ተፈጥሯል: {e} - Response: {e.response.text if e.response else 'N/A'}")
    return None

# --- Image Processing Functions ---
def get_image_from_telegram(file_id):
    """Downloads an image from Telegram servers using its file_id."""
    try:
        file_path_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
        res = requests.get(file_path_url).json()
        if not res.get('ok'):
            print(f"የፋይል ዱካ በማግኘት ላይ ስህተት: {res.get('description')}")
            return None
        file_path = res['result']['file_path']
        image_download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        image_res = requests.get(image_download_url)
        image_res.raise_for_status()
        return Image.open(io.BytesIO(image_res.content)).convert("RGB")
    except Exception as e:
        print(f"ፎቶ በማውረድ ላይ ስህተት: {e}")
        return None

def apply_adjustment(image, adjustment_type, value):
    """Applies a single adjustment to an image."""
    if adjustment_type == 'brightness':
        return ImageEnhance.Brightness(image).enhance(1 + 0.1 * value)
    elif adjustment_type == 'contrast':
        return ImageEnhance.Contrast(image).enhance(1 + 0.1 * value)
    elif adjustment_type == 'saturation':
        return ImageEnhance.Color(image).enhance(1 + 0.2 * value)
    elif adjustment_type == 'warmth':
        r, g, b = image.split()
        r = r.point(lambda i: i * (1 + 0.05 * value))
        b = b.point(lambda i: i * (1 - 0.05 * value))
        return Image.merge('RGB', (r, g, b))
    elif adjustment_type == 'shadow':
        return ImageEnhance.Brightness(image).enhance(1 + 0.1 * value)
    return image

def reapply_adjustments(original_image, adjustments):
    """Re-applies a list of adjustments to the original image."""
    img = original_image.copy()
    for adj in adjustments:
        img = apply_adjustment(img, adj['tool'], adj['value'])
    return img

def apply_filter(image, filter_type):
    """Applies a one-time filter to an image."""
    if filter_type == 'saturate': return ImageEnhance.Color(image).enhance(1.5)
    elif filter_type == 'enhance':
        enhanced_image = ImageEnhance.Contrast(image).enhance(1.4)
        enhanced_image = ImageEnhance.Color(enhanced_image).enhance(1.2)
        enhanced_image = ImageEnhance.Sharpness(enhanced_image).enhance(1.3)
        return enhanced_image
    elif filter_type == 'dynamic': return ImageEnhance.Contrast(image).enhance(1.5).filter(ImageFilter.SHARPEN)
    elif filter_type == 'airy': return ImageEnhance.Color(ImageEnhance.Brightness(image).enhance(1.2)).enhance(0.8)
    elif filter_type == 'cinematic':
        desaturated = ImageEnhance.Color(image).enhance(0.6)
        contrasted = ImageEnhance.Contrast(desaturated).enhance(1.4)
        blue_layer = Image.new('RGB', contrasted.size, '#001122')
        return Image.blend(contrasted, blue_layer, alpha=0.2)
    elif filter_type == 'noir': return ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(1.8)
    return image

# --- UI Menus (Amharic) ---
def get_start_menu():
    """Generates the main menu for the /start command."""
    return {"inline_keyboard": [
        [{"text": "💰 ክሬዲቴን አሳይ", "callback_data": "mycredit"}, {"text": "🔗 መጋበዣ ሊንክ", "callback_data": "mylink"}],
        [{"text": "🆘 እርዳታ", "callback_data": "support"}]
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

# --- Main Webhook Handler ---
@app.route('/', methods=['POST'])
def webhook():
    update = request.get_json()
    db_data = None 
    db_changed = False 

    # --- Callback Query Handler (Button Presses) ---
    if 'callback_query' in update:
        callback_query = update['callback_query']
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        message_id = callback_query['message']['message_id']
        user_id = str(callback_query['from']['id'])
        
        db_data = get_db()
        user_data = db_data.get('users', {}).get(user_id)

        if not user_data:
            answer_callback_query(callback_query['id'])
            send_telegram_message(chat_id, "ይቅርታ, የእርስዎን መረጃ ማግኘት አልቻልኩም። እባክዎ /start ብለው እንደገና ይጀምሩ።")
            return 'ok'
            
        # --- Main Menu Button Handlers ---
        if data == 'mycredit':
            answer_callback_query(callback_query['id'])
            credit_balance = user_data.get('credits', 0)
            send_telegram_message(chat_id, f"💰 አሁን ያለዎት *{credit_balance}* ክሬዲት ነው።")
            return 'ok'
        
        elif data == 'mylink':
            answer_callback_query(callback_query['id'])
            invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
            send_telegram_message(chat_id, f"🔗 የእርስዎ የግል መጋበዣ ሊንክ ይኸውና:\n\n`{invite_link}`\n\nለጓደኞችዎ ያጋሩ።")
            return 'ok'

        elif data == 'support':
            answer_callback_query(callback_query['id'])
            send_telegram_message(chat_id, "🆘 ለእርዳታ ወይም አስተያየት ለመስጠት፣ መልዕክትዎን በዚህ መልኩ ይላኩ:\n`/support የእርስዎ መልዕክት`")
            return 'ok'

        # --- Photo Editing Session Handlers ---
        session = user_data.get('session', {})

        if not session.get('file_id'):
            answer_callback_query(callback_query['id'])
            send_telegram_message(chat_id, "ይቅርታ, የፎቶ ክፍለ ጊዜዎ ጊዜው አልፎበታል። እባክዎ ፎቶውን እንደገና ይላኩ።")
            return 'ok'

        original_image = get_image_from_telegram(session['file_id'])
        if not original_image:
            answer_callback_query(callback_query['id'])
            send_telegram_message(chat_id, "ይቅርታ, ዋናውን ፎቶ ማግኘት አልቻልኩም። እባክዎ ፎቶውን እንደገና ይላኩ።")
            return 'ok'
        
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
            send_or_edit_photo(chat_id, edited_image, f"✅ *{filter_type.capitalize()}* ማጣሪያ ተተግብሯል! የመጨረሻው ፎቶዎ ዝግጁ ነው።", message_id=message_id, reply_markup=None)
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

    # --- Handler for Bot Status Changes (e.g., being added to a group) ---
    if 'my_chat_member' in update:
        my_chat_member = update['my_chat_member']
        new_status = my_chat_member.get('new_chat_member', {}).get('status')
        
        if new_status in ['member', 'administrator']:
            adder_id = str(my_chat_member['from']['id'])
            group_id = my_chat_member['chat']['id']
            
            db_data = get_db()
            users_data = db_data.get('users', {})
            adder_data = users_data.get(adder_id)

            if adder_data:
                adder_data['add_task'] = {'group_id': group_id, 'added_count': 0, 'completed': False}
                users_data[adder_id] = adder_data
                update_db(db_data)
                
                adder_name = my_chat_member['from'].get('first_name', 'User')
                send_telegram_message(group_id, f"✅ ቦቱ ገብቷል። {adder_name} አሁን *{MEMBERS_TO_ADD}* ሰዎችን በመጨመር *{CREDITS_FOR_ADDING_MEMBERS}* ክሬዲቶችን ማግኘት ይችላሉ።")
        
        return 'ok'

    # --- Message Handler (Commands, Photos, New Members) ---
    if 'message' in update:
        message = update['message']
        user_id = str(message['from']['id'])
        chat_id = message['chat']['id']
        user_name = message['from'].get('first_name', 'User')
        text = message.get('text', '')

        db_data = get_db()
        users_data = db_data.get('users', {})
        
        if 'new_chat_members' in message:
            adder_id = str(message['from']['id'])
            adder_name = message['from'].get('first_name', 'User')
            adder_data = users_data.get(adder_id)

            if adder_data:
                task = adder_data.get('add_task', {})
                if task.get('group_id') == chat_id and not task.get('completed'):
                    new_member_count = len([m for m in message['new_chat_members'] if not m.get('is_bot')])
                    if new_member_count > 0:
                        task['added_count'] = task.get('added_count', 0) + new_member_count
                        
                        if task['added_count'] >= MEMBERS_TO_ADD:
                            task['completed'] = True
                            adder_data['credits'] = adder_data.get('credits', 0) + CREDITS_FOR_ADDING_MEMBERS
                            
                            completion_message = (
                                f"🎉 እንኳን ደስ አለዎት {adder_name}! *{MEMBERS_TO_ADD}* ሰዎችን ስለጨመሩ *{CREDITS_FOR_ADDING_MEMBERS}* ክሬዲቶችን አግኝተዋል።\n\n"
                                f"አሁን ፎቶዎችን ማስተካከል ይችላሉ። እዚህ ጋር ይንኩ 👉 @{BOT_USERNAME}"
                            )
                            send_telegram_message(chat_id, completion_message)
                            
                        adder_data['add_task'] = task
                        users_data[adder_id] = adder_data
                        update_db(db_data)
            return 'ok'

        user_data = users_data.get(user_id)
        is_new_user = not user_data

        if is_new_user:
            invited_by = text.split()[1] if text.startswith('/start ') and len(text.split()) > 1 else None
            user_data = {'credits': 1, 'invited_by': invited_by, 'add_task': {}, 'session': {}}
            users_data[user_id] = user_data
            db_changed = True
            
            if invited_by:
                try:
                    inviter_data = users_data.get(str(invited_by))
                    if inviter_data:
                        inviter_data['credits'] = inviter_data.get('credits', 0) + INVITE_CREDIT_AWARD
                        users_data[str(invited_by)] = inviter_data
                        send_telegram_message(invited_by, f"🎉 አንድ ሰው በእርስዎ ሊንክ ተጠቅሞ ስለገባ *{INVITE_CREDIT_AWARD}* ክሬዲት አግኝተዋል።")
                except Exception as e:
                    print(f"የግብዣ ክሬዲት በመስጠት ላይ ስህተት: {e}")

        if 'photo' in message:
            if not user_data:
                send_telegram_message(chat_id, "እባክዎ መጀመሪያ ቦቱን በ /start ትዕዛዝ ያስጀምሩት።")
                return 'ok'

            if user_data.get('credits', 0) < EDIT_COST:
                send_telegram_message(chat_id, f"❌ በቂ ክሬዲት የለዎትም። ያለዎት *{user_data.get('credits', 0)}* ነው። ተጨማሪ ክሬዲት ለማግኘት ጓደኛዎችዎን ይጋብዙ።")
                return 'ok'

            user_data['credits'] -= EDIT_COST
            db_changed = True
            file_id = message['photo'][-1]['file_id']
            
            send_telegram_message(chat_id, "⏳ ፎቶዎን በማዘጋጀት ላይ ነው...")

            image = get_image_from_telegram(file_id)
            if image:
                caption = "የማስተካከያ አይነት ይምረጡ።"
                message_id = send_or_edit_photo(chat_id, image, caption, reply_markup=get_main_menu())

                if message_id:
                    user_data['session'] = {'file_id': file_id, 'message_id': message_id, 'adjustments': []}
                else:
                    user_data['credits'] += EDIT_COST
                    send_telegram_message(chat_id, "❌ ስህተት ተፈጥሯል። የኤዲቲንግ ክፍለ ጊዜ መጀመር አልተቻለም። ክሬዲትዎ አልተቀነሰም።")
            else:
                user_data['credits'] += EDIT_COST
                send_telegram_message(chat_id, "❌ ይቅርታ, ፎቶዎን ማውረድ አልተቻለም። ክሬዲትዎ አልተቀነሰም።")
            
            users_data[user_id] = user_data
            update_db(db_data)
            return 'ok'

        if text.startswith('/'):
            command_parts = text.split()
            command = command_parts[0].lower()
            args = command_parts[1:]
            is_admin = user_id == ADMIN_ID
            
            if not user_data and command != '/start':
                 send_telegram_message(chat_id, "እባክዎ መጀመሪያ ቦቱን በ /start ትዕዛዝ ያስጀምሩት።")
                 return 'ok'

            if command == '/start':
                start_message = (
                    f"👋 ሰላም {user_name}!\n\n"
                    "ወደ ፎቶ ማስተካከያ ቦት እንኳን በደህና መጡ።\n\n"
                    "ለመጀመር በቀላሉ **ፎቶ ይላኩልኝ** ወይም ከታች ያሉትን አማራጮች ይጠቀሙ።"
                )
                send_telegram_message(chat_id, start_message, reply_markup=get_start_menu())
            
            elif command == '/support':
                if not args:
                    send_telegram_message(chat_id, "እባክዎ ከትዕዛዙ በኋላ መልዕክትዎን ያስገቡ።\nምሳሌ: `/support ሰላም`")
                else:
                    support_message = " ".join(args)
                    forward_message = f"🆘 *አዲስ የድጋፍ መልዕክት*\n\n*ከ:* {user_name} (ID: `{user_id}`)\n\n*መልዕክት:* {support_message}"
                    if ADMIN_ID: send_telegram_message(ADMIN_ID, forward_message)
                    send_telegram_message(chat_id, "✅ መልዕክትዎ ለአስተዳዳሪው ተልኳል።")

            # Admin commands...
            elif is_admin and command == '/status':
                user_count = len(users_data)
                send_telegram_message(chat_id, f"📊 *የቦት ሁኔታ*\n\nጠቅላላ ተጠቃሚዎች: *{user_count}*")

            elif is_admin and command == '/broadcast':
                if not args:
                    send_telegram_message(chat_id, "አጠቃቀም: `/broadcast <message>`")
                else:
                    broadcast_text = " ".join(args)
                    sent_count = 0
                    for uid in users_data.keys():
                        try:
                            send_telegram_message(uid, broadcast_text)
                            sent_count += 1
                            time.sleep(0.1) 
                        except Exception: pass
                    send_telegram_message(chat_id, f"✅ መልዕክቱ ለ *{sent_count}* ከ *{len(users_data)}* ተጠቃሚዎች ተልኳል።")

            elif is_admin and command == '/addcredit':
                if len(args) == 2 and args[1].isdigit():
                    target_user_id, amount = args[0], int(args[1])
                    target_data = users_data.get(target_user_id)
                    if target_data:
                        target_data['credits'] = target_data.get('credits', 0) + amount
                        users_data[target_user_id] = target_data
                        db_changed = True
                        send_telegram_message(chat_id, f"✅ *{amount}* ክሬዲት ለተጠቃሚ `{target_user_id}` በተሳካ ሁኔታ ተጨምሯል።")
                        send_telegram_message(target_user_id, f"🎉 አስተዳዳሪው *{amount}* ክሬዲት ወደ አካውንትዎ ጨምሯል!")
                    else: send_telegram_message(chat_id, "❌ ተጠቃሚው አልተገኘም።")
                else: send_telegram_message(chat_id, "አጠቃቀም: `/addcredit <user_id> <amount>`")


        if db_changed:
            db_data['users'] = users_data
            update_db(db_data)

    return 'ok'

@app.route('/')
def index():
    return "Photo Editor Bot is alive and fully automated!"
