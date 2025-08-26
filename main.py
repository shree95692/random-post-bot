from pyrogram import Client, filters
import asyncio
import random
import json
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from keep_alive import keep_alive  # Keep alive system for Replit/Render

# === BOT CONFIG (Environment Variables) ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

PRIVATE_CHANNEL_LINK = os.getenv("PRIVATE_CHANNEL_LINK")  # Example: https://t.me/+AbCdEfGhIjKlMnZp
PUBLIC_CHANNEL_USERNAME = os.getenv("PUBLIC_CHANNEL_USERNAME")  # Example: @ARPmovie

POSTS_PER_BATCH = int(os.getenv("POSTS_PER_BATCH", 10))  # Default 10
TIMEZONE = pytz.timezone("Asia/Kolkata")

client = Client("auto_post_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
POSTED_FILE = "posted.json"


# ===================== Helper Functions =====================
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return json.load(f)
    return {"posted": []}


def save_posted(data):
    with open(POSTED_FILE, "w") as f:
        json.dump(data, f)


async def get_all_messages():
    all_msgs = []
    chat = await client.join_chat(PRIVATE_CHANNEL_LINK)  # ✅ invite link se join
    async for msg in client.get_chat_history(chat.id, limit=0):
        if msg.text or msg.photo or msg.video or msg.document:
            all_msgs.append(msg)
    return all_msgs


async def post_random_messages():
    print(f"[{datetime.now()}] ⏳ Running post job...")
    posted_data = load_posted()
    posted_ids = [tuple(x) for x in posted_data.get("posted", [])]

    all_msgs = await get_all_messages()
    remaining = [msg for msg in all_msgs if (msg.chat.id, msg.id) not in posted_ids]

    if not remaining:
        print("✅ All posts sent once. Resetting cycle.")
        posted_data["posted"] = []
        remaining = all_msgs

    selected = random.sample(remaining, min(POSTS_PER_BATCH, len(remaining)))

    for msg in selected:
        try:
            await client.copy_message(
                chat_id=PUBLIC_CHANNEL_USERNAME,
                from_chat_id=msg.chat.id,
                message_id=msg.id
            )
            posted_data["posted"].append([msg.chat.id, msg.id])
            print(f"✅ Posted message {msg.id}")
        except Exception as e:
            print(f"❌ Failed to post message {msg.id}: {e}")

    save_posted(posted_data)


# ===================== Commands =====================
@client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "✅ Bot chal raha hai!\n"
        "⏰ Scheduled posts: 10:00 AM & 11:00 PM IST\n"
        "📡 Source: Private channel se random 10 posts."
    )


@client.on_message(filters.command("postnow") & filters.private)
async def postnow_command(client, message):
    await message.reply_text("⏳ Abhi 10 random posts bheje ja rahe hain...")
    await post_random_messages()
    await message.reply_text("✅ Posts bhej diye gaye!")


@client.on_message(filters.command("test") & filters.private)
async def test_command(client, message):
    try:
        chat = await client.join_chat(PRIVATE_CHANNEL_LINK)
        await message.reply_text(f"Channel mil gaya ✅\nID: {chat.id}\nTitle: {chat.title}")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


# ===================== Main =====================
async def main():
    keep_alive()
    await client.start()
    print("✅ Bot successfully started and jobs scheduled!")

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(post_random_messages, "cron", hour=10, minute=0)
    scheduler.add_job(post_random_messages, "cron", hour=23, minute=0)
    scheduler.start()

    await asyncio.Event().wait()


client.run(main())
