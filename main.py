import os
import requests
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv

load_dotenv()

SEARCH_SERVICE_NAME = os.environ.get("SEARCH_SERVICE_NAME")
ADMIN_KEY = os.environ.get("ADMIN_KEY")
OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME")

# List of all available indices
INDICES = [
    "do-debugger-0",
    "do-upgrade-0",
    "minidash-minidashn-0",
    "minidash-minidashn-troubleshooting-0",
    "onboarding-0",
    "tools-0",
    "eng-ms-docs-cloud-ai-platform-devdiv-serverless-paas-balam-serverless-paas-vikr-app-service-web-apps-app-service-team-docum-0"
]

def query_search_indices(service_name, admin_key, query, indices):
    endpoint = f"https://{service_name}.search.windows.net"
    credential = AzureKeyCredential(admin_key)
    all_results = []

    for index in indices:
        search_client = SearchClient(endpoint=endpoint, index_name=index, credential=credential)
        results = search_client.search(
            search_text=query, 
            search_mode="any",
            query_type="simple", 
            top=5, 
            search_fields=["content"],
            highlight_pre_tag="<b>", 
            highlight_post_tag="</b>"
        )
        count = 0
        for result in results:
            content = result.get("content")
            if content:
                all_results.append(f"[{index}] {content}")
                count += 1

    return all_results

def generate_response(user_input, context):
    headers = {
        "Content-Type": "application/json",
        "api-key": OPENAI_API_KEY
    }
    
    # The prompt instructs GPT-4 to use the provided context as a guide while still allowing flexibility.
    prompt = (
        "Your name is Deployment Assistant. "
        "Below is a block of context that may contain relevant instructions. "
        "Please answer the following question using the context as a guide. "
        "If the context contains sufficient details, base your answer strongly on it. "
        "If parts of the answer require natural language completion, feel free to fill in the blanks but be concise, "
        "but do not make up details or guess what acronyms stand for if the context does not support them. "
        "If there are html or .md tags, you can ignore them. "
        ""
        "Context:\n"
        f"{context}\n\n"
        "Question:\n"
        f"{user_input}"
    )
    
    messages = [
        {"role": "system", "content": "You are an AI assistant. Use the provided context as your primary guide, but feel free to be natural and fill in details if needed. Do not invent details if the context is insufficient."},
        {"role": "user", "content": prompt}
    ]
    
    # Increase max_tokens to allow for a longer, natural response.
    data = {"model": DEPLOYMENT_NAME, "messages": messages, "max_tokens": 2000}
    response = requests.post(OPENAI_ENDPOINT, headers=headers, json=data)
    return response.json().get("choices", [{}])[0].get("message", {}).get("content", "No response.")

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
            print("Sorry I dont know how to answer that yet. Please send this prompt to aaboumahmoud.")
        else:
            print("\nResponse from GPT-4:\n", response)

if __name__ == "__main__":
    main()