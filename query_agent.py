import logging
import os
import re
import time
import asyncio
import requests
from flask import Flask, request, Response
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.identity import ManagedIdentityCredential
from botbuilder.core import TurnContext, MessageFactory
from botbuilder.schema import Activity
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botframework.connector.auth.microsoft_app_credentials import MicrosoftAppCredentials

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load settings
load_dotenv()
SEARCH_SERVICE_NAME = os.getenv("SEARCH_SERVICE_NAME")
ADMIN_KEY = os.getenv("ADMIN_KEY")
OPENAI_ENDPOINT = os.getenv("OPENAI_ENDPOINT") 
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEPLOYMENT_NAME = os.getenv("DEPLOYMENT_NAME")
USER_ASSIGNED_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
MICROSOFT_APP_ID = os.getenv("MicrosoftAppId")
MICROSOFT_APP_TENANT_ID = os.getenv("MicrosoftAppTenantId")
MICROSOFT_APP_TYPE = os.getenv("MicrosoftAppType")

logger.info(f"SEARCH_SERVICE_NAME: {SEARCH_SERVICE_NAME}")
logger.info(f"ADMIN_KEY: {ADMIN_KEY}")
logger.info(f"OPENAI_ENDPOINT: {OPENAI_ENDPOINT}")
logger.info(f"OPENAI_API_KEY: {OPENAI_API_KEY}")
logger.info(f"DEPLOYMENT_NAME: {DEPLOYMENT_NAME}")
logger.info(f"USER_ASSIGNED_CLIENT_ID: {USER_ASSIGNED_CLIENT_ID}")
logger.info(f"MicrosoftAppId: {MICROSOFT_APP_ID}")

# Get Managed Identity Credential
credential = ManagedIdentityCredential(client_id=USER_ASSIGNED_CLIENT_ID)

# Function to get an access token
def get_access_token():
    try:
        logger.info("Fetching MSI access token for Bot Framework API...")
        token = credential.get_token("https://graph.microsoft.com/.default")
        logger.info("Successfully retrieved access token.")
        return token.token
    except Exception as e:
        logger.error(f"Failed to retrieve access token: {str(e)}")
        return None  # Return None if MSI authentication fails

class MSIAppCredentials(MicrosoftAppCredentials):
    def __init__(self):
        super().__init__(MICROSOFT_APP_ID, None)
        self.caller_id = MICROSOFT_APP_ID

    def get_access_token(self, force_refresh: bool = False) -> str:
        return get_access_token()

# Create BotFramework Authentication Configuration
CONFIG = {
    "MicrosoftAppId": MICROSOFT_APP_ID,
    "MicrosoftAppTenantId": MICROSOFT_APP_TENANT_ID,
    "MicrosoftAppType": MICROSOFT_APP_TYPE,
}

adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(CONFIG))

# Explicitly instantiate MSIAppCredentials
msi_credentials = MSIAppCredentials()
adapter.credentials = msi_credentials

logger.info(f"Adapter credentials type: {type(adapter.credentials)}")
logger.info(f"Adapter credentials attributes: {dir(adapter.credentials)}")
logger.info(f"Adapter credentials: {vars(msi_credentials)}")

async def on_error(context: TurnContext, error: Exception):
    logger.error(f"[on_turn_error] Unhandled error: {error}")
    await context.send_activity("The bot encountered an error. Please try again later.")
adapter.on_turn_error = on_error

# Flask + Bot Framework setup
app = Flask(__name__)

async def on_turn(context: TurnContext):
    activity_type = context.activity.type
    if activity_type == "conversationUpdate":
        logger.info("Received conversationUpdate event")
        await context.send_activity("Welcome to the bot!")
        return

    user_id = context.activity.from_property.id or "unknown"
    text = (context.activity.text or "").strip()
    logger.info(f"Received message from user {user_id}: {text}")
    
    await context.send_activity(MessageFactory.text(f"Echo: {text}"))

@app.route("/api/messages", methods=["POST"])
def messages():
    logger.info("Received request at /api/messages")

    if not request.is_json:
        logger.error("Invalid request format")
        return Response("Invalid request format", status=400)

    body = request.json
    auth_header = request.headers.get("Authorization", "")

    logger.info(f"Processing activity: {body}")
    
    activity = Activity().deserialize(body)
    logger.info(f"Activity post deserialize: {vars(activity)}")
    logger.info(f"Auth header: {auth_header}")
    
    try:
        asyncio.run(adapter.process_activity(activity, auth_header, on_turn))
        logger.info("Successfully processed activity")
    except Exception as e:
        logger.error(f"Error processing activity: {e}")

    return Response(status=201)

@app.route("/")
def alive():
    logger.info("Health check: App is alive")
    return "Antares Genie is ALLIIVEEEEEE."

if __name__ == "__main__":
    logger.info("Starting Antares Genie bot server...")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3978)))