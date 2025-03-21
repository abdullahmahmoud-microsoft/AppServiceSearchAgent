import os

class DefaultConfig:
    """Bot Configuration"""
    PORT = 3978
    APP_ID = os.environ.get("MicrosoftAppId", "")
    APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
    APP_TYPE = os.environ.get("MicrosoftAppType", "UserAssignedMSI")
    USER_ASSIGNED_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")
