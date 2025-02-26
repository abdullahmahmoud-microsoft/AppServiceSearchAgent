import os
import re
import time
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex, SearchField, SearchFieldDataType
from dotenv import load_dotenv

load_dotenv()

SEARCH_SERVICE_NAME = os.environ.get("SEARCH_SERVICE_NAME")
ADMIN_KEY = os.environ.get("ADMIN_KEY")

URLS_TO_INDEX = [
    "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/troubleshoot_deployment"
    # Add more URLs as needed.
]

def generate_valid_id(url, chunk_index):
    # Remove URL scheme, replace underscores with dashes, and lowercase.
    url = url.replace("https://", "").replace("http://", "").replace("_", "-").lower()
    index_name = re.sub(r'[^a-z0-9-]', '-', url)
    # Collapse multiple dashes into one.
    index_name = re.sub(r'-+', '-', index_name)
    # Strip any leading or trailing dashes.
    index_name = index_name.strip('-')
    # Indexing has 128 char limit, so truncate if necessary.
    if len(index_name) > 128:
        index_name = index_name[:123].strip('-')
    full_index = f"{index_name}-{chunk_index}"
    return full_index

def split_text(text, chunk_size=3000):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def scrape_authenticated_page(url):
    driver = webdriver.Edge(service=EdgeService(EdgeChromiumDriverManager().install()))
    driver.get(url)
    
    input("Please log in to the website in the opened Edge window, then press Enter here to continue...")
    
    # Wait a few seconds to ensure the page is fully loaded.
    time.sleep(5)
    
    html = driver.page_source
    driver.quit()
    return html

def extract_text_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(['header', 'nav', 'footer']):
        tag.decompose()
    for element in soup(["script", "style"]):
        element.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r'\s+', ' ', text)

# Function to create or replace an index in Azure Cognitive Search.
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

    try:
        index_client.delete_index(index_name)
        print(f"Deleted existing index {index_name}")
    except Exception:
        print(f"No existing index {index_name}, creating new one.")

    index_client.create_index(index)
    print(f"Created index {index_name}")

def upload_documents(service_name, admin_key, index_name, documents):
    endpoint = f"https://{service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)
    results = search_client.upload_documents(documents=documents)
    print(f"Uploaded {len(documents)} documents to index {index_name}")
    return results

def main():
    for url in URLS_TO_INDEX:
        print(f"Processing URL: {url}")
        html = scrape_authenticated_page(url)
        if not html:
            print(f"No HTML retrieved from {url}")
            continue
        
        text = extract_text_from_html(html)
        if not text:
            print(f"No text extracted from {url}")
            continue
        
        text_chunks = split_text(text)
        index_name = generate_valid_id(url, 0)
        create_or_replace_index(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name)
        
        documents = [
            {
                "id": generate_valid_id(url, i),
                "content": chunk,
                "file_name": url,
                "upload_date": datetime.now(timezone.utc).isoformat()
            }
            for i, chunk in enumerate(text_chunks)
        ]
        upload_documents(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name, documents)

if __name__ == "__main__":
    main()
