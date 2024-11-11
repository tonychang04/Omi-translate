import boto3
import json
import os
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.event_handler.api_gateway import Response

# Initialize logger and API resolver
logger = Logger()
app = APIGatewayRestResolver()

# Get environment variables
GOOGLE_CSE_ID = os.environ.get('GOOGLE_CSE_ID')
AWS_DEFAULT_REGION = 'us-east-1'

if not GOOGLE_CSE_ID:
    logger.error("GOOGLE_CSE_ID environment variable is not set")
    raise ValueError("GOOGLE_CSE_ID environment variable is not set")

def get_user_api_key(user_id: str) -> str:
    ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)
    try:
        response = ssm.get_parameter(
            Name=f'/omi/google-search/{user_id}',
            WithDecryption=True
        )
        return json.loads(response['Parameter']['Value'])['google_api_key']
    except ssm.exceptions.ParameterNotFound:
        return None
    except Exception as e:
        logger.error(f"Error retrieving API key: {str(e)}")
        return None

@app.post("/setup")
def setup():
    try:
        # Get request data
        body = app.current_event.json_body
        user_id = app.current_event.get_query_string_value(name="uid")
        
        if not user_id:
            logger.error("No user ID provided")
            return {"statusCode": 400, "body": {"error": "No user ID provided"}}
            
        if not body or 'google_api_key' not in body:
            logger.error("Invalid request data: missing google_api_key")
            return {"statusCode": 400, "body": {"error": "Invalid request data"}}

        ssm = boto3.client('ssm', region_name=AWS_DEFAULT_REGION)
        
        param_value = json.dumps({
            'google_api_key': body['google_api_key']
        })
        param_name = f'/omi/google-search/{user_id}'
                
        ssm.put_parameter(
            Name=param_name,
            Value=param_value,
            Type='SecureString',
            Overwrite=True
        )
        
        logger.info(f"Parameter saved successfully for user {user_id}")
        
        return {
            "status": "success",
            "message": "Setup completed successfully",
            "is_setup_completed": True
        }
        
    except Exception as e:
        logger.error(f"Error in setup: {str(e)}")
        logger.exception(e)
        return {"statusCode": 500, "body": {"error": str(e)}}

@app.post("/webhook")
def webhook():
    try:
        user_id = app.current_event.get_query_string_value(name="uid")
        if not user_id:
            return {"statusCode": 400, "body": {"error": "No user ID provided"}}
            
        api_key = get_user_api_key(user_id)
        if not api_key:
            return {"statusCode": 404, "body": {"error": "User not set up"}}
            
        # Your Google Search logic here
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error in webhook: {str(e)}")
        return {"statusCode": 500, "body": {"error": str(e)}}

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
