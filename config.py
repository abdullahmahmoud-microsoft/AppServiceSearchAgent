import os

class DefaultConfig:
    """Bot Configuration"""

    PORT = int(os.environ.get("PORT", 3978))
    APP_ID = os.environ.get("MicrosoftAppId", "")
    APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
    APP_TYPE = os.environ.get("MicrosoftAppType", "UserAssignedMSI")
    APP_TENANTID = os.environ.get("MicrosoftAppTenantId", "")
    SEARCH_SERVICE_NAME = os.environ.get("SEARCH_SERVICE_NAME", "")
    ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
    OPENAI_ENDPOINT = os.environ.get("OPENAI_ENDPOINT", "")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME", "")
    USER_ASSIGNED_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")
