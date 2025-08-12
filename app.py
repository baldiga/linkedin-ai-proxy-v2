import os
import firebase_admin
import json
from flask import Flask, request, jsonify
from firebase_admin import credentials, firestore
from openai import OpenAI # Updated to use OpenAI library
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)

# Fetch Firebase credentials from environment variable
firebase_credentials_json = os.environ.get("FIREBASE_CREDENTIALS")
if not firebase_credentials_json:
    raise ValueError("FIREBASE_CREDENTIALS environment variable not set")

try:
    # Initialize Firebase Admin SDK
    cred = credentials.Certificate(json.loads(firebase_credentials_json))
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"Error initializing Firebase: {e}")
    # Handle the error gracefully, maybe a different fallback or terminate
    db = None

# Initialize OpenAI client with API key from environment variable
openai_api_key = os.environ.get("OPENAI_API_KEY") # Updated environment variable name
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set")

client = OpenAI(api_key=openai_api_key)

# The /generate route handles incoming requests for content generation
@app.route("/generate", methods=["POST"])
def generate():
    if request.method == "POST":
        data = request.json
        prompt = data.get("prompt")
        user_id = data.get("userId")
        
        # Guard clause to ensure prompt and user ID are present
        if not prompt or not user_id:
            return jsonify({"error": "Missing prompt or userId"}), 400

        try:
            # Use OpenAI's ChatCompletion endpoint
            completion = client.chat.completions.create(
                model="gpt-3.5-turbo", # You can specify a different model if needed
                messages=[
                    {"role": "system", "content": "You are a professional assistant for generating LinkedIn content."},
                    {"role": "user", "content": prompt}
                ]
            )

            # Extract the response text
            generated_text = completion.choices[0].message.content

            # Save the prompt and response to Firestore
            if db:
                doc_ref = db.collection("artifacts").document("linin-f5c39").collection("users").document(user_id).collection("generated_content").document()
                doc_ref.set({
                    "prompt": prompt,
                    "response": generated_text,
                    "timestamp": datetime.now()
                })

            return jsonify({"response": generated_text})
        except Exception as e:
            # Handle potential API errors and log them
            print(f"An error occurred: {e}")
            return jsonify({"error": str(e)}), 500
    
    return jsonify({"error": "Method not allowed"}), 405

# Health check endpoint
@app.route("/")
def health_check():
    return "OK"

if __name__ == "__main__":
    app.run(debug=True)
