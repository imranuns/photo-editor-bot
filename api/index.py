import os
import requests
from flask import Flask, request
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import io
import json
import time

app = Flask(__name__)

# --- Environment Variables ---
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

# --- Database Functions (JSONBin.io) ---
def get_db():
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY: raise Exception("JSONBin API Key or Bin ID is missing.")
    headers = {'X-Master-Key': JSONBIN_API_KEY, 'X-Bin-Meta': 'false'}
    req = requests.get(f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}', headers=headers)
    req.raise_for_status()
    return req.json()

def update_db(data):
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY: raise Exception("JSONBin API Key or Bin ID is missing.")
    headers = {'Content-Type': 'application/json', 'X-Master-Key': JSONBIN_API_KEY}
    req = requests.put(f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}', json=data, headers=headers)
    req.raise_for_status()

def get_user_data(user_id):
    db_data = get_db()
    return db_data.get('users', {}).get(str(user_id))

def update_user_data(user_id, data):
    db_data = get_db()
    if 'users' not in db_data: db_data['users'] = {}
    db_data['users'][str(user_id)] = data
    update_db(db_data)

# --- Telegram Functions ---
def send_telegram_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def send_or_edit_photo(chat_id, image, caption, message_id=None, reply_markup=None):
    output_buffer = io.BytesIO()
    image.save(output_buffer, format='JPEG', quality=95)
    output_buffer.seek(0)
    final_reply_markup = reply_markup if reply_markup is not None else {'inline_keyboard': []}
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
    return None

# --- Image Processing Functions ---
def get_image_from_telegram(file_id):
    try:
        file_path_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
        res = requests.get(file_path_url).json()
        file_path = res['result']['file_path']
        image_download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        image_res = requests.get(image_download_url)
        return Image.open(io.BytesIO(image_res.content)).convert("RGB")
    except Exception as e:
        print(f"Error downloading image: {e}")
        return None

def apply_adjustment(image, adjustment_type, value):
    if adjustment_type == 'brightness': enhancer = ImageEnhance.Brightness(image)
    elif adjustment_type == 'contrast': enhancer = ImageEnhance.Contrast(image)
    elif adjustment_type == 'saturation': enhancer = ImageEnhance.Color(image)
    elif adjustment_type == 'warmth':
        r, g, b = image.split()
        r = r.point(lambda i: i * (1 + 0.08 * value))
        b = b.point(lambda i: i * (1 - 0.08 * value))
        return Image.merge('RGB', (r, g, b))
    elif adjustment_type == 'shadow':
        enhancer = ImageEnhance.Brightness(image)
        return enhancer.enhance(1 + 0.15 * value)
    else: return image
    return enhancer.enhance(1 + 0.15 * value)

def apply_filter(image, filter_type):
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

# --- UI Menus ---
def get_main_menu():
    return {"inline_keyboard": [[{"text": "🎨 Filters", "callback_data": "menu_filters"}, {"text": "🛠️ Adjust", "callback_data": "menu_adjust"}]]}
def get_filters_menu():
    return {"inline_keyboard": [
        [{"text": "🌈 Saturation", "callback_data": "filter_saturate"}, {"text": "✨ Enhance", "callback_data": "filter_enhance"}],
        [{"text": "⚡ Dynamic", "callback_data": "filter_dynamic"}, {"text": "💨 Airy", "callback_data": "filter_airy"}],
        [{"text": "🎬 Cinematic", "callback_data": "filter_cinematic"}, {"text": "⚫ Noir (B&W)", "callback_data": "filter_noir"}],
        [{"text": "↩️ Back to Main Menu", "callback_data": "menu_main"}]
    ]}
def get_adjust_menu():
    return {"inline_keyboard": [
        [{"text": "☀️ Brightness", "callback_data": "adjust_brightness"}, {"text": "🌗 Contrast", "callback_data": "adjust_contrast"}],
        [{"text": "🎨 Saturation", "callback_data": "adjust_saturation"}, {"text": "🌡️ Warmth", "callback_data": "adjust_warmth"}],
        [{"text": "🌒 Shadow", "callback_data": "adjust_shadow"}, {"text": "↩️ Reset", "callback_data": "adjust_reset"}],
        [{"text": "✅ Apply & Send", "callback_data": "adjust_send"}, {"text": "↩️ Back to Main Menu", "callback_data": "menu_main"}]
    ]}
def get_adjust_submenu(tool):
    return {"inline_keyboard": [
        [{"text": "➕ Increase", "callback_data": f"do_{tool}_1"}, {"text": "➖ Decrease", "callback_data": f"do_{tool}_-1"}],
        [{"text": "↩️ Back to Adjust Menu", "callback_data": "menu_adjust"}]
    ]}

