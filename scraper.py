from telethon import TelegramClient, events
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputPeerUser
from telethon.errors import (
    UserPrivacyRestrictedError, FloodWaitError, RPCError,
    ApiIdInvalidError, AuthTokenInvalidError, SessionPasswordNeededError
)
import logging
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot's credentials
MY_API_ID = 24494088
MY_API_HASH = '1f40e14758a2aa23c4fe045c2ce8c6c7'
MY_BOT_TOKEN = '7168876595:AAFaadASPhOxQBMnBKZToKi8lpCvvpNYB6U'

# Initialize the bot client with your bot token
bot_client = TelegramClient('bot', api_id=MY_API_ID, api_hash=MY_API_HASH).start(bot_token=MY_BOT_TOKEN)

# Dictionary to store user sessions and credentials
user_sessions = {}
stop_commands = set()

async def scrape_users(client, channel_username, event):
    """Scrape users from a channel and display them."""
    logger.info(f'Scraping users from {channel_username}...')
    users = []
    try:
        async for user in client.iter_participants(channel_username):
            if not user.bot and user.username:  # Skip bots and users without usernames
                users.append(user)
                user_info = f'Found user: {user.first_name} {user.last_name or ""} (@{user.username})'
                logger.info(user_info)
                await event.reply(user_info)
                if len(users) >= 100 or event.chat_id in stop_commands:
                    await event.reply("Stopping the scraping process.")
                    break
    except Exception as e:
        error_msg = f'Error scraping users: {e}'
        logger.error(error_msg)
        await event.reply(error_msg)
    return users

async def add_users_to_group(client, group_username, users, event):
    """Add users to a group."""
    logger.info(f'Adding users to {group_username}...')
    user_count = 0
    for user in users:
        if user_count >= 100:
            await event.reply("Reached the limit of 100 users. Stopping the adding process.")
            break
        try:
            if event.chat_id in stop_commands:
                await event.reply("Stopping the adding process.")
                return
            await client(InviteToChannelRequest(
                channel=group_username,
                users=[InputPeerUser(user.id, user.access_hash)]
            ))
            user_count += 1
            user_info = f'Added user: {user.first_name} {user.last_name or ""} (@{user.username})'
            logger.info(user_info)
            await event.reply(user_info)
        except UserPrivacyRestrictedError:
            privacy_msg = f'Could not add user due to privacy settings: {user.first_name} (@{user.username})'
            logger.warning(privacy_msg)
            await event.reply(privacy_msg)
        except FloodWaitError as e:
            flood_msg = f'Flood wait error. Need to wait {e.seconds} seconds'
            logger.error(flood_msg)
            await event.reply(flood_msg)
            await asyncio.sleep(e.seconds)
        except RPCError as e:
            rpc_error_msg = f'RPC error while adding user {user.id}: {e}'
            logger.error(rpc_error_msg)
            await event.reply(rpc_error_msg)
    await event.reply(f"Added {user_count} users to the group {group_username}.")

@bot_client.on(events.NewMessage(pattern='/start'))
async def start(event):
    """Send a welcome message and provide options."""
    await event.reply('Welcome to the Telegram Scraper Bot!\n\n'
                      'Please choose an option:\n'
                      '/set_credentials - Set your API credentials\n'
                      '/scrape_and_add - Scrape users and add to a group\n'
                      '/stop - Stop the current operation')
    raise events.StopPropagation

@bot_client.on(events.NewMessage(pattern='/set_credentials'))
async def set_credentials(event):
    """Prompt the user to set their API credentials."""
    global user_sessions

    chat_id = event.chat_id

    async with bot_client.conversation(chat_id, timeout=300) as conv:
        try:
            await conv.send_message("Please enter your `API ID`:")
            api_id = int((await conv.get_response()).text.strip())

            await conv.send_message("Please enter your `API Hash`:")
            api_hash = (await conv.get_response()).text.strip()

            await conv.send_message("Please enter your `Phone Number`:")
            phone_number = (await conv.get_response()).text.strip()

            # Store user-specific session details
            user_sessions[chat_id] = {
                'api_id': api_id,
                'api_hash': api_hash,
                'phone_number': phone_number
            }

            await conv.send_message("Credentials set successfully! Use /scrape_and_add to scrape users and add them to a group.")

            # Start the OTP process
            await request_otp(conv, chat_id)

        except (ValueError, TypeError) as e:
            error_msg = "Invalid input format. Please try again."
            logger.error(f"Error in input format: {e}")
            await conv.send_message(error_msg)

