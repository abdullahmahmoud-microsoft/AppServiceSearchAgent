import os
import re
import time
import json
import ast
import hashlib
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

load_dotenv()

SEARCH_SERVICE_NAME = os.environ.get("SEARCH_SERVICE_NAME")
ADMIN_KEY = os.environ.get("ADMIN_KEY")
OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME")
API_VERSION = "2021-04-30-Preview"

def generate_index_name(url):
    slug = url.replace("https://", "").replace("http://", "").replace("_", "-").lower()
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    h = hashlib.md5(url.encode()).hexdigest()
    return f"{slug[:60]}-{h[:8]}"

def generate_valid_id(url, doc_index):
    index_name = generate_index_name(url)
    return f"{index_name}-{doc_index}"

def split_text(text, chunk_size=3000):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

def scrape_authenticated_page(url):
    options = webdriver.EdgeOptions()

    driver = webdriver.Edge(options=options, service=EdgeService(EdgeChromiumDriverManager().install()))
    driver.get(url)

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "_content"))
        )
    except Exception as e:
        print("Warning: Main content not detected; proceeding anyway.", e)
    html = driver.page_source
    driver.quit()
    return html

def extract_title(html):
    soup = BeautifulSoup(html, 'html.parser')
    if soup.title:
        return soup.title.get_text().strip()
    return ""

def extract_main_content(html):
    """
    Extracts the core documentation text.
    It first looks for an <article id="_content"> element and, if found,
    returns its text (after removing extraneous elements). Otherwise,
    it falls back to collecting text from all paragraph tags.
    """
    soup = BeautifulSoup(html, 'html.parser')
    article = soup.find('article', id="_content")
    if article:
        for unwanted in article.find_all(['nav', 'header', 'footer', 'aside', 'script', 'style']):
            unwanted.decompose()
        return article.get_text(separator="\n").strip()
    else:
        paragraphs = soup.find_all('p')
        texts = [p.get_text(separator=" ").strip() for p in paragraphs if p.get_text().strip()]
        if texts:
            return "\n".join(texts)
        return soup.get_text(separator="\n").strip()

def extract_sections_from_article(html):
    soup = BeautifulSoup(html, 'html.parser')
    article = soup.find('article', id="_content")
    sections = []
    if article:

        for unwanted in article.find_all(['nav', 'header', 'footer', 'aside', 'script', 'style']):
            unwanted.decompose()

        h2_containers = article.find_all("div", class_=lambda x: x and "h2-container" in x)
        if h2_containers:
            for i, container in enumerate(h2_containers):
                h_heading = container.find(['h1','h2','h3','h4','h5','h6'])
                if h_heading:
                    sec_title = h_heading.get_text(strip=True)
                    h_heading.decompose()
                else:
                    sec_title = f"Section {i+1}"
                sec_content = container.get_text(separator="\n", strip=True)
                sections.append({"title": sec_title, "content": sec_content})
        else:
            # Use headers if previous approach fails
            headings = article.find_all(['h1','h2','h3','h4','h5','h6'])
            if headings:
                for i, heading in enumerate(headings):
                    sec_title = heading.get_text(strip=True)
                    content_parts = []
                    for sibling in heading.find_next_siblings():
                        if sibling.name in ['h1','h2','h3','h4','h5','h6']:
                            break
                        text = sibling.get_text(separator=" ", strip=True)
                        if text:
                            content_parts.append(text)
                    sec_content = "\n".join(content_parts).strip()
                    if not sec_title:
                        sec_title = f"Section {i+1}"
                    sections.append({"title": sec_title, "content": sec_content})
            else:
                full_text = article.get_text(separator="\n").strip()
                sections.append({"title": "Untitled Section", "content": full_text})
    else:
        paragraphs = soup.find_all('p')
        for i, p in enumerate(paragraphs):
            text = p.get_text(separator=" ", strip=True)
            if text:
                sections.append({"title": f"Section {i+1}", "content": text})
        if not sections:
            full_text = soup.get_text(separator="\n").strip()
            sections.append({"title": "Untitled Section", "content": full_text})
    return sections

