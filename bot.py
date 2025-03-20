import logging
from botbuilder.core import ActivityHandler, TurnContext, MessageFactory
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.identity import ManagedIdentityCredential
from config import DefaultConfig

CONFIG = DefaultConfig()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MyBot(ActivityHandler):
    def __init__(self):
        # Initialize Azure Cognitive Search client
        self.search_client = self.create_search_client()

    def create_search_client(self):
        endpoint = f"https://{CONFIG.SEARCH_SERVICE_NAME}.search.windows.net"
        credential = ManagedIdentityCredential(client_id=CONFIG.USER_ASSIGNED_CLIENT_ID)
        return SearchClient(endpoint=endpoint, index_name="your-index-name", credential=credential)

    async def on_message_activity(self, turn_context: TurnContext):
        user_id = turn_context.activity.from_property.id or "unknown"
        text = (turn_context.activity.text or "").strip()
        logger.info(f"Received message from user {user_id}: {text}")

        # Process command
        if text.startswith("/search"):
            query = text[len("/search"):].strip()
            if query:
                results = self.search_documents(query)
                if results:
                    await turn_context.send_activity(MessageFactory.text(f"Search results:\n{results}"))
                else:
                    await turn_context.send_activity(MessageFactory.text("No results found."))
            else:
                await turn_context.send_activity(MessageFactory.text("Please provide a search query."))
        else:
            await turn_context.send_activity(MessageFactory.text(f"Echo: '{text}'"))

    def search_documents(self, query):
        try:
            results = self.search_client.search(search_text=query, top=5)
            response = ""
            for result in results:
                title = result.get("title", "No Title")
                content = result.get("content", "No Content")
                response += f"Title: {title}\nContent: {content}\n\n"
            return response.strip()
        except Exception as e:
            logger.error(f"Search query failed: {e}")
            return "An error occurred while searching."

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity("Hello and welcome!")