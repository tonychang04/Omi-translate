import boto3
import json
import os
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.event_handler.api_gateway import Response
from typing import Tuple
import requests
import openai
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import threading
import time
from collections import defaultdict

# Initialize logger and API resolver
logger = Logger()
app = APIGatewayRestResolver()


# Add OpenAI API key to environment variables
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY environment variable is not set")
    raise ValueError("OPENAI_API_KEY environment variable is not set")

openai.api_key = OPENAI_API_KEY
AWS_DEFAULT_REGION = "us-east-1" 

# Feature flags at the top of the file
FEATURES = {
    'USE_GLOBAL_API_KEY': True,  # True = use single API key for all users
}

def get_user_settings(user_id: str) -> tuple:
    """Get user's settings based on mode"""
    ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)
    try:
        response = ssm.get_parameter(
            Name=f'/omi/realtimetranslate/{user_id}',
            WithDecryption=True
        )
        settings = json.loads(response['Parameter']['Value'])
        
        if FEATURES['USE_GLOBAL_API_KEY']:
            return OPENAI_API_KEY, settings.get('target_language')
        else:
            return settings.get('openai_api_key'), settings.get('target_language')
            
    except ssm.exceptions.ParameterNotFound:
        return None, None
    except Exception as e:
        logger.error(f"Error retrieving settings: {str(e)}")
        return None, None

# Constants for translation timing
MIN_WORDS = 5  # minimum words before considering translation

TRIGGER_PHRASES = ["translate", "translate to"]
PARTIAL_FIRST = ["trans", "translate"]
PARTIAL_SECOND = ["late", "to"]

class TranslationBuffer:
    def __init__(self):
        self.buffers = {}
        self.lock = threading.Lock()
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()

    def get_buffer(self, session_id):
        current_time = time.time()
        
        # Cleanup old sessions periodically
        if current_time - self.last_cleanup > self.cleanup_interval:
            self.cleanup_old_sessions()
        
        with self.lock:
            if session_id not in self.buffers:
                self.buffers[session_id] = {
                    'messages': [],
                    'trigger_detected': False,
                    'trigger_time': 0,
                    'collected_text': [],
                    'response_sent': False,
                    'partial_trigger': False,
                    'partial_trigger_time': 0,
                    'last_activity': current_time
                }
            else:
                self.buffers[session_id]['last_activity'] = current_time
                
        return self.buffers[session_id]

    def cleanup_old_sessions(self):
        current_time = time.time()
        with self.lock:
            expired_sessions = [
                session_id for session_id, data in self.buffers.items()
                if current_time - data['last_activity'] > 300  # Remove sessions older than 1 hour
            ]
            for session_id in expired_sessions:
                del self.buffers[session_id]
            self.last_cleanup = current_time

# Initialize the translation buffer instance
translation_buffer = TranslationBuffer()

# Add cooldown tracking
translation_cooldowns = defaultdict(float)
TRANSLATION_COOLDOWN = 5  

@app.post("/setup")
def setup():
    try:
        body = app.current_event.json_body
        user_id = app.current_event.get_query_string_value(name="uid")
        
        if not user_id:
            logger.error("No user ID provided")
            return Response(
                status_code=400,
                content_type="application/json",
                body=json.dumps({"error": "No user ID provided"})
            )
        
        # Validate based on mode
        if FEATURES['USE_GLOBAL_API_KEY']:
            # Only require target_language
            if not body or 'target_language' not in body:
                return Response(
                    status_code=400,
                    content_type="application/json",
                    body=json.dumps({"error": "Please enter a target language"})
                )
            param_value = json.dumps({
                'target_language': body['target_language']
            })
        else:
            # Require both API key and language
            if not body or 'target_language' not in body or 'openai_api_key' not in body:
                return Response(
                    status_code=400,
                    content_type="application/json",
                    body=json.dumps({"error": "Please provide both API key and target language"})
                )
            param_value = json.dumps({
                'target_language': body['target_language'],
                'openai_api_key': body['openai_api_key']
            })

        # Store settings
        ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)
        param_name = f'/omi/realtimetranslate/{user_id}'
        
        ssm.put_parameter(
            Name=param_name,
            Value=param_value,
            Type='SecureString',
            Overwrite=True
        )
        
        logger.info(f"Parameter saved successfully for user {user_id}")
        
        return Response(
            status_code=200,
            content_type="application/json",
            body=json.dumps({
                "status": "success",
                "message": "Setup completed successfully",
                "is_setup_completed": True,
                "target_language": body['target_language']
            })
        )
        
    except Exception as e:
        logger.error(f"Error in setup: {str(e)}")
        logger.exception(e)
        return Response(
            status_code=500,
            content_type="application/json",
            body=json.dumps({
                "error": f"Server error: {str(e)}"
            })
        )
    
@app.get("/setup_completed")
def setup_completed():
    try:
        user_id = app.current_event.get_query_string_value(name="uid")
        if not user_id:
            return Response(
                status_code=400,
                content_type="application/json",
                body=json.dumps({"error": "No user ID provided"})
            )

        ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)
        
        try:
            # Get the parameter
            response = ssm.get_parameter(
                Name=f'/omi/realtimetranslate/{user_id}',
                WithDecryption=True
            )
            
            # Parse stored settings
            settings = json.loads(response['Parameter']['Value'])
            
            # Check required fields based on mode
            if FEATURES['USE_GLOBAL_API_KEY']:
                # Only need target language
                is_setup_complete = bool(settings.get('target_language'))
            else:
                # Need both API key and target language
                is_setup_complete = bool(
                    settings.get('target_language') and 
                    settings.get('openai_api_key')
                )
            
            return Response(
                status_code=200,
                content_type="application/json",
                body=json.dumps({
                    "is_setup_completed": is_setup_complete,
                })
            )
            
        except ssm.exceptions.ParameterNotFound:
            return Response(
                status_code=200,
                content_type="application/json",
                body=json.dumps({
                    "is_setup_completed": False,
                    "reason": "No settings found"
                })
            )
            
    except Exception as e:
        logger.error(f"Error checking setup status: {str(e)}")
        return Response(
            status_code=500,
            content_type="application/json",
            body=json.dumps({
                "error": f"Error checking setup status: {str(e)}"
            })
        )

