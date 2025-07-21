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

def apply_artistic_filter(image):
    """Applies a custom artistic filter similar to the user's example."""
    try:
        # 1. Convert to grayscale to desaturate
        grayscale_image = ImageOps.grayscale(image)
        
        # 2. Re-colorize with a cool tone (mapping black to dark blue, white to light gray)
        colorized_image = ImageOps.colorize(grayscale_image, black="#222B3D", white="#DFE2E5")
        
        # 3. Increase contrast to make details pop
        contrast_enhancer = ImageEnhance.Contrast(colorized_image)
        final_image = contrast_enhancer.enhance(1.4)
        
        return final_image
    except Exception as e:
        print(f"Error applying artistic filter: {e}")
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

        if data == 'artistic':
            send_telegram_message(chat_id, "🎨 Applying the *Artistic* filter...")

            original_image = get_image_from_telegram(file_id)
            if original_image:
                edited_image = apply_artistic_filter(original_image)
                
                output_buffer = io.BytesIO()
                edited_image.save(output_buffer, format='JPEG')
                output_buffer.seek(0)
                
                send_processed_photo(chat_id, output_buffer.getvalue(), "✅ Here is your artistically edited photo!")
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
            user_photo_session[chat_id] = file_id
            
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✨ Apply Artistic Filter", "callback_data": "artistic"}
                    ]
                ]
            }
            send_telegram_message(chat_id, "Great! Now click the button below to apply the special filter:", reply_markup=keyboard)
            return 'ok'

        # Handle other messages
        send_telegram_message(chat_id, "I only understand photos. Please send a photo to edit.")

    return 'ok'

@app.route('/')
def index():
    return "Photo Editor Bot is running with Artistic Filter!"
