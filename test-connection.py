import os
import requests
from dotenv import load_dotenv

load_dotenv()

OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

headers = {
    "Content-Type": "application/json",
    "api-key": OPENAI_API_KEY
}

data = {
    "messages": [{"role": "user", "content": "Hello, how are you?"}],
    "max_tokens": 50
}

response = requests.post(OPENAI_ENDPOINT, headers=headers, json=data)

print(response.status_code)
print(response.json())
