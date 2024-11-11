# app.py

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

import boto3
import json
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger()

app = Flask(__name__)
app.debug = True  # Enable Flask debug mode

# Enable CORS globally with all defaults
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Type", "Authorization"]
    }
})


@app.after_request
def add_cors_headers(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
    return response

# Get CSE ID from environment variable
GOOGLE_CSE_ID = os.environ.get('GOOGLE_CSE_ID')
if not GOOGLE_CSE_ID:
    logger.error("GOOGLE_CSE_ID environment variable is not set")
    raise ValueError("GOOGLE_CSE_ID environment variable is not set")

# Get AWS region from environment variable
AWS_DEFAULT_REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

def get_user_api_key(user_id):
    ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)  # Updated region variable name
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

@app.route('/')
def setup_page():
    return render_template('setup.html')

@app.route('/setup', methods=['POST'])
def setup():

    try:
        data = request.json
        user_id = request.args.get('uid')
        
        if not user_id:
            logger.error("No user ID provided")
            return jsonify({"error": "No user ID provided"}), 400
            
        ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)  # Updated region variable name
        
        # Create the parameter value
        param_value = json.dumps({
            'google_api_key': data['google_api_key'],
        })
        param_name = f'/omi/google-search/{user_id}'
                
        try:
            ssm.put_parameter(
                Name=param_name,
                Value=param_value,
                Type='SecureString',
                Overwrite=True
            )
            logger.info("Parameter saved successfully")
        except Exception as ssm_error:
            logger.error(f"SSM Error: {str(ssm_error)}")
            raise ssm_error
        
        return jsonify({
            "status": "success",
            "is_setup_completed": True
        }), 200
        
    except Exception as e:
        logger.error(f"Error in setup: {str(e)}")
        logger.error(f"Error type: {type(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
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
