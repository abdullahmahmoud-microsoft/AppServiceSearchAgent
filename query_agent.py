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
        # Ensure caller_id is set on the credentials object.
        self.caller_id = MICROSOFT_APP_ID

    def get_access_token(self, force_refresh: bool = False) -> str:
        # Retrieve and return the token using your get_access_token() function.
        return get_access_token()

# Create BotFramework Authentication Configuration
CONFIG = {
    "MicrosoftAppId": MICROSOFT_APP_ID,
    "MicrosoftAppTenantId": MICROSOFT_APP_TENANT_ID,
    "MicrosoftAppType": MICROSOFT_APP_TYPE,
}

# Initialize CloudAdapter
adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(CONFIG))
##adapter.credentials = MSIAppCredentials()
##logger.info(f"Adapter credentials: {vars(adapter.credentials)}")

async def on_error(context: TurnContext, error: Exception):
    logger.error(f"[on_turn_error] Unhandled error: {error}")
    await context.send_activity("The bot encountered an error. Please try again later.")
adapter.on_turn_error = on_error

# Build Azure Search index list once
def get_indices():
    endpoint = f"https://{SEARCH_SERVICE_NAME}.search.windows.net"
    credential = AzureKeyCredential(ADMIN_KEY)
    client = SearchIndexClient(endpoint, credential)
    return [idx.name for idx in client.list_indexes()]

INDICES = get_indices()
session_history = {}

def query_search_indices(query):
    endpoint = f"https://{SEARCH_SERVICE_NAME}.search.windows.net"
    credential = AzureKeyCredential(ADMIN_KEY)
    results = []
    for index in INDICES:
        client = SearchClient(endpoint, index, credential)
        hits = client.search(search_text=query, top=5, semantic_configuration_name="default", search_fields=["title", "content"])
        for r in hits:
            title = r.get("title", "No Title")
            content = r.get("content", "")
            if content:
                results.append(f"[{index}] {title}: {content}")
    return results

def generate_response(messages):
    headers = {"Content-Type": "application/json", "api-key": OPENAI_API_KEY}
    payload = {"model": DEPLOYMENT_NAME, "messages": messages, "max_tokens": 1000}
    resp = requests.post(OPENAI_ENDPOINT, headers=headers, json=payload).json()
    return resp.get("choices", [{}])[0].get("message", {}).get("content", "")

from create_index import generate_qa_pairs, create_or_replace_index, upload_documents

def store_conversation(user_id, history):
    convo = "\n".join(f"{role.capitalize()}: {msg}" for role, msg in history)
    qa_pairs = generate_qa_pairs(convo, f"conversation-{user_id}")
    docs = []
    for i, qa in enumerate(qa_pairs):
        q, a = qa.get("question", "").strip(), qa.get("answer", "").strip()
        if q and a:
            docs.append({
                "id": f"{user_id}-{i}",
                "doc_type": "qa",
                "page_title": f"Conversation {user_id}",
                "title": q,
                "content": f"Q: {q}\nA: {a}",
                "file_name": f"conversation-{user_id}",
                "upload_date": time.strftime("%Y-%m-%dT%H:%M:%SZ")
            })
    index_name = f"conversation-{user_id}".lower()
    create_or_replace_index(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name)
    upload_documents(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name, docs)
    return bool(docs)

# Flask + Bot Framework setup
app = Flask(__name__)

async def on_turn(context: TurnContext):
    activity_type = context.activity.type
    if activity_type == "conversationUpdate":
        # Optionally, send a welcome message or simply ignore the event
        logger.info("Received conversationUpdate event")
        await context.send_activity("Welcome to the bot!")
        return

    # Continue with normal processing for message activities
    user_id = context.activity.from_property.id or "unknown"
    text = (context.activity.text or "").strip()
    logger.info(f"Received message from user {user_id}: {text}")
    
    # Your existing logic...
    history = session_history.setdefault(user_id, [])
    history.append(("user", text))
    messages = [{"role": r, "content": c} for r, c in history]
    
    reply = generate_response(messages)
    history.append(("assistant", reply))
    hits = query_search_indices(text)
    if hits:
        reply += "\n\nAdditional context:\n" + "\n".join(hits)
    
    logger.info(f"Replying to user {user_id}: {reply}")
    await context.send_activity(MessageFactory.text(reply))

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
    # Show all activity parameters
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
