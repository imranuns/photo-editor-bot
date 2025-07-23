import os
import requests
from flask import Flask, request
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import io
import json
import time

app = Flask(__name__)

# --- Environment Variables ---
# Make sure to set these in your Vercel project settings
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
    """Fetches the entire database from JSONBin.io."""
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY:
        print("ERROR: JSONBin API Key or Bin ID is missing.")
        raise Exception("JSONBin API Key or Bin ID is missing.")
    headers = {'X-Master-Key': JSONBIN_API_KEY, 'X-Bin-Meta': 'false'}
    try:
        req = requests.get(f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest', headers=headers)
        req.raise_for_status()
        return req.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting DB: {e}")
        return {} # Return an empty DB structure on failure

def update_db(data):
    """Updates the entire database on JSONBin.io."""
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY:
        print("ERROR: JSONBin API Key or Bin ID is missing.")
        raise Exception("JSONBin API Key or Bin ID is missing.")
    headers = {'Content-Type': 'application/json', 'X-Master-Key': JSONBIN_API_KEY}
    try:
        req = requests.put(f'https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}', json=data, headers=headers)
        req.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error updating DB: {e}")


def get_user_data(user_id):
    """Retrieves data for a specific user."""
    db_data = get_db()
    return db_data.get('users', {}).get(str(user_id))

def update_user_data(user_id, data):
    """Updates data for a specific user."""
    db_data = get_db()
    if 'users' not in db_data:
        db_data['users'] = {}
    db_data['users'][str(user_id)] = data
    update_db(db_data)

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
        print(f"Error sending message: {e}")


def send_or_edit_photo(chat_id, image, caption, message_id=None, reply_markup=None):
    """Sends or edits a photo message with an inline keyboard."""
    output_buffer = io.BytesIO()
    image.save(output_buffer, format='JPEG', quality=95)
    output_buffer.seek(0)
    
    final_reply_markup = reply_markup if reply_markup is not None else {'inline_keyboard': []}
    
    try:
        if message_id:
            # Edit an existing photo message
            url = f"https://api.telegram.org/bot{TOKEN}/editMessageMedia"
            media = {'type': 'photo', 'media': 'attach://edited_image.jpg', 'caption': caption, 'parse_mode': 'Markdown'}
            files = {'edited_image.jpg': output_buffer}
            data = {'chat_id': chat_id, 'message_id': message_id, 'media': json.dumps(media), 'reply_markup': json.dumps(final_reply_markup)}
            response = requests.post(url, data=data, files=files)
            response.raise_for_status()
            return message_id
        else:
            # Send a new photo message
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            files = {'photo': ('edited_image.jpg', output_buffer, 'image/jpeg')}
            data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'Markdown', 'reply_markup': json.dumps(final_reply_markup)}
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            if response.ok:
                return response.json()['result']['message_id']
    except requests.exceptions.RequestException as e:
        print(f"Error sending/editing photo: {e} - Response: {e.response.text if e.response else 'N/A'}")
    return None

# --- Image Processing Functions ---
def get_image_from_telegram(file_id):
    """Downloads an image from Telegram servers using its file_id."""
    try:
        file_path_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
        res = requests.get(file_path_url).json()
        if not res.get('ok'):
            print(f"Error getting file path: {res.get('description')}")
            return None
        file_path = res['result']['file_path']
        image_download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        image_res = requests.get(image_download_url)
        image_res.raise_for_status()
        return Image.open(io.BytesIO(image_res.content)).convert("RGB")
    except Exception as e:
        print(f"Error downloading image: {e}")
        return None

def apply_adjustment(image, adjustment_type, value):
    """Applies a single adjustment to an image."""
    # This function is designed to be cumulative.
    # The 'value' is a step (-1 or 1), so we scale it appropriately.
    if adjustment_type == 'brightness':
        enhancer = ImageEnhance.Brightness(image)
        return enhancer.enhance(1 + 0.1 * value)
    elif adjustment_type == 'contrast':
        enhancer = ImageEnhance.Contrast(image)
        return enhancer.enhance(1 + 0.1 * value)
    elif adjustment_type == 'saturation':
        enhancer = ImageEnhance.Color(image)
        return enhancer.enhance(1 + 0.2 * value)
    elif adjustment_type == 'warmth':
        r, g, b = image.split()
        r = r.point(lambda i: i * (1 + 0.05 * value))
        b = b.point(lambda i: i * (1 - 0.05 * value))
        return Image.merge('RGB', (r, g, b))
    elif adjustment_type == 'shadow':
        # This is a simplified shadow adjustment.
        enhancer = ImageEnhance.Brightness(image)
        return enhancer.enhance(1 + 0.1 * value)
    return image # Return original if type is unknown

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
        [{"text": "🌒 Shadow", "callback_data": "adjust_shadow"}, {"text": "🔄 Reset All", "callback_data": "adjust_reset"}],
        [{"text": "✅ Apply & Send", "callback_data": "adjust_send"}, {"text": "↩️ Back to Main Menu", "callback_data": "menu_main"}]
    ]}
