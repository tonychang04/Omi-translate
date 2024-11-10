# app.py

from flask import Flask, request, jsonify
import boto3
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
application = app

# Get CSE ID from environment variable, with fallback
GOOGLE_CSE_ID = os.environ.get('GOOGLE_CSE_ID')
if not GOOGLE_CSE_ID:
    raise ValueError("GOOGLE_CSE_ID environment variable is not set")

def get_user_api_key(user_id):
    ssm = boto3.client('ssm')
    try:
        response = ssm.get_parameter(
            Name=f'/omi/google-search/{user_id}',
            WithDecryption=True
        )
        return json.loads(response['Parameter']['Value'])['google_api_key']
    except ssm.exceptions.ParameterNotFound:
        return None
    except Exception as e:
        print(f"Error retrieving API key: {str(e)}")
        return None

@app.route('/setup', methods=['POST'])
def setup():
    try:
        data = request.json
        user_id = request.args.get('uid')
        
        if not user_id:
            return jsonify({"error": "No user ID provided"}), 400
            
        ssm = boto3.client('ssm')
        ssm.put_parameter(
            Name=f'/omi/google-search/{user_id}',
            Value=json.dumps({
                'google_api_key': data['google_api_key'],
                'google_cse_id': GOOGLE_CSE_ID
            }),
            Type='SecureString',
            Overwrite=True
        )
        
        return jsonify({
            "status": "success",
            "is_setup_completed": True
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        user_id = request.args.get('uid')
        if not user_id:
            return jsonify({"error": "No user ID provided"}), 400
            
        api_key = get_user_api_key(user_id)
        if not api_key:
            return jsonify({"error": "User not set up"}), 404
            
        # Your Google Search logic here using credentials
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# For local development only
if __name__ == '__main__':
    app.run(debug=True)
