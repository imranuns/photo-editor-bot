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
user_photo_session = {}

# --- Telegram Functions ---
def send_telegram_message(chat_id, text, reply_markup=None):
    """Sends a text message to the user."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def send_processed_photo(chat_id, image_bytes, caption):
    """Sends a processed photo back to the user."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    files = {'photo': ('edited_image.jpg', image_bytes, 'image/jpeg')}
    data = {'chat_id': chat_id, 'caption': caption}
    requests.post(url, files=files, data=data)

# --- Image Processing Functions ---
def get_image_from_telegram(file_id):
    """Downloads an image from Telegram and returns it as a PIL Image object."""
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

def apply_filter(image, filter_type):
    """Applies a selected filter to the image."""
    try:
        if filter_type == 'saturate':
            return ImageEnhance.Color(image).enhance(1.8)
            
        elif filter_type == 'enhance':
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.2)
            enhancer = ImageEnhance.Color(image)
            return enhancer.enhance(1.2)

        elif filter_type == 'vivid':
            color_enhancer = ImageEnhance.Color(image)
            vivid_image = color_enhancer.enhance(1.6)
            contrast_enhancer = ImageEnhance.Contrast(vivid_image)
            return contrast_enhancer.enhance(1.3)

        elif filter_type == 'dynamic':
            contrast_enhancer = ImageEnhance.Contrast(image)
            contrasted_image = contrast_enhancer.enhance(1.5)
            return contrasted_image.filter(ImageFilter.SHARPEN)

        elif filter_type == 'ember':
            grayscale = ImageOps.grayscale(image)
            return ImageOps.colorize(grayscale, black="#4D1A00", white="#FFD699")

        elif filter_type == 'airy':
            brightness_enhancer = ImageEnhance.Brightness(image)
            bright_image = brightness_enhancer.enhance(1.3)
            color_enhancer = ImageEnhance.Color(bright_image)
            return color_enhancer.enhance(0.8)

        elif filter_type == 'stormy':
            contrast_enhancer = ImageEnhance.Contrast(image)
            contrasted_image = contrast_enhancer.enhance(1.6)
            blue_grey_layer = Image.new('RGB', contrasted_image.size, '#2A3441')
            return Image.blend(contrasted_image, blue_grey_layer, alpha=0.25)

        elif filter_type == 'cinematic':
            color_enhancer = ImageEnhance.Color(image)
            desaturated_image = color_enhancer.enhance(0.5)
            contrast_enhancer = ImageEnhance.Contrast(desaturated_image)
            contrasted_image = contrast_enhancer.enhance(1.4)
            blue_layer = Image.new('RGB', contrasted_image.size, '#001122')
            return Image.blend(contrasted_image, blue_layer, alpha=0.15)

        elif filter_type == 'noir':
            grayscale_image = ImageOps.grayscale(image)
            contrast_enhancer = ImageEnhance.Contrast(grayscale_image)
            return contrast_enhancer.enhance(1.8)

        return image
    except Exception as e:
        print(f"Error applying filter {filter_type}: {e}")
        return image # Return original image on failure

# --- Webhook Handler ---
@app.route('/', methods=['POST'])
def webhook():
    update = request.get_json()
    
    # Handle button clicks for editing
    if 'callback_query' in update:
        callback_query = update['callback_query']
        data = callback_query['data']
        chat_id = callback_query['message']['chat']['id']
        
        file_id = user_photo_session.get(chat_id)
        if not file_id:
            send_telegram_message(chat_id, "Sorry, your photo session has expired. Please send the photo again.")
            return 'ok'

        send_telegram_message(chat_id, f"🎨 Applying the *{data.capitalize()}* filter...")

        original_image = get_image_from_telegram(file_id)
        if original_image:
            edited_image = apply_filter(original_image, data)
            
            output_buffer = io.BytesIO()
            edited_image.save(output_buffer, format='JPEG', quality=90)
            output_buffer.seek(0)
            
            send_processed_photo(chat_id, output_buffer.getvalue(), f"✅ Here is your *{data.capitalize()}* edited photo!")
        else:
            send_telegram_message(chat_id, "❌ Could not process the image.")
        
        user_photo_session.pop(chat_id, None)
        return 'ok'

    if 'message' in update:
        message = update['message']
        chat_id = message['chat']['id']
        
        if 'text' in message and message['text'] == '/start':
            welcome_message = "👋 Welcome to the Pro Photo Editor Bot!\n\nPlease send me a photo to get started."
            send_telegram_message(chat_id, welcome_message)
            return 'ok'

        if 'photo' in message:
            file_id = message['photo'][-1]['file_id']
            user_photo_session[chat_id] = file_id
            
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "🌈 Saturation", "callback_data": "saturate"},
                        {"text": "✨ Enhance", "callback_data": "enhance"},
                        {"text": "🌟 Vibrant", "callback_data": "vibrant"}
                    ],
                    [
                        {"text": "⚡ Dynamic", "callback_data": "dynamic"},
                        {"text": "🔥 Ember", "callback_data": "ember"},
                        {"text": "💨 Airy", "callback_data": "airy"}
                    ],
                    [
                        {"text": "⛈️ Stormy", "callback_data": "stormy"},
                        {"text": "🎬 Cinematic", "callback_data": "cinematic"},
                        {"text": "⚫ Noir (B&W)", "callback_data": "noir"}
                    ]
                ]
            }
            send_telegram_message(chat_id, "Great! Now choose a professional filter to apply:", reply_markup=keyboard)
            return 'ok'

        send_telegram_message(chat_id, "I only understand photos. Please send a photo to edit.")

    return 'ok'

@app.route('/')
def index():
    return "Photo Editor Bot is running with multiple Pro Filters!"
