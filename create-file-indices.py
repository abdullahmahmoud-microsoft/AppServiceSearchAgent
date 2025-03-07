'''
Sidelining this script for now. It creates indices the old way for now. create-web-indices.py has the new high tech stuff.
'''

import os
import re
import json
import time
import fitz  # PyMuPDF
import requests
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
OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME")

blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)

def generate_valid_id(blob_name, chunk_index):
    blob_name = blob_name.replace('.pdf', '').replace('.md', '').lower()
    index_name = re.sub(r'[^a-z0-9-]', '-', blob_name).strip('-')
    if len(index_name) > 128:
        index_name = index_name[:128]
    return f"{index_name}-{chunk_index}"

def split_text(text, chunk_size=3000):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def extract_text_from_pdf(file_path):
    document = fitz.open(file_path)
    return " ".join([page.get_text() for page in document])

def extract_text_from_md(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()

def generate_qa_pairs(file_text, file_name, max_retries=3):
    # Determine target number of Q&A pairs based on document length to prevent it from making stuff up if the document is short.
    target = max(10, min(35, int(len(file_text) / 1000)))

    prompt = (
        "You are Deployment Assistant, an expert in deployment and engineering support. "
        f"Based on the following document content, generate approximately {target} detailed question-answer pairs that an experienced engineer might ask about the content. "
        "Ensure the questions and answers are related to the given text.  "
        "Do NOT make up words or context or resolve acronyms that you dont have context on what they resolve to . "
        "For each pair, only include it if you are highly confident that the answer is fully supported by the document. If you are not confident or if the answer would be a guess, skip that pair. "
        "Remove any user-specific details (such as IDs, GUIDs, and personal information), "
        "but include detailed step-by-step instructions if the documentation contains them. "
        "Accurately cover all technical aspects mentioned in the document, including configuration steps, error resolutions, and command syntax, without omitting any crucial details."
        "Do not invent resolved names for acronyms unless you are absolutely certain of what the acronym means. "
        "Return the output in JSON format as a list of objects, each with 'question' and 'answer' fields.\n\n"
        "Document Content:\n" + file_text
    )
    headers = {"Content-Type": "application/json", "api-key": OPENAI_API_KEY}
    data = {
        "model": DEPLOYMENT_NAME,
        "messages": [
            {"role": "system", "content": "You are an AI assistant that generates detailed Q&A pairs for deployment-related documents."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 4000
    }
    
    attempt = 0
    while attempt < max_retries:
        response = requests.post(OPENAI_ENDPOINT, headers=headers, json=data)
        if response.status_code == 429:
            wait_time = 21
            try:
                error_msg = response.json().get("error", {}).get("message", "")
                match = re.search(r"after (\d+) seconds", error_msg)
                if match:
                    wait_time = int(match.group(1))
            except Exception:
                pass
            print(f"Rate limit exceeded. Waiting for {wait_time} seconds before retrying...")
            time.sleep(wait_time)
            attempt += 1
            continue

        try:
            response_json = response.json()
        except Exception as e:
            print("Error parsing response as JSON:", e)
            return []
            
        message_content = response_json.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        if message_content.startswith("```json"):
            message_content = message_content[len("```json"):].strip()
        if message_content.endswith("```"):
            message_content = message_content[:-3].strip()
        try:
            qa_pairs = json.loads(message_content)
            if isinstance(qa_pairs, str):
                qa_pairs = json.loads(qa_pairs)
            if isinstance(qa_pairs, list) and all(isinstance(item, dict) for item in qa_pairs):
                return qa_pairs
            else:
                print("Parsed QA pairs are not in the expected format:", qa_pairs)
                return []
        except Exception as e:
            print("Error parsing QA pairs:", e)

            match = re.search(r'\[.*\]', message_content, re.DOTALL)
            if match:
                trimmed = match.group(0)
                try:
                    qa_pairs = json.loads(trimmed)
                    if isinstance(qa_pairs, list) and all(isinstance(item, dict) for item in qa_pairs):
                        return qa_pairs
                except Exception as e2:
                    print("Error parsing trimmed QA pairs:", e2)
            return []
    print("Max retries reached for", file_name)
    return []

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
            if blob.name.endswith(".pdf"):
                text = extract_text_from_pdf(download_file_path)
            else:
                text = extract_text_from_md(download_file_path)
            qa_pairs = generate_qa_pairs(text, blob.name)
            if not qa_pairs:
                print(f"Failed to generate Q&A pairs for {blob.name}. Skipping.")
                os.remove(download_file_path)
                continue
            documents = []
            for i, qa in enumerate(qa_pairs):
                if not isinstance(qa, dict):
                    print(f"Skipping QA pair {i} for {blob.name} because it is not a dict.")
                    continue
                question = qa.get("question", "").strip()
                answer = qa.get("answer", "").strip()
                content = f"Question: {question}\nAnswer: {answer}"
                doc = {
                    "id": generate_valid_id(blob.name, i),
                    "content": content,
                    "file_name": blob.name,
                    "upload_date": blob.creation_time.isoformat() if hasattr(blob, "creation_time") and blob.creation_time else ""
                }
                documents.append(doc)
            index_name_final = generate_valid_id(blob.name, 0)
            create_or_replace_index(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name_final)
            upload_documents(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name_final, documents)
            os.remove(download_file_path)

if __name__ == "__main__":
    main()