# --- Webhook Handler ---
@app.route('/', methods=['POST'])
def webhook():
    update = request.get_json()
    
    if 'callback_query' in update:
        callback_query = update['callback_query']
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        message_id = callback_query['message']['message_id']
        user_id = callback_query['from']['id']
        
        user_data = get_user_data(user_id)
        session = user_data.get('session', {})

        if not session.get('file_id'):
            send_telegram_message(chat_id, "Sorry, your photo session has expired. Please send the photo again.")
            return 'ok'

        original_image = get_image_from_telegram(session['file_id'])
        current_image = Image.open(io.BytesIO(bytes.fromhex(session['current_image_hex']))) if 'current_image_hex' in session else original_image.copy()

        if data == 'menu_main':
            send_or_edit_photo(chat_id, current_image, "Choose a category:", message_id=message_id, reply_markup=get_main_menu())
        elif data == 'menu_filters':
            send_or_edit_photo(chat_id, current_image, "Select a one-click filter:", message_id=message_id, reply_markup=get_filters_menu())
        elif data == 'menu_adjust':
            send_or_edit_photo(chat_id, current_image, "Adjust tools:", message_id=message_id, reply_markup=get_adjust_menu())

        elif data.startswith('filter_'):
            filter_type = data.split('_')[1]
            edited_image = apply_filter(original_image, filter_type)
            send_or_edit_photo(chat_id, edited_image, f"✅ Filter *{filter_type.capitalize()}* applied!", message_id=message_id, reply_markup=None)
            user_data['session'] = {}
            update_user_data(user_id, user_data)

        elif data.startswith('adjust_'):
            tool = data.split('_')[1]
            if tool == 'send':
                send_or_edit_photo(chat_id, current_image, "✅ Your final edit has been sent!", message_id=message_id, reply_markup=None)
                user_data['session'] = {}
                update_user_data(user_id, user_data)
            elif tool == 'reset':
                current_image = original_image.copy()
                output_buffer = io.BytesIO()
                current_image.save(output_buffer, format='JPEG')
                session['current_image_hex'] = output_buffer.getvalue().hex()
                user_data['session'] = session
                update_user_data(user_id, user_data)
                send_or_edit_photo(chat_id, current_image, "🔄 Image has been reset to original.", message_id=message_id, reply_markup=get_adjust_menu())
            else:
                send_or_edit_photo(chat_id, current_image, f"Adjusting *{tool.capitalize()}*. Use the buttons below.", message_id=message_id, reply_markup=get_adjust_submenu(tool))

        elif data.startswith('do_'):
            parts = data.split('_')
            tool, value = parts[1], int(parts[2])
            current_image = apply_adjustment(current_image, tool, value)
            output_buffer = io.BytesIO()
            current_image.save(output_buffer, format='JPEG')
            session['current_image_hex'] = output_buffer.getvalue().hex()
            user_data['session'] = session
            update_user_data(user_id, user_data)
            send_or_edit_photo(chat_id, current_image, "Preview:", message_id=message_id, reply_markup=get_adjust_submenu(tool))
        return 'ok'

    if 'message' in update:
        message = update['message']
        user_id = message['from']['id']
        chat_id = message['chat']['id']
        user_name = message['from'].get('first_name', 'User')
        text = message.get('text', '')

        if 'new_chat_members' in message:
            group_id = message['chat']['id']
            adder_id = message['from']['id']
            adder_name = message['from'].get('first_name', 'User')
            user_data = get_user_data(adder_id)
            if user_data:
                task = user_data.get('add_task', {})
                if task.get('group_id') == group_id and not task.get('completed'):
                    new_member_count = len(message['new_chat_members'])
                    task['added_count'] = task.get('added_count', 0) + new_member_count
                    if task['added_count'] >= MEMBERS_TO_ADD:
                        task['completed'] = True
                        user_data['credits'] = user_data.get('credits', 0) + CREDITS_FOR_ADDING_MEMBERS
                        completion_message = f"🎉 እንኳን ደስ አለዎት {adder_name}! *{MEMBERS_TO_ADD}* ሰዎችን ስለጨመሩ *{CREDITS_FOR_ADDING_MEMBERS}* ክሬዲቶችን አግኝተዋል።\n\nአሁን ፎቶዎችን ማስተካከል ይችላሉ። እዚህ ጋር ይንኩ 👉 @{BOT_USERNAME}"
                        send_telegram_message(group_id, completion_message)
                    user_data['add_task'] = task
                    update_user_data(adder_id, user_data)
            return 'ok'

        command_parts = text.split()
        command = command_parts[0].lower()
        args = command_parts[1:]
        
        is_admin = str(user_id) == ADMIN_ID
        user_data = get_user_data(user_id)

        if not user_data:
            invited_by = args[0] if len(args) > 0 and command == '/start' else None
            user_data = {'credits': 0, 'invited_by': invited_by, 'add_task': {}, 'session': {}}
            update_user_data(user_id, user_data)
            if invited_by:
                inviter_data = get_user_data(invited_by)
                if inviter_data:
                    inviter_data['credits'] = inviter_data.get('credits', 0) + INVITE_CREDIT_AWARD
                    update_user_data(invited_by, inviter_data)
                    send_telegram_message(invited_by, f"🎉 Someone joined using your link! You've earned *{INVITE_CREDIT_AWARD}* credit(s).")

        if command == '/start':
            start_message = "👋 Hello {user_name}!\n\nWelcome to the Photo Editor Bot.\n\nHere are the available commands:\n\n📸 `/edit` - Start editing a new photo.\n💰 `/mycredit` - Check your credit balance.\n🔗 `/mylink` - Get your personal invite link.\n🎁 `/unlock` - Earn credits by adding members in a group.\n🆘 `/support` - Contact the admin for help."
            send_telegram_message(chat_id, start_message.format(user_name=user_name))

        elif command == '/edit':
            if user_data.get('credits', 0) < EDIT_COST:
                send_telegram_message(chat_id, f"❌ You don't have enough credits to edit. You need *{EDIT_COST}* credit(s).")
            else:
                user_data['session'] = {'status': 'waiting_for_photo'}
                update_user_data(user_id, user_data)
                send_telegram_message(chat_id, "Please send me the photo you want to edit now.")
        
        elif command == '/mycredit':
            send_telegram_message(chat_id, f"💰 You currently have *{user_data.get('credits', 0)}* credits.")

        elif command == '/mylink':
            invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
            send_telegram_message(chat_id, f"🔗 Here is your personal invite link:\n\n`{invite_link}`")

        elif command == '/unlock':
            if chat_id < 0:
                user_data['add_task'] = {'group_id': chat_id, 'added_count': 0, 'completed': False}
                update_user_data(user_id, user_data)
                send_telegram_message(chat_id, f"✅ Task started for {user_name}!\n\nNow, add *{MEMBERS_TO_ADD}* members to this group to earn *{CREDITS_FOR_ADDING_MEMBERS}* credits. I must be an admin to count the members.")
            else:
                send_telegram_message(chat_id, "This command only works in a group.")
        
        elif command == '/support':
             if not args:
                send_telegram_message(chat_id, "Please enter your message after the command.\nExample: `/support Hello`")
             else:
                support_message = " ".join(args)
                forward_message = f"🆘 *New Support Message*\n\n*From:* {user_name} (ID: `{user_id}`)\n\n*Message:* {support_message}"
                if ADMIN_ID: send_telegram_message(ADMIN_ID, forward_message)
                send_telegram_message(chat_id, "✅ Your message has been sent to the admin.")

        elif is_admin and command == '/status':
            db_data = get_db()
            user_count = len(db_data.get('users', {}))
            send_telegram_message(chat_id, f"📊 *Bot Status*\n\nTotal Users: *{user_count}*")

        elif is_admin and command == '/broadcast':
            if not args:
                send_telegram_message(chat_id, "Usage: `/broadcast <message>`")
            else:
                broadcast_text = " ".join(args)
                db_data = get_db()
                users = db_data.get('users', {})
                sent_count = 0
                for uid in users.keys():
                    try:
                        send_telegram_message(uid, broadcast_text)
                        sent_count += 1
                        time.sleep(0.1)
                    except Exception: pass
                send_telegram_message(chat_id, f"✅ Broadcast sent to *{sent_count}* of *{len(users)}* users.")

        elif is_admin and command == '/addcredit':
            if len(args) == 2:
                target_user_id, amount = args[0], int(args[1])
                target_data = get_user_data(target_user_id)
                if target_data:
                    target_data['credits'] = target_data.get('credits', 0) + amount
                    update_user_data(target_user_id, target_data)
                    send_telegram_message(chat_id, f"✅ Successfully added *{amount}* credits to user `{target_user_id}`.")
                    send_telegram_message(target_user_id, f"🎉 Admin has added *{amount}* credits to your account!")
                else: send_telegram_message(chat_id, "❌ User not found.")
            else: send_telegram_message(chat_id, "Usage: `/addcredit <user_id> <amount>`")
        
        elif 'photo' in message:
            session = user_data.get('session', {})
            if session.get('status') == 'waiting_for_photo':
                user_data['credits'] -= EDIT_COST
                
                file_id = message['photo'][-1]['file_id']
                image = get_image_from_telegram(file_id)
                if image:
                    message_id = send_or_edit_photo(chat_id, image, "Photo received! Choose a category:", reply_markup=get_main_menu())
                    if message_id:
                        output_buffer = io.BytesIO()
                        image.save(output_buffer, format='JPEG')
                        current_image_hex = output_buffer.getvalue().hex()
                        
                        user_data['session'] = {'file_id': file_id, 'message_id': message_id, 'current_image_hex': current_image_hex}
                        update_user_data(user_id, user_data)
                else: send_telegram_message(chat_id, "❌ Sorry, I couldn't download your photo.")
            else:
                send_telegram_message(chat_id, "To edit a photo, please send the `/edit` command first.")
        
    return 'ok'

@app.route('/')
def index():
    return "Advanced Photo Editor Bot - Session Fixed!"
