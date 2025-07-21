import os
import requests
from flask import Flask, request
from PIL import Image, ImageOps, ImageEnhance
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

def apply_pro_filter(image):
    """Applies a professional, cinematic filter to the image."""
    try:
        # 1. Slightly desaturate the image to give it a moody feel
        color_enhancer = ImageEnhance.Color(image)
        desaturated_image = color_enhancer.enhance(0.4) # Reduce color by 60%
        
        # 2. Increase contrast to make details stand out
        contrast_enhancer = ImageEnhance.Contrast(desaturated_image)
        contrasted_image = contrast_enhancer.enhance(1.3) # Increase contrast by 30%

        # 3. Add a cool (blueish) tint to the shadows
        # To do this, we create a blue layer and blend it
        blue_layer = Image.new('RGB', contrasted_image.size, '#001122')
        final_image = Image.blend(contrasted_image, blue_layer, alpha=0.15) # Blend 15% of the blue layer
        
        return final_image
    except Exception as e:
        print(f"Error applying pro filter: {e}")
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

        if data == 'pro_filter':
            send_telegram_message(chat_id, "🎨 Applying the *Pro Filter*... This might take a moment.")

            original_image = get_image_from_telegram(file_id)
            if original_image:
                edited_image = apply_pro_filter(original_image)
                
                output_buffer = io.BytesIO()
                edited_image.save(output_buffer, format='JPEG', quality=90)
                output_buffer.seek(0)
                
                send_processed_photo(chat_id, output_buffer.getvalue(), "✅ Here is your professionally edited photo!")
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
                        {"text": "✨ Apply Pro Filter", "callback_data": "pro_filter"}
                    ]
                ]
            }
            send_telegram_message(chat_id, "Great! Now click the button below to apply the professional filter:", reply_markup=keyboard)
            return 'ok'

        send_telegram_message(chat_id, "I only understand photos. Please send a photo to edit.")

    return 'ok'

@app.route('/')
def index():
    return "Photo Editor Bot is running with Pro Filter!"
