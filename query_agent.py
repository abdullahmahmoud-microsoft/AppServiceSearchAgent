import os
import re
import time
import json
import requests
from flask import Flask, request, jsonify
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

# Load configuration from .env file
load_dotenv()
SEARCH_SERVICE_NAME = os.environ.get("SEARCH_SERVICE_NAME")
ADMIN_KEY = os.environ.get("ADMIN_KEY")
OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME")

# Initialize Flask app
app = Flask(__name__)

# Global in-memory session history (dictionary keyed by user_id)
session_history = {}

# --- Search Functions (unchanged) ---
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

def generate_response(messages):
    """
    Given a list of messages (dictionaries with 'role' and 'content'),
    generate a response using the OpenAI endpoint.
    """
    headers = {
        "Content-Type": "application/json",
        "api-key": OPENAI_API_KEY
    }
    data = {
        "model": DEPLOYMENT_NAME,
        "messages": messages,
        "max_tokens": 1000
    }
    response = requests.post(OPENAI_ENDPOINT, headers=headers, json=data)
    try:
        return response.json().get("choices", [{}])[0].get("message", {}).get("content", "No response.")
    except Exception as e:
        print("Error processing OpenAI response:", e)
        return "No response."

# --- Conversation Storage and Summarization ---
# Import the QA generation function from the indexing module.
# (We assume create_index.py is in the same directory)
from create_index import generate_qa_pairs, create_or_replace_index, upload_documents

def store_conversation(user_id, conversation_history):
    """
    Takes the conversation history (a list of (role, message) tuples),
    concatenates it into a single text block, and uses GPT to generate
    a list of Q&A pairs. Then it calls the indexing functions to create
    (or replace) an index and upload documents.
    """
    # Concatenate the conversation history into a single text chunk.
    # You might format it as "User: ...\nAssistant: ..." for clarity.
    convo_text = "\n".join([f"{role.capitalize()}: {content}" for role, content in conversation_history])
    print("Storing conversation:\n", convo_text)

    # Generate QA pairs using GPT (this works similarly to your existing function)
    qa_pairs = generate_qa_pairs(convo_text, f"conversation-{user_id}")
    if not qa_pairs:
        print("No QA pairs were generated.")
        return False

    # Prepare documents for indexing.
    documents = []
    doc_index = 0
    # We use a placeholder title for the entire conversation.
    page_title = f"Conversation from {user_id}"
    for qa in qa_pairs:
        if not isinstance(qa, dict):
            print("Skipping non-dict QA pair:", qa)
            continue
        question = " ".join(qa.get("question", "").split())
        answer = " ".join(qa.get("answer", "").split())
        if not question or not answer:
            continue
        doc = {
            "id": f"{user_id}-{doc_index}",
            "doc_type": "qa",
            "page_title": page_title,
            "title": question,
            "content": f"Question: {question}\nAnswer: {answer}",
            "file_name": f"conversation-{user_id}",
            "upload_date":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
        documents.append(doc)
        doc_index += 1

    # Create a unique index name for this conversation.
    index_name = f"conversation-{user_id}".lower()
    create_or_replace_index(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name)
    upload_documents(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name, documents)
    print("Conversation stored to knowledge base.")
    return True

# --- Flask Endpoint for Bot Messaging ---
@app.route("/api/messages", methods=["POST"])
def messages():
    req = request.get_json()
    # Assume that the incoming request contains a 'user_id' and 'text' field.
    user_id = req.get("user_id") or request.remote_addr  # fallback to IP if no user_id provided
    user_text = req.get("text", "").strip()

    # Initialize conversation history for new sessions
    if user_id not in session_history:
        session_history[user_id] = []

    history = session_history[user_id]

    # Check if the user is instructing the bot to store the conversation.
    # Here we check if the message contains a trigger phrase.
    if re.search(r'store\s+.*(knowledge base|index)', user_text, re.IGNORECASE):
        # Call GPT on the entire conversation history to extract QA pairs and store them.
        success = store_conversation(user_id, history)
        # Clear the conversation history (or keep it as desired)
        session_history[user_id] = []
        if success:
            return jsonify({"type": "message", "text": "Your conversation has been stored in the knowledge base."})
        else:
            return jsonify({"type": "message", "text": "Failed to store conversation. Please try again."})

    # Otherwise, this is a normal chat message.
    # Append the user's message to the conversation history.
    history.append(("user", user_text))

    # Build the prompt messages for OpenAI including conversation history.
    messages_for_model = []
    for role, content in history:
        messages_for_model.append({"role": role, "content": content})
    # Generate response using GPT.
    assistant_reply = generate_response(messages_for_model)

    # Append the bot's reply to the conversation history.
    history.append(("assistant", assistant_reply))
    # Optionally, you can query search indices and include that context.
    # For example:
    search_results = query_search_indices(SEARCH_SERVICE_NAME, ADMIN_KEY, user_text, INDICES)
    if search_results:
        assistant_reply += "\n\nAdditional context:\n" + " ".join(search_results)

    # Return the answer in Bot Framework's expected JSON format.
    return jsonify({"type": "message", "text": assistant_reply})

if __name__ == "__main__":
    # Run on port 3978 (default for Bot Framework Emulator)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3978)))