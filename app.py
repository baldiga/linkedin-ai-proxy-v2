# app.py
import os
import firebase_admin
import json
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore
from openai import OpenAI
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

# --- INITIALIZATION ---

app = Flask(__name__)

# Initialize Firebase
try:
    firebase_credentials_json = os.environ.get("FIREBASE_CREDENTIALS")
    if not firebase_credentials_json:
        raise ValueError("FIREBASE_CREDENTIALS environment variable not set")
    cred = credentials.Certificate(json.loads(firebase_credentials_json))
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    users_ref = db.collection('users')
    print("Firebase initialized successfully.")
except Exception as e:
    print(f"FATAL: Error initializing Firebase: {e}")
    db = None
    users_ref = None

# Initialize OpenAI Client
try:
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")
    client = OpenAI(api_key=openai_api_key)
    print("OpenAI client initialized successfully.")
except Exception as e:
    print(f"FATAL: Error initializing OpenAI client: {e}")
    client = None

# Subscription Tiers Configuration
TIER_LIMITS = {
    'free': 5, # Added a free tier for new signups
    'tier1': 30,
    'tier2': 70,
    'tier3': 100,
    'enterprise': float('inf') # Effectively unlimited
}

# --- USER AUTHENTICATION ENDPOINTS ---

@app.route("/signup", methods=["POST"])
def signup():
    """Creates a new user account."""
    if not db:
        return jsonify({"error": "Database not configured"}), 500

    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    # Check if user already exists
    if users_ref.document(email).get().exists:
        return jsonify({"error": "User with this email already exists"}), 409

    # Hash the password for security
    password_hash = generate_password_hash(password)

    # Create new user document
    user_data = {
        'email': email,
        'password_hash': password_hash,
        'subscription_tier': 'free', # Default to free tier
        'daily_comment_count': 0,
        'last_comment_date': datetime.now().strftime('%Y-%m-%d'),
        'created_at': datetime.now()
    }
    users_ref.document(email).set(user_data)

    return jsonify({"success": True, "message": "User created successfully"}), 201

@app.route("/login", methods=["POST"])
def login():
    """Authenticates a user and provides their status."""
    if not db:
        return jsonify({"error": "Database not configured"}), 500
        
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user_doc = users_ref.document(email).get()

    if not user_doc.exists:
        return jsonify({"error": "Invalid credentials"}), 401

    user_data = user_doc.to_dict()

    if not check_password_hash(user_data.get('password_hash'), password):
        return jsonify({"error": "Invalid credentials"}), 401
    
    # NOTE: In a real production app, you would return a secure token (e.g., JWT)
    # For simplicity here, we'll just confirm success and the client will store the email.
    return jsonify({
        "success": True,
        "message": "Login successful",
        "userData": {
            "email": user_data.get('email'),
            "tier": user_data.get('subscription_tier'),
            "usage": user_data.get('daily_comment_count'),
            "limit": TIER_LIMITS.get(user_data.get('subscription_tier', 'free'))
        }
    }), 200


# --- CORE FUNCTIONALITY ENDPOINT ---

@app.route("/generate-comment", methods=["POST"])
def generate_comment():
    """Generates a comment after validating user's quota."""
    if not db or not client:
        return jsonify({"error": "A backend service is not configured"}), 500

    data = request.json
    user_id = data.get("userId") # User's email will be the ID
    post_content = data.get("postContent")
    persona = data.get("persona", "friendly and professional")
    response_language = data.get("responseLanguage", "English")
    include_emojis = data.get("includeEmojis", False)

    if not user_id or not post_content:
        return jsonify({"error": "Missing userId or postContent"}), 400

    # --- Usage Quota Logic ---
    user_doc_ref = users_ref.document(user_id)
    user_doc = user_doc_ref.get()

    if not user_doc.exists:
        return jsonify({"error": "User not found. Please log in again."}), 404

    user_data = user_doc.to_dict()
    today_str = datetime.now().strftime('%Y-%m-%d')

    # Reset daily count if it's a new day
    if user_data.get('last_comment_date') != today_str:
        user_data['daily_comment_count'] = 0
        user_data['last_comment_date'] = today_str

    # Check if user is over their limit
    tier = user_data.get('subscription_tier', 'free')
    limit = TIER_LIMITS.get(tier, 0)

    if user_data['daily_comment_count'] >= limit:
        return jsonify({"error": f"Daily limit of {limit} comments reached. Please upgrade your plan."}), 429 # 429: Too Many Requests

    # --- OpenAI Comment Generation ---
    try:
        emoji_instruction = "Include relevant emojis." if include_emojis else "Do not use emojis."
        prompt = (
            f"You are a professional assistant for generating LinkedIn comments. "
            f"The user's desired persona is '{persona}'. "
            f"The comment must be in '{response_language}'. {emoji_instruction}\n\n"
            f"Generate a thoughtful comment for the following LinkedIn post:\n\n"
            f"POST: \"{post_content}\""
        )
        
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You generate high-quality, professional LinkedIn comments based on user-defined personas and languages."},
                {"role": "user", "content": prompt}
            ]
        )
        generated_text = completion.choices[0].message.content.strip()

        # --- Update Usage Count in Firestore ---
        user_doc_ref.update({
            'daily_comment_count': firestore.Increment(1),
            'last_comment_date': today_str
        })

        # Log the generation for history (optional)
        # db.collection("generation_logs").add({ ... })

        return jsonify({"success": True, "comment": generated_text})

    except Exception as e:
        print(f"An error occurred during comment generation: {e}")
        return jsonify({"error": "Failed to generate comment due to a server error."}), 500


# --- HEALTH CHECK ---
@app.route("/")
def health_check():
    """Health check endpoint for Render."""
    return "OK"

if __name__ == "__main__":
    # Use Gunicorn for production, this is for local dev only
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

