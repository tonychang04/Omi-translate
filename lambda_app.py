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

def get_user_settings(user_id: str) -> tuple:
    ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)
    try:
        response = ssm.get_parameter(
            Name=f'/omi/realtimetranslate/{user_id}',
            WithDecryption=True
        )
        settings = json.loads(response['Parameter']['Value'])
        return settings.get('openai_api_key'), settings.get('target_language')
    except ssm.exceptions.ParameterNotFound:
        return None, None
    except Exception as e:
        logger.error(f"Error retrieving settings: {str(e)}")
        return None, None

@app.post("/setup")
def setup():
    try:
        # Get request data
        body = app.current_event.json_body
        user_id = app.current_event.get_query_string_value(name="uid")
        
        if not user_id:
            logger.error("No user ID provided")
            return Response(
                status_code=400,
                content_type="application/json",
                body=json.dumps({"error": "No user ID provided"})
            )
            
        if not body or 'openai_api_key' not in body or 'target_language' not in body:
            logger.error("Invalid request data: missing openai_api_key or target_language")
            return Response(
                status_code=400,
                content_type="application/json",
                body=json.dumps({"error": "Invalid request data: Please provide both API key and target language"})
            )

        # Validate the OpenAI API key
        try:
            test_client = openai.OpenAI(api_key=body['openai_api_key'])
            # Make a small test request
            test_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5
            )
            is_valid = True
            error_message = None
        except Exception as e:
            is_valid = False
            error_message = f"Invalid OpenAI API key: {str(e)}"
            logger.error(error_message)
        
        if not is_valid:
            return Response(
                status_code=400,
                content_type="application/json",
                body=json.dumps({"error": error_message})
            )

        # Store both API key and target language
        ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)
        param_value = json.dumps({
            'openai_api_key': body['openai_api_key'],
            'target_language': body['target_language']
        })
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
            # Try to get the parameter
            response = ssm.get_parameter(
                Name=f'/omi/realtimetranslate/{user_id}',
                WithDecryption=True
            )
            
            # If we get here, the parameter exists
            return Response(
                status_code=200,
                content_type="application/json",
                body=json.dumps({
                    "is_setup_completed": True,
                })
            )
        except ssm.exceptions.ParameterNotFound:
            return Response(
                status_code=200,
                content_type="application/json",
                body=json.dumps({
                    "is_setup_completed": False,
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
        data = app.current_event.json_body
        user_id = app.current_event.get_query_string_value(name="uid")
        segments = data.get('transcript_segments', [])
        
        translated_segments = []
        # Process each segment
        for segment in segments:
            text = segment.get('text', '').strip()
            if not text:
                continue
                
            logger.info(f"[SEGMENT] Processing text: '{text}'")
            
            # Get translation settings
            api_key, target_language = get_user_settings(user_id)
            if not api_key or not target_language:
                raise ValueError("Translation settings not found")
            
            # Translate current segment
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"Translate to {target_language}"},
                    {"role": "user", "content": text}
                ],
                temperature=0.3
            )
            
            translated_text = response.choices[0].message.content.strip()
            speaker = segment.get('speaker', 'UNKNOWN')
            formatted_message = f"{speaker}: {translated_text}"
            logger.info(f"[TRANSLATE] Translation result: '{formatted_message}'")
            translated_segments.append(formatted_message)
        
        # Return all translated segments
        return Response(
            status_code=200,
            content_type="application/json",
            body=json.dumps({
                "message": " ".join(translated_segments)
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