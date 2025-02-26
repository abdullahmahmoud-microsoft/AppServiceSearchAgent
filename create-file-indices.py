import os
import re
import fitz 
from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex, SearchField, SearchFieldDataType
from dotenv import load_dotenv

load_dotenv()

BLOB_CONNECTION_STRING = os.environ.get("BLOB_CONNECTION_STRING")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME")
SEARCH_SERVICE_NAME = os.environ.get("SEARCH_SERVICE_NAME")
ADMIN_KEY = os.environ.get("ADMIN_KEY")

blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)

def generate_valid_id(blob_name, chunk_index):
    blob_name = blob_name.replace('.pdf', '').replace('.md', '').lower()
    # Replace invalid characters with dashes
    index_name = re.sub(r'[^a-z0-9-]', '-', blob_name)
    # Remove leading and trailing dashes
    index_name = index_name.strip('-')
    # Ensure the index name is not longer than 128 characters
    if len(index_name) > 128:
        index_name = index_name[:128]
    return f"{index_name}-{chunk_index}"

def split_text(text, chunk_size=3000):
    """Splits text into chunks of specified size."""
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def extract_text_from_pdf(file_path):
    document = fitz.open(file_path)
    text = " ".join([page.get_text() for page in document])
    return text

def extract_text_from_md(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

# Function to create or replace an index in Azure Cognitive Search
def create_or_replace_index(service_name, admin_key, index_name):
    endpoint = f"https://{service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)

    fields = [
        SearchField(name="id", type=SearchFieldDataType.String, key=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="file_name", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="upload_date", type=SearchFieldDataType.DateTimeOffset, filterable=True)
    ]

    index = SearchIndex(name=index_name, fields=fields)

    # Delete existing index if it exists
    try:
        index_client.delete_index(index_name)
        print(f"Deleted existing index {index_name}")
    except Exception:
        print(f"No existing index {index_name}, creating new one.")

    # Create the index
    index_client.create_index(index)
    print(f"Created index {index_name}")

# Function to upload documents to an index
def upload_documents(service_name, admin_key, index_name, documents):
    endpoint = f"https://{service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)

    results = search_client.upload_documents(documents=documents)
    print(f"Uploaded {len(documents)} documents to index {index_name}")
    return results

# Main script
def main():
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)
    print(f"Retrieving files from container {CONTAINER_NAME}")

    tmp_dir = os.path.join(os.getcwd(), "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    for blob in container_client.list_blobs():
        if blob.name.endswith(".pdf") or blob.name.endswith(".md"):
            blob_client = container_client.get_blob_client(blob.name)
            download_file_path = os.path.join(tmp_dir, blob.name)

            with open(download_file_path, "wb") as download_file:
                download_file.write(blob_client.download_blob().readall())

            # Extract text
            if blob.name.endswith(".pdf"):
                text = extract_text_from_pdf(download_file_path)
            else:
                text = extract_text_from_md(download_file_path)

            # Split text into smaller chunks
            text_chunks = split_text(text)

            # Generate a valid index name
            index_name = generate_valid_id(blob.name, 0)

            # Create or replace index
            create_or_replace_index(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name)

            # Prepare documents for upload
            documents = [
                {"id": generate_valid_id(blob.name, i), "content": chunk, "file_name": blob.name, "upload_date": blob.creation_time.isoformat()}
                for i, chunk in enumerate(text_chunks)
            ]

            # Upload documents to Azure Cognitive Search
            upload_documents(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name, documents)

            # Remove the downloaded file
            os.remove(download_file_path)

if __name__ == "__main__":
    main()
