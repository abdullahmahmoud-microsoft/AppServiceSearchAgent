import os

class DefaultConfig:
    PORT = int(os.environ.get("PORT", 3978))
    MicrosoftAppId = os.environ.get("MicrosoftAppId", "")
    MicrosoftAppType = os.environ.get("MicrosoftAppType", "UserAssignedMSI")
    MicrosoftAppTenantId = os.environ.get("MicrosoftAppTenantId", "")
    MicrosoftAppClientId = os.environ.get("AZURE_CLIENT_ID", "")
