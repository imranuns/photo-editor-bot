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
# To temporarily store the file_id of the photo being edited
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
    if filter_type == 'grayscale':
        return ImageOps.grayscale(image)
    elif filter_type == 'sepia':
        # Sepia is grayscale with a color tint
        grayscale = ImageOps.grayscale(image)
        sepia_image = ImageOps.colorize(grayscale, black="#704214", white="#EAE0C8")
        return sepia_image
    elif filter_type == 'sharpen':
        return image.filter(ImageFilter.SHARPEN)
    elif filter_type == 'enhance':
        # Auto-enhance brightness, contrast, and color
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.2) # Increase contrast
        enhancer = ImageEnhance.Color(image)
        image = enhancer.enhance(1.2) # Increase color saturation
        return image
    return image

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

        send_telegram_message(chat_id, f"🎨 Applying *{data}* filter...")

        original_image = get_image_from_telegram(file_id)
        if original_image:
            edited_image = apply_filter(original_image, data)
            
            output_buffer = io.BytesIO()
            edited_image.save(output_buffer, format='JPEG')
            output_buffer.seek(0)
            
            send_processed_photo(chat_id, output_buffer.getvalue(), f"✅ Here is your *{data}* edited photo!")
        else:
            send_telegram_message(chat_id, "❌ Could not process the image.")
        
        # Clear the session
        user_photo_session.pop(chat_id, None)
        return 'ok'

    if 'message' in update:
        message = update['message']
        chat_id = message['chat']['id']
        
        # Handle /start command
        if 'text' in message and message['text'] == '/start':
            welcome_message = "👋 Welcome to the Photo Editor Bot!\n\nPlease send me a photo to get started."
            send_telegram_message(chat_id, welcome_message)
            return 'ok'

        # Handle incoming photo
        if 'photo' in message:
            file_id = message['photo'][-1]['file_id']
            # Store the file_id for the user to edit
            user_photo_session[chat_id] = file_id
            
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✨ Auto-Enhance", "callback_data": "enhance"},
                        {"text": "🎨 Grayscale", "callback_data": "grayscale"}
                    ],
                    [
                        {"text": "🎞️ Sepia", "callback_data": "sepia"},
                        {"text": "🔪 Sharpen", "callback_data": "sharpen"}
                    ]
                ]
            }
            send_telegram_message(chat_id, "Great! Now choose an effect to apply to your photo:", reply_markup=keyboard)
            return 'ok'

        # Handle other messages
        send_telegram_message(chat_id, "I only understand photos. Please send a photo to edit.")

    return 'ok'

@app.route('/')
def index():
    return "Photo Editor Bot is running!"
