from pyrogram import Client, filters
import asyncio
import random
import json
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from keep_alive import keep_alive  # For Render/Replit keep alive

# === CONFIG ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Direct IDs (no need from env now)
PRIVATE_CHANNEL_ID = -1002458215030   # Private channel ID
PUBLIC_CHANNEL_ID = -1002469220850    # Public channel ID

POSTS_PER_BATCH = int(os.getenv("POSTS_PER_BATCH", 10))  # Default 10 if not set
TIMEZONE = pytz.timezone("Asia/Kolkata")

client = Client("scheduled_forward_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

POSTED_FILE = "posted.json"


# ===================== Helper Functions =====================
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return json.load(f)
    return {"all_posts": [], "forwarded": []}


def save_posted(data):
    with open(POSTED_FILE, "w") as f:
        json.dump(data, f)


# ===================== Event: Save new posts =====================
@client.on_message(filters.chat(PRIVATE_CHANNEL_ID))
async def save_new_post(client, message):
    data = load_posted()
    post_key = [message.chat.id, message.id]

    if post_key not in data["all_posts"]:
        data["all_posts"].append(post_key)
        save_posted(data)
        print(f"💾 Saved new post {message.id} for scheduling")


# ===================== Scheduled Forward =====================
async def forward_scheduled_posts():
    print(f"[{datetime.now()}] ⏳ Running scheduled forward job...")
    data = load_posted()

    all_posts = data["all_posts"]
    already_forwarded = data["forwarded"]

    remaining = [post for post in all_posts if post not in already_forwarded]

    if not remaining:
        print("✅ All posts forwarded once. Resetting cycle.")
        data["forwarded"] = []
        save_posted(data)
        remaining = all_posts

    if not remaining:
        print("⚠️ No posts available to forward yet.")
        return

    selected = random.sample(remaining, min(POSTS_PER_BATCH, len(remaining)))

    for chat_id, msg_id in selected:
        try:
            await client.copy_message(
                chat_id=PUBLIC_CHANNEL_ID,
                from_chat_id=chat_id,
                message_id=msg_id
            )
            data["forwarded"].append([chat_id, msg_id])
            print(f"✅ Forwarded message {msg_id}")
        except Exception as e:
            print(f"❌ Failed to forward message {msg_id}: {e}")

    save_posted(data)


# ===================== Commands =====================
@client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "✅ Bot chal raha hai!\n"
        f"⏰ Scheduled: {POSTS_PER_BATCH} posts at 10:00 AM & 11:00 PM IST\n"
        "📡 Source: Private channel me jo naye posts aaye, unko save karke schedule pe forward karega."
    )


@client.on_message(filters.command("postnow") & filters.private)
async def postnow_command(client, message):
    await message.reply_text("⏳ Abhi random posts forward ho rahe hain...")
    await forward_scheduled_posts()
    await message.reply_text("✅ Posts forward ho gaye!")


# ===================== Main =====================
async def main():
    keep_alive()  # keep alive for Render/Replit
    await client.start()
    print("✅ Bot started and scheduler loaded!")

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=10, minute=0)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=23, minute=0)
    scheduler.start()

    await asyncio.Event().wait()


client.run(main())
