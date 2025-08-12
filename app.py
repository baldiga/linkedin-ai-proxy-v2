import os
import requests
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Load environment variables from a .env file (for local development)
load_dotenv()

app = Flask(__name__)

# Load Firebase credentials from a JSON string environment variable
# This is the Service Account Key you will generate and save on Render.com
firebase_credentials_json = os.environ.get("FIREBASE_CREDENTIALS")
if firebase_credentials_json:
    try:
        cred = credentials.Certificate(json.loads(firebase_credentials_json))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firebase initialized successfully.")
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        db = None
else:
    print("FIREBASE_CREDENTIALS environment variable is not set.")
    db = None

# Load API keys from environment variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_ORG_ID = os.environ.get("OPENAI_ORG_ID")

@app.route('/generate_comment', methods=['POST'])
def generate_comment():
    """
    Generates a comment using the OpenAI API based on the LinkedIn post content.
    It also updates the user's comment count in Firebase.
    """
    if not OPENAI_API_KEY:
        return jsonify({"error": "OpenAI API key not configured."}), 500
    
    data = request.json
    post_content = data.get('post_content')
    persona = data.get('persona', 'friendly_and_professional')
    response_language = data.get('response_language', 'hebrew')
    include_emojis = data.get('include_emojis', False)
    user_id = data.get('user_id')

    if not post_content:
        return jsonify({"error": "No post content provided."}), 400

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {OPENAI_API_KEY}'
    }
    if OPENAI_ORG_ID:
        headers['OpenAI-Organization'] = OPENAI_ORG_ID

    prompt = f"You are an AI assistant for a LinkedIn user. The user's persona is '{persona}'. The user wants to write a comment on a post with the following content: '{post_content}'. Write a concise, professional, and engaging comment in {response_language}. Ensure the comment is relevant and adds value to the conversation. "
    if include_emojis:
        prompt += "Include relevant emojis in the comment."

    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100,
        "temperature": 0.7
    }

    try:
        openai_response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        openai_response.raise_for_status()
        comment = openai_response.json()['choices'][0]['message']['content'].strip()
        
        # After successful generation, update the comment count in Firebase
        if db and user_id:
            try:
                user_ref = db.collection('users').document(user_id)
                user_ref.update({
                    'commentCount': firestore.Increment(1)
                })
                print(f"Comment count incremented for user: {user_id}")
            except Exception as e:
                print(f"Error updating comment count for user {user_id}: {e}")
        
        return jsonify({"comment": comment})
    
    except requests.exceptions.RequestException as e:
        print(f"Error calling OpenAI API: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def health_check():
    return "Server is running."

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
