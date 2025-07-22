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
# {'file_id': str, 'image': PIL.Image, 'message_id': int}
user_photo_session = {}

# --- Telegram Functions ---
def send_telegram_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def send_or_edit_photo(chat_id, image, caption, message_id=None):
    """Sends a new photo or edits an existing one."""
    output_buffer = io.BytesIO()
    image.save(output_buffer, format='JPEG', quality=95)
    output_buffer.seek(0)
    
    if message_id:
        # Edit the existing photo message
        url = f"https://api.telegram.org/bot{TOKEN}/editMessageMedia"
        media = {
            'type': 'photo',
            'media': f'attach://edited_image.jpg'
        }
        files = {'edited_image.jpg': output_buffer}
        data = {'chat_id': chat_id, 'message_id': message_id, 'media': json.dumps(media)}
        requests.post(url, data=data, files=files)
        return message_id
    else:
        # Send a new photo message
        url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
        files = {'photo': ('edited_image.jpg', output_buffer, 'image/jpeg')}
        data = {'chat_id': chat_id, 'caption': caption}
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
    if adjustment_type == 'brightness':
        enhancer = ImageEnhance.Brightness(image)
    elif adjustment_type == 'contrast':
        enhancer = ImageEnhance.Contrast(image)
    elif adjustment_type == 'saturation':
        enhancer = ImageEnhance.Color(image)
    elif adjustment_type == 'warmth':
        # This is a creative way to simulate warmth
        r, g, b = image.split()
        r = r.point(lambda i: i * (1 + 0.1 * value))
        b = b.point(lambda i: i * (1 - 0.1 * value))
        return Image.merge('RGB', (r, g, b))
    elif adjustment_type == 'shadow':
        # This is a creative way to simulate shadow recovery
        enhancer = ImageEnhance.Brightness(image)
        return enhancer.enhance(1 + 0.1 * value) # Simplified shadow adjustment
    else:
        return image
    return enhancer.enhance(1 + 0.1 * value) # value is -1 or 1

def apply_filter(image, filter_type):
    """Applies a one-click filter."""
    if filter_type == 'saturate': return ImageEnhance.Color(image).enhance(1.5)
    elif filter_type == 'enhance': return ImageEnhance.Contrast(ImageEnhance.Color(image).enhance(1.2)).enhance(1.2)
    elif filter_type == 'dynamic': return ImageEnhance.Contrast(image).enhance(1.5).filter(ImageFilter.SHARPEN)
    elif filter_type == 'airy': return ImageEnhance.Color(ImageEnhance.Brightness(image).enhance(1.2)).enhance(0.8)
    elif filter_type == 'cinematic':
        desaturated = ImageEnhance.Color(image).enhance(0.6)
        contrasted = ImageEnhance.Contrast(desaturated).enhance(1.4)
        blue_layer = Image.new('RGB', contrasted.size, '#001122')
        return Image.blend(contrasted, blue_layer, alpha=0.2)
    elif filter_type == 'noir': return ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(1.8)
    elif filter_type == 'frame': return ImageOps.expand(image, border=int(image.width * 0.04), fill='white')
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
        [{"text": "🌒 Shadow", "callback_data": "adjust_shadow"}, {"text": "🖼️ Frame", "callback_data": "filter_frame"}],
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
            send_telegram_message(chat_id, "Sorry, your photo session has expired. Please send the photo again.")
            return 'ok'

        # --- Menu Navigation ---
        if data == 'menu_main':
            send_telegram_message(chat_id, "Choose an editing option:", reply_markup=get_main_menu())
        elif data == 'menu_filters':
            send_telegram_message(chat_id, "Select a one-click filter:", reply_markup=get_filters_menu())
        elif data == 'menu_adjust':
            send_or_edit_photo(chat_id, session['image'], "Use the tools below to adjust your image.", message_id=session.get('message_id'))
            send_telegram_message(chat_id, "Adjust tools:", reply_markup=get_adjust_menu())

        # --- Filter Application ---
        elif data.startswith('filter_'):
            filter_type = data.split('_')[1]
            send_telegram_message(chat_id, f"🎨 Applying *{filter_type.capitalize()}* filter...")
            edited_image = apply_filter(session['image'], filter_type)
            send_or_edit_photo(chat_id, edited_image, f"✅ Filter *{filter_type.capitalize()}* applied!")
            user_photo_session.pop(chat_id, None)

        # --- Adjustment Tool Selection ---
        elif data.startswith('adjust_'):
            tool = data.split('_')[1]
            if tool == 'send':
                send_telegram_message(chat_id, "✅ Your final edit has been sent!")
                user_photo_session.pop(chat_id, None)
            else:
                send_telegram_message(chat_id, f"Adjusting *{tool.capitalize()}*. Use the buttons to increase or decrease.", reply_markup=get_adjust_submenu(tool))

        # --- Adjustment Action ---
        elif data.startswith('do_'):
            parts = data.split('_')
            tool, value = parts[1], int(parts[2])
            
            session['image'] = apply_adjustment(session['image'], tool, value)
            user_photo_session[chat_id] = session # Save the updated image
            
            # Edit the photo in place without sending a new message
            send_or_edit_photo(chat_id, session['image'], "Preview:", message_id=session.get('message_id'))

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
                # Start a new session
                message_id = send_or_edit_photo(chat_id, image, "Photo received! Choose an editing option:")
                user_photo_session[chat_id] = {'file_id': file_id, 'image': image, 'message_id': message_id}
                send_telegram_message(chat_id, "Choose a category:", reply_markup=get_main_menu())
            else:
                send_telegram_message(chat_id, "❌ Sorry, I couldn't download your photo.")
            return 'ok'

        send_telegram_message(chat_id, "I only understand photos. Please send a photo to edit.")

    return 'ok'

@app.route('/')
def index():
    return "Advanced Photo Editor Bot is running!"
