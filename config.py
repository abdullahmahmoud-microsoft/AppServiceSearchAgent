import os

class DefaultConfig:
    MicrosoftAppId = os.environ.get("MicrosoftAppId", "")  # Your bot's App Registration ID
    MicrosoftAppType = os.environ.get("MicrosoftAppType", "UserAssignedMSI")
    MicrosoftAppTenantId = os.environ.get("MicrosoftAppTenantId", "")
    MicrosoftAppClientId = os.environ.get("AZURE_CLIENT_ID", "")  # UAMI Client ID