async def request_otp(conv, chat_id):
    """Request the OTP from the user."""
    user_session = user_sessions[chat_id]
    api_id = user_session['api_id']
    api_hash = user_session['api_hash']
    phone_number = user_session['phone_number']

    # Create a new client for the user session
    user_client = TelegramClient(f'{chat_id}_scraper', api_id, api_hash)

    try:
        await user_client.connect()

        # Send the code request
        await user_client.send_code_request(phone_number)
        await conv.send_message("An OTP has been sent to your phone. Please enter the OTP in the format: `1 2 3 4 5 6` (with spaces between each number).")

        otp_code = (await conv.get_response()).text.strip()
        otp_code = ''.join(otp_code.split())  # Remove any spaces from the input

        # Sign in using the OTP code
        await user_client.sign_in(phone_number, otp_code)
        await conv.send_message("Login successful! You can now use /scrape_and_add.")
    except SessionPasswordNeededError:
        # Two-factor authentication required
        await conv.send_message("Two-factor authentication is enabled on your account. Please enter your password:")

        password = (await conv.get_response()).text.strip()

        await user_client.sign_in(password=password)
        await conv.send_message("Login successful with 2FA! You can now use /scrape_and_add.")
    except AuthTokenInvalidError:
        logger.error('Invalid bot token provided.')
        await conv.send_message('The bot token you provided is invalid. Please verify and try again.')
    except ApiIdInvalidError:
        logger.error('Invalid API ID or API Hash provided.')
        await conv.send_message('The API ID or API Hash you provided is invalid. Please verify and try again.')
    except Exception as e:
        error_msg = f'An unexpected error occurred during OTP process: {e}'
        logger.error(error_msg)
        await conv.send_message(error_msg)
    finally:
        await user_client.disconnect()

@bot_client.on(events.NewMessage(pattern='/scrape_and_add'))
async def scrape_and_add(event):
    """Scrape users from a channel and add them to a group using the credentials set by the user."""
    global user_sessions

    chat_id = event.chat_id

    if chat_id not in user_sessions:
        await event.reply("Please set your credentials first using /set_credentials.")
        return

    user_session = user_sessions[chat_id]
    api_id = user_session['api_id']
    api_hash = user_session['api_hash']
    phone_number = user_session['phone_number']

    # Create a new client for the user session
    user_client = TelegramClient(f'{chat_id}_scraper', api_id, api_hash)

    try:
        # Attempt to start the user client
        await user_client.start(phone=phone_number)

        # User inputs for source channel and target group
        async with bot_client.conversation(chat_id, timeout=300) as conv:
            await conv.send_message("Please enter the `source channel` (from where to scrape users):")
            source_channel = (await conv.get_response()).text.strip()

            await conv.send_message("Please enter the `target group` (where to add users):")
            target_group = (await conv.get_response()).text.strip()

            # Scrape users and add them to the group
            users = await scrape_users(user_client, source_channel, event)
            await add_users_to_group(user_client, target_group, users, event)

            await conv.send_message("Completed adding users to the group.")

    except AuthTokenInvalidError:
        logger.error('Invalid bot token provided.')
        await event.reply('The bot token you provided is invalid. Please verify and try again.')
    except ApiIdInvalidError:
        logger.error('Invalid API ID or API Hash provided.')
        await event.reply('The API ID or API Hash you provided is invalid. Please verify and try again.')
    except Exception as e:
        error_msg = f'An unexpected error occurred: {e}'
        logger.error(error_msg)
        await event.reply(error_msg)
    finally:
        await user_client.disconnect()

@bot_client.on(events.NewMessage(pattern='/stop'))
async def stop(event):
    """Stop the current scraping and adding operation."""
    global stop_commands

    chat_id = event.chat_id
    stop_commands.add(chat_id)
    await event.reply("Operation stopped. You can start a new operation using /scrape_and_add.")
    raise events.StopPropagation

# Start the bot client
with bot_client:
    bot_client.run_until_disconnected()
