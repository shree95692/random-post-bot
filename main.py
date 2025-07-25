from pyrogram import Client
import asyncio
import random
import json
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# === BOT CONFIG ===
API_ID = 25424751
API_HASH = "eecb6d1f5c01c2f54e5939827f30a19f"
BOT_TOKEN = "8381754208:AAHO60W1yDa6hUMIsGxYjf_u2T8V-fJ4D6I"

PRIVATE_CHANNEL_LINK = "https://t.me/+GEZvmdljbjNkZjk1"  # Your private channel (invite link)
PUBLIC_CHANNEL_USERNAME = "@ARPmovie"  # Your public channel username

POSTS_PER_BATCH = 10
TIMEZONE = pytz.timezone("Asia/Kolkata")

client = Client("auto_post_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

POSTED_FILE = "posted.json"


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
    async for msg in client.get_chat_history(PRIVATE_CHANNEL_LINK, limit=0):
        if msg.text or msg.photo or msg.video or msg.document:
            all_msgs.append(msg)
    return all_msgs


async def post_random_messages():
    print(f"[{datetime.now()}] ⏳ Running scheduled post job...")
    posted_data = load_posted()
    posted_ids = [tuple(x) for x in posted_data.get("posted", [])]

    all_msgs = await get_all_messages()
    all_ids = [(msg.chat.id, msg.message_id) for msg in all_msgs]

    remaining = [msg for msg in all_msgs if (msg.chat.id, msg.message_id) not in posted_ids]

    if not remaining:
        print("✅ All posts have been sent once. Resetting cycle.")
        posted_data["posted"] = []
        remaining = all_msgs

    selected = random.sample(remaining, min(POSTS_PER_BATCH, len(remaining)))

    for msg in selected:
        try:
            await client.copy_message(
                chat_id=PUBLIC_CHANNEL_USERNAME,
                from_chat_id=msg.chat.id,
                message_id=msg.message_id
            )
            posted_data["posted"].append([msg.chat.id, msg.message_id])
            print(f"✅ Posted message {msg.message_id}")
        except Exception as e:
            print(f"❌ Failed to post message {msg.message_id}: {e}")

    save_posted(posted_data)


async def main():
    await client.start()
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Schedule jobs at 10:00 AM and 11:00 PM IST
    scheduler.add_job(post_random_messages, "cron", hour=10, minute=0)
    scheduler.add_job(post_random_messages, "cron", hour=23, minute=0)

    scheduler.start()
    print("🤖 Bot is running... Press Ctrl+C to stop.")
    await asyncio.Event().wait()


client.run(main())
