import os
import requests
from flask import Flask, request
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import io
import json

app = Flask(__name__)

# --- Environment Variables ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')

# --- Session Management ---
# Stores the state of the user's current editing session
# {'file_id': str, 'original_image': PIL.Image, 'current_image': PIL.Image, 'message_id': int}
user_photo_session = {}

# --- Telegram Functions ---
def send_telegram_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def edit_telegram_message(chat_id, message_id, text, reply_markup=None):
    """Edits an existing text message, typically to remove buttons."""
    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def send_or_edit_photo(chat_id, image, caption, message_id=None, reply_markup=None):
    """Sends a new photo or edits an existing one, now with button support."""
    output_buffer = io.BytesIO()
    image.save(output_buffer, format='JPEG', quality=95)
    output_buffer.seek(0)
    
    if message_id:
        url = f"https://api.telegram.org/bot{TOKEN}/editMessageMedia"
        media = {'type': 'photo', 'media': 'attach://edited_image.jpg', 'caption': caption}
        files = {'edited_image.jpg': output_buffer}
        data = {'chat_id': chat_id, 'message_id': message_id, 'media': json.dumps(media)}
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        requests.post(url, data=data, files=files)
        return message_id
    else:
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        files = {'photo': ('edited_image.jpg', output_buffer, 'image/jpeg')}
        data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'Markdown'}
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        response = requests.post(url, files=files, data=data)
        if response.ok:
            return response.json()['result']['message_id']
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
    """Applies an adjustment to the image."""
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
    """Applies a one-click filter."""
    if filter_type == 'saturate': return ImageEnhance.Color(image).enhance(1.5)
    elif filter_type == 'enhance': return ImageEnhance.Contrast(ImageEnhance.Color(image).enhance(1.4)).enhance(1.4)
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
        [{"text": "↩️ Back", "callback_data": "menu_main"}]
    ]}

def get_adjust_menu():
    return {"inline_keyboard": [
        [{"text": "☀️ Brightness", "callback_data": "adjust_brightness"}, {"text": "🌗 Contrast", "callback_data": "adjust_contrast"}],
        [{"text": "🎨 Saturation", "callback_data": "adjust_saturation"}, {"text": "🌡️ Warmth", "callback_data": "adjust_warmth"}],
        [{"text": "🌒 Shadow", "callback_data": "adjust_shadow"}, {"text": "↩️ Reset", "callback_data": "adjust_reset"}],
        [{"text": "✅ Apply & Send", "callback_data": "adjust_send"}, {"text": "↩️ Back", "callback_data": "menu_main"}]
    ]}

def get_adjust_submenu(tool):
    return {"inline_keyboard": [
        [{"text": "➕ Increase", "callback_data": f"do_{tool}_1"}, {"text": "➖ Decrease", "callback_data": f"do_{tool}_-1"}],
        [{"text": "↩️ Back to Adjust", "callback_data": "menu_adjust"}]
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
        
        session = user_photo_session.get(chat_id)
        if not session:
            edit_telegram_message(chat_id, message_id, "Sorry, your photo session has expired. Please send the photo again.")
            return 'ok'

        if data == 'menu_main':
            send_or_edit_photo(chat_id, session['current_image'], "Choose a category:", message_id=session.get('message_id'), reply_markup=get_main_menu())
        elif data == 'menu_filters':
            send_or_edit_photo(chat_id, session['current_image'], "Select a one-click filter:", message_id=session.get('message_id'), reply_markup=get_filters_menu())
        elif data == 'menu_adjust':
            send_or_edit_photo(chat_id, session['current_image'], "Adjust tools:", message_id=session.get('message_id'), reply_markup=get_adjust_menu())

        elif data.startswith('filter_'):
            filter_type = data.split('_')[1]
            edit_telegram_message(chat_id, message_id, f"🎨 Applying *{filter_type.capitalize()}* filter...")
            edited_image = apply_filter(session['original_image'], filter_type)
            send_or_edit_photo(chat_id, edited_image, f"✅ Filter *{filter_type.capitalize()}* applied!")
            user_photo_session.pop(chat_id, None)

        elif data.startswith('adjust_'):
            tool = data.split('_')[1]
            if tool == 'send':
                send_or_edit_photo(chat_id, session['current_image'], "✅ Your final edit has been sent!")
                user_photo_session.pop(chat_id, None)
            elif tool == 'reset':
                session['current_image'] = session['original_image'].copy()
                user_photo_session[chat_id] = session
                send_or_edit_photo(chat_id, session['current_image'], "🔄 Image has been reset to original.", message_id=session.get('message_id'), reply_markup=get_adjust_menu())
            else:
                send_or_edit_photo(chat_id, session['current_image'], f"Adjusting *{tool.capitalize()}*. Use the buttons below.", message_id=session.get('message_id'), reply_markup=get_adjust_submenu(tool))

        elif data.startswith('do_'):
            parts = data.split('_')
            tool, value = parts[1], int(parts[2])
            session['current_image'] = apply_adjustment(session['current_image'], tool, value)
            user_photo_session[chat_id] = session
            send_or_edit_photo(chat_id, session['current_image'], "Preview:", message_id=session.get('message_id'), reply_markup=get_adjust_submenu(tool))

        return 'ok'

    if 'message' in update:
        message = update['message']
        chat_id = message['chat']['id']
        
        if 'text' in message and message['text'] == '/start':
            send_telegram_message(chat_id, "👋 Welcome to the Advanced Photo Editor Bot!\n\nPlease send me a photo to get started.")
            return 'ok'

        if 'photo' in message:
            file_id = message['photo'][-1]['file_id']
            image = get_image_from_telegram(file_id)
            if image:
                # *** የተስተካከለው ክፍል ***
                # ፎቶውን ከምናሌው ጋር በአንድ ላይ እንልካለን
                message_id = send_or_edit_photo(chat_id, image, "Photo received! Choose a category:", reply_markup=get_main_menu())
                if message_id:
                    user_photo_session[chat_id] = {'file_id': file_id, 'original_image': image.copy(), 'current_image': image.copy(), 'message_id': message_id}
            else:
                send_telegram_message(chat_id, "❌ Sorry, I couldn't download your photo.")
            return 'ok'

        send_telegram_message(chat_id, "I only understand photos. Please send a photo to edit.")

    return 'ok'

@app.route('/')
def index():
    return "Advanced Photo Editor Bot is running with new features!"