@app.post("/translate")
def translate():
    try:
        # Get the request data
        data = app.current_event.json_body
        user_id = app.current_event.get_query_string_value(name="uid")
        session_id = data.get('session_id',user_id)
        segments = data.get('segments', [])
        
        if not user_id or not session_id:
            raise ValueError("Both uid and session_id are required")
        
        current_time = time.time()
        buffer_data = translation_buffer.get_buffer(session_id)
        
        for segment in segments:
            if not segment.get('text'):
                continue
            
            #logger.info(f"Segment: {segment}")
            text = segment.get('text', '').strip()
            
            # Check for complete trigger phrases first
            if any(trigger in text.lower() for trigger in TRIGGER_PHRASES) and not buffer_data['trigger_detected']:
                logger.info(f"[TRIGGER] Session {session_id}, Found trigger phrase in: '{text}'")
                buffer_data['trigger_detected'] = True
                buffer_data['trigger_time'] = current_time
                buffer_data['collected_text'] = []
                buffer_data['response_sent'] = False
                buffer_data['partial_trigger'] = False
                translation_cooldowns[session_id] = current_time
                
                # Get text after trigger and start collecting
                for trigger in TRIGGER_PHRASES:
                    if trigger in text.lower():
                        parts = text.lower().split(trigger, 1)
                        if len(parts) > 1:
                            after_trigger = parts[1].strip()
                            if after_trigger:
                                buffer_data['collected_text'].append(after_trigger)
                                logger.info(f"[COLLECT] Initial text after trigger: '{after_trigger}'")
                continue
            
            # If trigger was detected, collect text until pause
            if buffer_data['trigger_detected'] and not buffer_data['response_sent']:
                time_since_trigger = current_time - buffer_data['trigger_time']
                logger.info(f"[COLLECT] Time since trigger: {time_since_trigger:.2f}s")
                # Add current text to collection
                buffer_data['collected_text'].append(text)
                
                # Get complete collected text first
                collected_text = " ".join(buffer_data['collected_text'])
                logger.info(f"[COLLECT] Current text: '{collected_text}'")
                
                # Then check if we should translate
                should_translate = (
                    (any(collected_text.rstrip().endswith(end) for end in ['.', '!', '?']) and
                    len(collected_text.split()) >= MIN_WORDS) or
                    time_since_trigger > 4
                )
                
                if should_translate:
                    # Get translation settings using user_id
                    api_key, target_language = get_user_settings(user_id)
                    if not api_key or not target_language:
                        raise ValueError("Translation settings not found")
                    
                    # Translate collected text
                    client = openai.OpenAI(api_key=api_key)
                    logger.info(f"[TRANSLATE] Translating text: '{collected_text}'")
                    
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": f"Translate to {target_language}"},
                            {"role": "user", "content": collected_text}
                        ],
                        temperature=0.3
                    )
                    
                    translated_text = response.choices[0].message.content.strip()
                    speaker = segment.get('speaker', 'UNKNOWN')
                    formatted_message = f"{speaker}: {translated_text}"
                    logger.info(f"[TRANSLATE] Translation result: '{formatted_message}'")
                    
                    # Reset buffer
                    buffer_data['trigger_detected'] = False
                    buffer_data['collected_text'] = []
                    buffer_data['response_sent'] = True
                    
                    return Response(
                        status_code=200,
                        content_type="application/json",
                        body=json.dumps({
                            "message": formatted_message
                        })
                    )
        
        # Return success if no translation needed
        return Response(
            status_code=200,
            content_type="application/json",
            body=json.dumps({
                "status": "success"
            })
        )
            
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        return Response(
            status_code=500,
            body=json.dumps({"error": str(e)})
        )

@logger.inject_lambda_context
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    """Main Lambda handler"""
    # Add debug logging
    #logger.info(f"Received event: {json.dumps(event)}")
    
    # Check if this is a CloudWatch Events warm-up event
    if event.get('source') == 'aws.events' and 'detail-type' in event and event['detail-type'] == 'Scheduled Event':
        logger.info("WarmUp - Lambda is warm!")
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "WarmUp event handled successfully"})
        }
    
    # Check if this is a Zappa warm-up event
    if event.get('source') == 'serverless-plugin-warmup':
        logger.info("WarmUp - Lambda is warm!")
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "WarmUp event handled successfully"})
        }
    
    try:
        # Handle API Gateway events
        if 'httpMethod' in event:
            return app.resolve(event, context)
        else:
            logger.error("Unhandled event type")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Unsupported event type"})
            }
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

# Add this function to read the HTML file
def read_html_template(template_name: str) -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(current_dir, 'templates', template_name)
    try:
        with open(template_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        logger.error(f"Error reading template {template_name}: {str(e)}")
        return "<h1>Error loading page</h1>"

@app.get("/")
def setup_page():
    html_content = read_html_template('setup.html')
    return Response(
        status_code=200,
        content_type="text/html",
        body=html_content
    )
    
    