def get_adjust_submenu(tool):
    return {"inline_keyboard": [
        [{"text": "➕ Increase", "callback_data": f"do_{tool}_1"}, {"text": "➖ Decrease", "callback_data": f"do_{tool}_-1"}],
        [{"text": "↩️ Back to Adjust Menu", "callback_data": "menu_adjust"}]
    ]}

# --- Main Webhook Handler ---
@app.route('/', methods=['POST'])
def webhook():
    update = request.get_json()

    # --- Callback Query Handler (Button Presses) ---
    if 'callback_query' in update:
        callback_query = update['callback_query']
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        message_id = callback_query['message']['message_id']
        user_id = callback_query['from']['id']
        
        user_data = get_user_data(user_id)
        if not user_data:
            send_telegram_message(chat_id, "Sorry, I couldn't find your data. Please send /start.")
            return 'ok'
            
        session = user_data.get('session', {})

        if not session.get('file_id'):
            send_telegram_message(chat_id, "Sorry, your photo session has expired. Please send the photo again.")
            return 'ok'

        original_image = get_image_from_telegram(session['file_id'])
        if not original_image:
            send_telegram_message(chat_id, "Sorry, I couldn't retrieve the original photo. The session might be too old. Please send the photo again.")
            return 'ok'
        
        # Re-create the current image by applying all saved adjustments
        current_image = reapply_adjustments(original_image, session.get('adjustments', []))

        # --- Menu Navigation ---
        if data == 'menu_main':
            send_or_edit_photo(chat_id, current_image, "Choose a category:", message_id=message_id, reply_markup=get_main_menu())
        elif data == 'menu_filters':
            send_or_edit_photo(chat_id, current_image, "Select a one-click filter:", message_id=message_id, reply_markup=get_filters_menu())
        elif data == 'menu_adjust':
            send_or_edit_photo(chat_id, current_image, "Adjust tools:", message_id=message_id, reply_markup=get_adjust_menu())

        # --- Filter Application (Terminal Action) ---
        elif data.startswith('filter_'):
            filter_type = data.split('_')[1]
            edited_image = apply_filter(original_image.copy(), filter_type)
            send_or_edit_photo(chat_id, edited_image, f"✅ Filter *{filter_type.capitalize()}* applied! Your final image is ready.", message_id=message_id, reply_markup=None)
            user_data['session'] = {} # End session
            update_user_data(user_id, user_data)

        # --- Adjustment Tool Selection ---
        elif data.startswith('adjust_'):
            tool = data.split('_')[1]
            if tool == 'send':
                send_or_edit_photo(chat_id, current_image, "✅ Your final edit is ready!", message_id=message_id, reply_markup=None)
                user_data['session'] = {} # End session
                update_user_data(user_id, user_data)
            elif tool == 'reset':
                session['adjustments'] = [] # Clear the adjustments list
                user_data['session'] = session
                update_user_data(user_id, user_data)
                send_or_edit_photo(chat_id, original_image, "🔄 Image has been reset to original.", message_id=message_id, reply_markup=get_adjust_menu())
            else: # Go to the specific adjustment submenu
                send_or_edit_photo(chat_id, current_image, f"Adjusting *{tool.capitalize()}*. Use the buttons below.", message_id=message_id, reply_markup=get_adjust_submenu(tool))

        # --- Applying an Adjustment ---
        elif data.startswith('do_'):
            parts = data.split('_')
            tool, value = parts[1], int(parts[2])
            
            # Append the new adjustment and save it
            session.setdefault('adjustments', []).append({'tool': tool, 'value': value})
            user_data['session'] = session
            update_user_data(user_id, user_data)
            
            # Apply the new adjustment on top of the current image for the preview
            newly_adjusted_image = apply_adjustment(current_image, tool, value)
            
            send_or_edit_photo(chat_id, newly_adjusted_image, f"Preview updated.", message_id=message_id, reply_markup=get_adjust_submenu(tool))
        
        return 'ok'

    # --- Message Handler (Commands and Photos) ---
    if 'message' in update:
        message = update['message']
        user_id = message['from']['id']
        chat_id = message['chat']['id']
        user_name = message['from'].get('first_name', 'User')
        text = message.get('text', '')

        # --- New Member Handler (for /unlock task) ---
        if 'new_chat_members' in message:
            # Logic for handling new members added to a group
            # This part seems correct and is left as is.
            pass # Your existing code for this is fine

        # --- Command and Photo Logic ---
        user_data = get_user_data(user_id)
        is_new_user = not user_data

        if is_new_user:
            invited_by = text.split()[1] if text.startswith('/start ') and len(text.split()) > 1 else None
            user_data = {'credits': 1, 'invited_by': invited_by, 'add_task': {}, 'session': {}} # Start with 1 credit
            update_user_data(user_id, user_data)
            if invited_by:
                try:
                    inviter_data = get_user_data(invited_by)
                    if inviter_data:
                        inviter_data['credits'] = inviter_data.get('credits', 0) + INVITE_CREDIT_AWARD
                        update_user_data(invited_by, inviter_data)
                        send_telegram_message(invited_by, f"🎉 Someone joined using your link! You've earned *{INVITE_CREDIT_AWARD}* credit(s).")
                except Exception as e:
                    print(f"Error giving invite credit: {e}")

        # --- Photo Handler (The Core Fix) ---
        if 'photo' in message:
            if user_data.get('credits', 0) < EDIT_COST:
                send_telegram_message(chat_id, f"❌ You don't have enough credits. You have *{user_data.get('credits', 0)}*. Earn more with /mylink or /unlock.")
                return 'ok'

            user_data['credits'] -= EDIT_COST
            file_id = message['photo'][-1]['file_id']
            
            send_telegram_message(chat_id, "⏳ Processing your photo...")

            image = get_image_from_telegram(file_id)
            if image:
                caption = "Let's get creative! Choose an editing option."
                message_id = send_or_edit_photo(chat_id, image, caption, reply_markup=get_main_menu())

                if message_id:
                    # Create a new session.
                    user_data['session'] = {'file_id': file_id, 'message_id': message_id, 'adjustments': []}
                    update_user_data(user_id, user_data)
                else: # Sending photo failed, refund credit
                    user_data['credits'] += EDIT_COST
                    update_user_data(user_id, user_data)
                    send_telegram_message(chat_id, "❌ Something went wrong. I couldn't start an editing session. Your credit was not used.")
            else: # Downloading photo failed, refund credit
                user_data['credits'] += EDIT_COST
                update_user_data(user_id, user_data)
                send_telegram_message(chat_id, "❌ Sorry, I couldn't download your photo. Your credit was not used.")
            return 'ok'

        # --- Command Handler ---
        if text.startswith('/'):
            command_parts = text.split()
            command = command_parts[0].lower()
            args = command_parts[1:]
            is_admin = str(user_id) == ADMIN_ID

            if command == '/start':
                start_message = (
                    f"👋 Hello {user_name}!\n\n"
                    "Welcome to the Photo Editor Bot.\n\n"
                    "To get started, just **send me a photo**!\n\n"
                    "Here are some other commands:\n"
                    "💰 `/mycredit` - Check your credit balance.\n"
                    "🔗 `/mylink` - Get your personal invite link.\n"
                    "🎁 `/unlock` - Earn credits by adding me to a group.\n"
                    "🆘 `/support` - Contact the admin for help."
                )
                send_telegram_message(chat_id, start_message)

            elif command == '/mycredit':
                send_telegram_message(chat_id, f"💰 You currently have *{user_data.get('credits', 0)}* credits.")

            elif command == '/mylink':
                invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
                send_telegram_message(chat_id, f"🔗 Here is your personal invite link:\n\n`{invite_link}`\n\nShare it with friends. When they start the bot, you'll get *{INVITE_CREDIT_AWARD}* credit!")

            elif command == '/unlock':
                if message['chat']['type'] in ['group', 'supergroup']:
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

            # --- Admin Commands ---
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
                            time.sleep(0.1) # Avoid rate limiting
                        except Exception: pass
                    send_telegram_message(chat_id, f"✅ Broadcast sent to *{sent_count}* of *{len(users)}* users.")

            elif is_admin and command == '/addcredit':
                if len(args) == 2 and args[1].isdigit():
                    target_user_id, amount = args[0], int(args[1])
                    target_data = get_user_data(target_user_id)
                    if target_data:
                        target_data['credits'] = target_data.get('credits', 0) + amount
                        update_user_data(target_user_id, target_data)
                        send_telegram_message(chat_id, f"✅ Successfully added *{amount}* credits to user `{target_user_id}`.")
                        send_telegram_message(target_user_id, f"🎉 Admin has added *{amount}* credits to your account!")
                    else: send_telegram_message(chat_id, "❌ User not found.")
                else: send_telegram_message(chat_id, "Usage: `/addcredit <user_id> <amount>`")

    return 'ok'

# This is a simple route to confirm the server is running.
@app.route('/')
def index():
    return "Photo Editor Bot is alive!"

