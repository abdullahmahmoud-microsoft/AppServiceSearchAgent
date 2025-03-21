import os
import traceback
import logging
from datetime import datetime
from aiohttp import web
from botbuilder.core import TurnContext
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botbuilder.core.integration import aiohttp_error_middleware
from botbuilder.schema import Activity, ActivityTypes
from bot import MyBot
from config import DefaultConfig
from azure.identity import ManagedIdentityCredential
from http import HTTPStatus
from aiohttp.web import Response, json_response
import jwt  # For debugging only

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG = DefaultConfig()

# 🔍 Patch token validation to debug Invalid AppId errors
original_authenticate_request = ConfigurationBotFrameworkAuthentication.authenticate_request

async def debug_authenticate_request(self, activity, auth_header):
    logger.info("🔍 Token validation triggered...")
    logger.info(f"✅ CONFIG.MicrosoftAppId: {CONFIG.MicrosoftAppId}")
    logger.info(f"✅ CONFIG.MicrosoftAppClientId (UAMI): {CONFIG.MicrosoftAppClientId}")
    logger.info(f"✅ CONFIG.MicrosoftAppTenantId: {CONFIG.MicrosoftAppTenantId}")
    logger.info(f"✅ CONFIG.MicrosoftAppType: {CONFIG.MicrosoftAppType}")

    try:
        parts = auth_header.split(" ")
        if len(parts) == 2 and parts[0].lower() == "bearer":
            decoded = jwt.decode(parts[1], options={"verify_signature": False})
            logger.info("🔐 Decoded token:")
            for k, v in decoded.items():
                logger.info(f"  {k}: {v}")
        else:
            logger.info("⚠️ No bearer token found in Authorization header.")
    except Exception as e:
        logger.info(f"⚠️ Failed to decode token: {e}")

    return await original_authenticate_request(self, activity, auth_header)

ConfigurationBotFrameworkAuthentication.authenticate_request = debug_authenticate_request

# 🔧 Create adapter
auth_config = ConfigurationBotFrameworkAuthentication(CONFIG)
ADAPTER = CloudAdapter(auth_config)
logger.info("Created CloudAdapter with authentication configuration")

# 🔄 Catch-all for unhandled errors
async def on_error(context: TurnContext, error: Exception):
    logger.error(f"[on_turn_error] unhandled error: {error}", exc_info=True)
    await context.send_activity("The bot encountered an error.")
    await context.send_activity("Please fix the bot source code.")
    if context.activity.channel_id == "emulator":
        await context.send_activity(Activity(
            label="TurnError",
            name="on_turn_error Trace",
            timestamp=datetime.now(datetime.timezone.utc),
            type=ActivityTypes.trace,
            value=f"{error}",
            value_type="https://www.botframework.com/schemas/error",
        ))

ADAPTER.on_turn_error = on_error

# 🤖 Create bot instance
BOT = MyBot()

# ✅ Debug token endpoint
async def debug_token(req):
    try:
        credential = ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])
        token = credential.get_token("https://api.botframework.com/.default")
        return Response(text=f"✅ Got token:\n{token.token[:50]}...", status=200)
    except Exception as e:
        return Response(text=f"❌ Failed to get token: {str(e)}", status=500)

# 📥 Incoming messages
async def messages(req: web.Request) -> web.Response:
    logger.info("Received request at /api/messages")
    logger.info(f"Request headers: {req.headers}")

    if "application/json" not in req.headers.get("Content-Type", ""):
        logger.warning("Unsupported media type")
        return Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

    try:
        body = await req.json()
        logger.info(f"Request body: {body}")
        activity = Activity().deserialize(body)
    except Exception as e:
        logger.error(f"Failed to deserialize activity: {e}", exc_info=True)
        return Response(status=HTTPStatus.BAD_REQUEST)

    auth_header = req.headers.get("Authorization", "")
    logger.info(f"Authorization header: {auth_header[:80]}...")

    try:
        response = await ADAPTER.process_activity(auth_header, activity, BOT.on_turn)
        if response:
            return json_response(data=response.body, status=response.status)
        return Response(status=HTTPStatus.OK)
    except Exception as e:
        logger.error(f"Error processing activity: {e}", exc_info=True)
        return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

# 🌐 App init
APP = web.Application(middlewares=[aiohttp_error_middleware])
APP.router.add_post("/api/messages", messages)
APP.router.add_get("/debug-token", debug_token)

logger.info("App is ready!")

if __name__ == "__main__":
    try:
        web.run_app(APP, host="0.0.0.0", port=3978)
    except Exception as error:
        logger.error("Failed to start web application", exc_info=True)
        raise error