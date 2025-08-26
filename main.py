from pyrogram import Client, filters
import asyncio
import random
import json
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from keep_alive import keep_alive  # Keep alive for Render/Replit

# === BOT CONFIG (Env me sirf API, HASH, TOKEN) ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

POSTS_PER_BATCH = int(os.getenv("POSTS_PER_BATCH", 10))  # Default 10
TIMEZONE = pytz.timezone("Asia/Kolkata")

client = Client("auto_post_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
POSTED_FILE = "posted.json"
CONFIG_FILE = "config.json"


# ===================== Helper Functions =====================
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return json.load(f)
    return {"posted": []}


def save_posted(data):
    with open(POSTED_FILE, "w") as f:
        json.dump(data, f)


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"private": None, "public": None}


def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)


config = load_config()


async def get_all_messages():
    all_msgs = []
    if not config["private"]:
        print("❌ Private channel not set yet!")
        return []
    async for msg in client.get_chat_history(config["private"], limit=0):
        if msg.text or msg.photo or msg.video or msg.document:
            all_msgs.append(msg)
    return all_msgs


async def post_random_messages():
    if not config["private"] or not config["public"]:
        print("⚠️ Channels not set yet. Skipping post.")
        return

    print(f"[{datetime.now()}] ⏳ Running scheduled post job...")
    posted_data = load_posted()
    posted_ids = [tuple(x) for x in posted_data.get("posted", [])]

    all_msgs = await get_all_messages()
    remaining = [msg for msg in all_msgs if (msg.chat.id, msg.message_id) not in posted_ids]

    if not remaining:
        print("✅ All posts sent once. Resetting cycle.")
        posted_data["posted"] = []
        remaining = all_msgs

    if not remaining:
        print("⚠️ No messages found in private channel.")
        return

    selected = random.sample(remaining, min(POSTS_PER_BATCH, len(remaining)))

    for msg in selected:
        try:
            await client.copy_message(
                chat_id=config["public"],
                from_chat_id=msg.chat.id,
                message_id=msg.message_id
            )
            posted_data["posted"].append([msg.chat.id, msg.message_id])
            print(f"✅ Posted message {msg.message_id}")
        except Exception as e:
            print(f"❌ Failed to post message {msg.message_id}: {e}")

    save_posted(posted_data)


# ===================== Commands =====================
@client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "✅ Bot chal raha hai!\n\n"
        "⏰ Scheduled posts: 10:00 AM & 11:00 PM IST\n"
        "📡 Source: Private channel se random posts.\n\n"
        "👉 Setup ke liye dono channels se ek ek post forward karo."
    )


@client.on_message(filters.command("postnow") & filters.private)
async def postnow_command(client, message):
    await message.reply_text("⏳ Abhi random posts bheje ja rahe hain...")
    await post_random_messages()


# ===================== Channel Setup by Forward =====================
@client.on_message(filters.private & filters.forwarded)
async def catch_forwarded(client, message):
    global config
    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
        title = message.forward_from_chat.title

        if config["private"] is None:
            config["private"] = chat_id
            save_config(config)
            await message.reply_text(f"✅ Private channel set: {chat_id} ({title})")
        elif config["public"] is None:
            config["public"] = chat_id
            save_config(config)
            await message.reply_text(f"✅ Public channel set: {chat_id} ({title})")
        else:
            await message.reply_text("⚠️ Dono channels already set ho chuke hain. Agar reset karna hai to `config.json` delete karo.")


@client.on_message(filters.command("done") & filters.private)
async def done_command(client, message):
    if config["private"] and config["public"]:
        await message.reply_text(
            f"✅ Channels connected successfully!\n\n"
            f"Private: {config['private']}\n"
            f"Public: {config['public']}"
        )
    else:
        await message.reply_text("⚠️ Abhi dono channels forward karke connect nahi huye.")


# ===================== Main =====================
async def main():
    keep_alive()  # Keep alive server
    await client.start()
    print("✅ Bot successfully started and scheduled jobs loaded!")

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(post_random_messages, "cron", hour=10, minute=0)
    scheduler.add_job(post_random_messages, "cron", hour=23, minute=0)
    scheduler.start()

    await asyncio.Event().wait()


client.run(main())
