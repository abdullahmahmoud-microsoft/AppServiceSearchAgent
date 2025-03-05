import os
import requests
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

load_dotenv()

SEARCH_SERVICE_NAME = os.environ.get("SEARCH_SERVICE_NAME")
ADMIN_KEY = os.environ.get("ADMIN_KEY")
OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME")

def get_indices(service_name, admin_key):
    endpoint = f"https://{service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)
    return [index.name for index in index_client.list_indexes()]

INDICES = get_indices(SEARCH_SERVICE_NAME, ADMIN_KEY)

def query_search_indices(service_name, admin_key, query, indices):
    endpoint = f"https://{service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    all_results = []

    for index in indices:
        search_client = SearchClient(endpoint=endpoint, index_name=index, credential=credential)
        results = search_client.search(
            search_text=query, 
            query_type="semantic",
            semantic_configuration_name="default",
            top=5, 
            search_fields=["title", "content"]
        )
        for result in results:
            doc_type = result.get("doc_type", "unknown")
            title = result.get("title", "No Title")
            content = result.get("content", "")
            if content:
                all_results.append(f"[{index}][{doc_type}] {title}: {content}")
    return all_results

def generate_response(user_input, context):
    headers = {
        "Content-Type": "application/json",
        "api-key": OPENAI_API_KEY
    }
    
    prompt = (
        "Your name is App Service Assistant. Your leader is Bilal Alam."
        "Below is a block of context that may contain relevant instructions. "
        "Answer the following question mainly using the details provided in the context. "
        "Do not invent details or guess what acronyms stand for if the context does not support them.\n"
        "Context:\n"
        f"{context}\n\n"
        "Question:\n"
        f"{user_input}"
    )
    
    messages = [
        {"role": "system", "content": "You are an AI assistant. Use the provided context as your primary guide. Do not invent details if the context is insufficient."},
        {"role": "user", "content": prompt}
    ]
    
    data = {"model": DEPLOYMENT_NAME, "messages": messages, "max_tokens": 1000}
    response = requests.post(OPENAI_ENDPOINT, headers=headers, json=data)
    
    try:
        return response.json().get("choices", [{}])[0].get("message", {}).get("content", "No response.")
    except Exception as e:
        print("Error processing OpenAI response:", e)
        return "No response."

def main():
    while True:
        user_query = input("Ask a question (or type 'exit' to quit): ")
        if user_query.lower() == 'exit':
            break

        search_results = query_search_indices(SEARCH_SERVICE_NAME, ADMIN_KEY, user_query, INDICES)
        context = " ".join(search_results) if search_results else "No relevant documents found."

        if context == "No relevant documents found.":
            print("Warning: No documents matched the query across the indices.")

        response = generate_response(user_query, context)
        if "No response" in response:  
            print("Sorry, I don't know how to answer that yet. Please send this prompt to aaboumahmoud.")
        else:
            print("\nResponse from App Service Assistant:\n", response)

if __name__ == "__main__":
    main()