def generate_qa_pairs(text_chunk, url, max_retries=3):
    target = max(10, min(50, int(len(text_chunk) / 1000))) * 2
    prompt = (
        "You are called Antares Genie, an expert in engineering support for the Azure App Service Team led by Bilal Alam. "
        "Based solely on the **core content** provided below (ignore navigation menus, headers, footers, sidebars, and extraneous UI elements), "
        f"generate approximately {target} highly relevant question-answer pairs that are directly supported by the text. "
        "Each Q&A pair must be specific and accurate. If the text does not provide a clear, definitive answer, skip generating that pair. "
        "Replace any user-specific details (such as IDs, GUIDs, or personal information) with placeholders. "
        "Return your answer in JSON format as a list of objects, each with a 'question' field and an 'answer' field.\n\n"
        "Content:\n" + text_chunk
    )
    headers = {"Content-Type": "application/json", "api-key": OPENAI_API_KEY}
    data = {
        "model": DEPLOYMENT_NAME,
        "messages": [
            {"role": "system", "content": "You are an AI assistant that generates detailed Q&A pairs from provided content."},
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
            print(f"Rate limit exceeded. Waiting for {wait_time} seconds...")
            time.sleep(wait_time)
            attempt += 1
            continue
        try:
            response_json = response.json()
        except Exception as e:
            print("Error parsing JSON:", e)
            return []
        message_content = response_json.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if message_content.startswith("```json"):
            message_content = message_content[len("```json"):].strip()
        if message_content.endswith("```"):
            message_content = message_content[:-3].strip()
        message_content_clean = re.sub(r'[\x00-\x1F]+', ' ', message_content)
        try:
            qa_pairs = json.loads(message_content_clean)
            if isinstance(qa_pairs, str):
                qa_pairs = json.loads(qa_pairs)
            if isinstance(qa_pairs, list) and all(isinstance(item, dict) for item in qa_pairs):
                return qa_pairs
            else:
                print("Parsed Q&A pairs not in expected format:", qa_pairs)
                return []
        except Exception as e:
            print("Error parsing Q&A pairs:", e)
            try:
                qa_pairs = ast.literal_eval(message_content_clean)
                if isinstance(qa_pairs, list) and all(isinstance(item, dict) for item in qa_pairs):
                    return qa_pairs
                else:
                    print("AST literal_eval parsed Q&A pairs not in expected format:", qa_pairs)
                    return []
            except Exception as e2:
                print("Error parsing Q&A pairs with ast.literal_eval:", e2)
                match = re.search(r'\[.*\]', message_content_clean, re.DOTALL)
                if match:
                    trimmed = match.group(0)
                    try:
                        qa_pairs = json.loads(trimmed)
                        if isinstance(qa_pairs, list) and all(isinstance(item, dict) for item in qa_pairs):
                            return qa_pairs
                    except Exception as e3:
                        print("Error parsing trimmed Q&A pairs:", e3)
                return []
    print("Max retries reached for", url)
    return []

def create_or_replace_index(service_name, admin_key, index_name):
    url = f"https://{service_name}.search.windows.net/indexes/{index_name}?api-version={API_VERSION}"
    headers = {"Content-Type": "application/json", "api-key": admin_key}
    
    fields = [
        {
            "name": "id",
            "type": "Edm.String",
            "searchable": True,
            "filterable": True,
            "retrievable": True,
            "sortable": True,
            "facetable": True,
            "key": True,
            "synonymMaps": []
        },
        {
            "name": "doc_type",
            "type": "Edm.String",
            "searchable": True,
            "filterable": True,
            "retrievable": True,
            "sortable": False,
            "facetable": False,
            "key": False,
            "synonymMaps": []
        },
        {
            "name": "page_title",
            "type": "Edm.String",
            "searchable": True,
            "filterable": True,
            "retrievable": True,
            "sortable": True,
            "facetable": False,
            "key": False,
            "synonymMaps": []
        },
        {
            "name": "title",
            "type": "Edm.String",
            "searchable": True,
            "filterable": True,
            "retrievable": True,
            "sortable": True,
            "facetable": True,
            "key": False,
            "synonymMaps": []
        },
        {
            "name": "content",
            "type": "Edm.String",
            "searchable": True,
            "filterable": True,
            "retrievable": True,
            "sortable": True,
            "facetable": True,
            "key": False,
            "synonymMaps": []
        },
        {
            "name": "file_name",
            "type": "Edm.String",
            "searchable": True,
            "filterable": True,
            "retrievable": True,
            "sortable": True,
            "facetable": True,
            "key": False,
            "synonymMaps": []
        },
        {
            "name": "upload_date",
            "type": "Edm.DateTimeOffset",
            "searchable": False,
            "filterable": True,
            "retrievable": True,
            "sortable": True,
            "facetable": True,
            "key": False,
            "synonymMaps": []
        }
    ]
    
    index_definition = {
        "name": index_name,
        "fields": fields,
        "semantic": {
            "configurations": [
                {
                    "name": "default",
                    "prioritizedFields": {
                        "titleField": {"fieldName": "file_name"},
                        "prioritizedContentFields": [{"fieldName": "content"}],
                        "prioritizedKeywordsFields": []
                    }
                }
            ]
        },
        "scoringProfiles": [],
        "suggesters": [],
        "analyzers": [],
        "normalizers": [],
        "tokenizers": [],
        "tokenFilters": [],
        "charFilters": [],
        "similarity": {"@odata.type": "#Microsoft.Azure.Search.BM25Similarity"}
    }
    
    delete_response = requests.delete(url, headers=headers)
    if delete_response.status_code in [200, 204]:
        print(f"Deleted existing index {index_name}")
    else:
        print(f"No existing index {index_name} or delete failed: {delete_response.text}")
    
    create_response = requests.put(url, headers=headers, json=index_definition)
    if create_response.status_code == 201:
        print(f"Created index {index_name} with semantic configuration.")
    else:
        print(f"Failed to create index {index_name}: {create_response.text}")

def upload_documents(service_name, admin_key, index_name, documents):
    endpoint = f"https://{service_name}.search.windows.net"
    from azure.search.documents import SearchClient
    from azure.core.credentials import AzureKeyCredential
    credential = AzureKeyCredential(admin_key)
    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)
    results = search_client.upload_documents(documents=documents)
    print(f"Uploaded {len(documents)} documents to index {index_name}")
    return results

def main():
    urls = [
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/do-upgrade",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/raregionexpansion",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/fastdeployments/fastdeployments",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/msdp-deployment",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/msdp-deployment-stage",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/onboarding",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/troubleshoot_deployment",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/deployment-process",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/r2d-franchise-process",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/debug-deployments-start",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/rolepatcher",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/oncalltasks",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/do-debugger",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/configuration-story",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/tipsandtricks",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/ev2deploy-for-testing",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/minidash-minidashn",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/minidash-minidashn-troubleshooting",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/deploymentteamdocs/antreleasestopandstartcriteria",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/sdp/sdp",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/quotaincreases",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/groupquota",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/skucoremappings",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/skuavailability",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/raregionexpansion",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/ase/asebuildout",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/ase/asecapacity",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/ase/selfservease",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/stamps/newstampbuildouts",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/stamps/stampscapacitydata",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/stamps/stampstateaciscommands",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/capacityteamdocs/stamps/stompupgradedeploymentblockers",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/falconteamdocs/testing/rdp/rdptovmss",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/telemetry/telemetry",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/telemetry/telemetrytroubleshooting",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/telemetry/microsoftwebhostingtracing",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/telemetry/kustogds",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/telemetry/lockdowngenevatables",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/telemetry/platformtelemetryoncall/telemetrychecklist",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustoclusterinfo",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotablesoverview",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresclouddeploymentevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresadmincontrollerevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresadmingeoevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresdataserviceapitransactions",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresdataservicecachechanges",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresdeploylogs",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antareshostroleevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresiislogfrontendtable",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresiislogworkertable",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresruntimedataserviceevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresruntimefrontendevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresruntimeworkerevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antaresruntimeworkersandboxevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antareswebworkereventlogs",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/antareswebworkerfreblogs",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/applicationevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/defaultlogeventtable",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/deploymentevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/frontendthrottlerlogs",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/functionslogs",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/functionsmetrics",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/georegionserviceevents",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/kudu",
        "https://eng.ms/docs/cloud-ai-platform/devdiv/serverless-paas-balam/serverless-paas-vikr/app-service-web-apps/app-service-team-documents/generalteamdocs/documentation/kusto/kustotabledocumentation/roleinstanceheartbeat"
    ]
    
    for url in urls:
        print(f"Processing URL: {url}")
        html = scrape_authenticated_page(url)
        if not html:
            print(f"No HTML retrieved from {url}")
            continue
        
        page_title = extract_title(html)
        main_content = extract_main_content(html)
        if not main_content:
            print(f"No main content extracted from {url}")
            continue
        
        sections = extract_sections_from_article(html)

        qa_pairs = generate_qa_pairs(main_content, url)
        
        documents = []
        doc_index = 0
        
        for section in sections:
            sec_title = section.get("title", "").strip() or f"Section {doc_index+1}"
            sec_content = section.get("content", "").strip()
            if not sec_content:
                continue
            doc = {
                "id": generate_valid_id(url, doc_index),
                "doc_type": "section",
                "page_title": page_title,
                "title": sec_title,
                "content": sec_content,
                "file_name": url,
                "upload_date": datetime.now(timezone.utc).isoformat()
            }
            documents.append(doc)
            doc_index += 1
        
        for qa in qa_pairs:
            if not isinstance(qa, dict):
                print(f"Skipping non-dict QA pair for {url}")
                continue
            question = " ".join(qa.get("question", "").split())
            answer = " ".join(qa.get("answer", "").split())
            if not question or not answer:
                continue
            doc = {
                "id": generate_valid_id(url, doc_index),
                "doc_type": "qa",
                "page_title": page_title,
                "title": question,
                "content": f"Question: {question}\nAnswer: {answer}",
                "file_name": url,
                "upload_date": datetime.now(timezone.utc).isoformat()
            }
            documents.append(doc)
            doc_index += 1
        
        if not documents:
            print(f"No documents created for {url}")
            continue
        
        index_name_final = generate_index_name(url)
        create_or_replace_index(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name_final)
        upload_documents(SEARCH_SERVICE_NAME, ADMIN_KEY, index_name_final, documents)

if __name__ == "__main__":
    main()