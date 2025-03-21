import sys
import traceback
import logging
from datetime import datetime
from aiohttp import web
from botbuilder.core import TurnContext
from botbuilder.core.integration import aiohttp_error_middleware
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botbuilder.schema import Activity, ActivityTypes
from bot import MyBot
from config import DefaultConfig
from azure.identity import ManagedIdentityCredential
from botframework.connector.auth import ManagedIdentityAppCredentials
from http import HTTPStatus
from aiohttp.web import Response, json_response

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

CONFIG = DefaultConfig()
logger.info(f"Loaded configuration: {CONFIG}")
logger.info(f"PORT: {CONFIG.PORT}")
logger.info(f"APP_ID: {CONFIG.APP_ID}")
logger.info(f"APP_PASSWORD: {CONFIG.APP_PASSWORD}")
logger.info(f"APP_TYPE: {CONFIG.APP_TYPE}")
logger.info(f"APP_TENANTID: {CONFIG.APP_TENANTID}")
logger.info(f"SEARCH_SERVICE_NAME: {CONFIG.SEARCH_SERVICE_NAME}")
logger.info(f"ADMIN_KEY: {CONFIG.ADMIN_KEY}")
logger.info(f"OPENAI_ENDPOINT: {CONFIG.OPENAI_ENDPOINT}")
logger.info(f"OPENAI_API_KEY: {CONFIG.OPENAI_API_KEY}")
logger.info(f"DEPLOYMENT_NAME: {CONFIG.DEPLOYMENT_NAME}")
logger.info(f"USER_ASSIGNED_CLIENT_ID: {CONFIG.USER_ASSIGNED_CLIENT_ID}")

ADAPTER = CloudAdapter(ConfigurationBotFrameworkAuthentication(CONFIG))

logger.info("Created CloudAdapter with authentication configuration")

# Catch-all for errors.
async def on_error(context: TurnContext, error: Exception):
    logger.error(f"\n [on_turn_error] unhandled error: {error}", exc_info=True)
    traceback.print_exc()

    # Send a message to the user
    await context.send_activity("The bot encountered an error or bug.")
    await context.send_activity(
        "To continue to run this bot, please fix the bot source code."
    )
    # Send a trace activity if we're talking to the Bot Framework Emulator
    if context.activity.channel_id == "emulator":
        trace_activity = Activity(
            label="TurnError",
            name="on_turn_error Trace",
            timestamp=datetime.utcnow(),
            type=ActivityTypes.trace,
            value=f"{error}",
            value_type="https://www.botframework.com/schemas/error",
        )
        await context.send_activity(trace_activity)

ADAPTER.on_turn_error = on_error
logger.info("Set on_turn_error handler for ADAPTER")

# Create the Bot
BOT = MyBot()
logger.debug("Created MyBot instance")

# Listen for incoming requests on /api/messages
async def messages(req: web.Request) -> web.Response:
    logger.info("Received request at /api/messages")
    logger.info(f"Request headers: {req.headers}")

    if "application/json" in req.headers["Content-Type"]:
        body = await req.json()
        logger.info(f"Request body: {body}")
    else:
        logger.warning("Unsupported media type")
        return Response(status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

    try:
        activity = Activity().deserialize(body)
        logger.info(f"Deserialized activity: {activity}")
    except Exception as e:
        logger.error(f"Failed to deserialize activity: {e}", exc_info=True)
        return Response(status=HTTPStatus.BAD_REQUEST)

    auth_header = req.headers["Authorization"] if "Authorization" in req.headers else ""
    logger.info(f"Authorization header: {auth_header}")

    try:
        response = await ADAPTER.process_activity(auth_header, activity, BOT.on_turn)
        if response:
            logger.info("Response generated by bot")
            logger.info(f"Response body: {response.body}")
            return json_response(data=response.body, status=response.status)
        logger.info("No response generated by bot")
        return Response(status=HTTPStatus.OK)
    except Exception as e:
        logger.error(f"Error processing activity: {e}", exc_info=True)
        return Response(status=HTTPStatus.INTERNAL_SERVER_ERROR)

APP = web.Application(middlewares=[aiohttp_error_middleware])
logger.info("Created web application with aiohttp_error_middleware")
APP.router.add_post("/api/messages", messages)
logger.info("Added POST route for /api/messages")

if __name__ == "__main__":
    try:
        logger.info("Starting web application")
        web.run_app(APP, host="0.0.0.0", port=CONFIG.PORT)
    except Exception as error:
        logger.error("Failed to start web application", exc_info=True)
        raise error