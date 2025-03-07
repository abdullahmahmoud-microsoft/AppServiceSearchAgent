import os
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

load_dotenv()

SEARCH_SERVICE_NAME = os.environ.get("SEARCH_SERVICE_NAME")
ADMIN_KEY = os.environ.get("ADMIN_KEY")

endpoint = f"https://{SEARCH_SERVICE_NAME}.search.windows.net"
credential = AzureKeyCredential(ADMIN_KEY)
index_client = SearchIndexClient(endpoint=endpoint, credential=credential)

indexes = list(index_client.list_indexes())

for index in indexes:
    try:
        index_client.delete_index(index.name)
        print(f"Deleted index: {index.name}")
    except Exception as e:
        print(f"Failed to delete index {index.name}: {e}")
