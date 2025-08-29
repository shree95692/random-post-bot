from pyrogram import Client, filters
import asyncio
import random
import json
import os
import base64
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
import requests
from keep_alive import keep_alive  # For Render/Replit keep alive

# === CONFIG ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Direct IDs
PRIVATE_CHANNEL_ID = -1002458215030
PUBLIC_CHANNEL_ID = -1002469220850

# GitHub config
GITHUB_REPO = "shree95692/random-forward-db"
GITHUB_FILE = "posted.json"
GITHUB_PAT = os.getenv("GITHUB_PAT")

POSTS_PER_BATCH = int(os.getenv("POSTS_PER_BATCH", 10))
TIMEZONE = pytz.timezone("Asia/Kolkata")

# Admin alerts
ADMIN_ID = 5163916480

client = Client("scheduled_forward_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
POSTED_FILE = "posted.json"


# ===================== Alert Helper =====================
async def send_alert(text):
    try:
        await client.send_message(ADMIN_ID, f"⚠️ ALERT:\n{text}")
    except:
        print("❌ Failed to send alert to admin")


# ===================== GitHub Backup Helpers =====================
def download_from_github():
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"⚠️ GitHub restore failed: HTTP {r.status_code}")
            return
        if not r.text.strip():
            print("⚠️ GitHub returned empty content.")
            return
        try:
            remote_data = json.loads(r.text)
        except Exception as e:
            print(f"❌ Remote JSON invalid: {e}")
            return

        # Normalize lists
        def _normalize(lst):
            out = []
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        out.append([item[0], item[1]])
            return out

        remote_all = _normalize(remote_data.get("all_posts", []))
        remote_forwarded = _normalize(remote_data.get("forwarded", []))

        # Load local
        local_data = {"all_posts": [], "forwarded": []}
        if os.path.exists(POSTED_FILE):
            try:
                with open(POSTED_FILE, "r") as f:
                    local_data = json.load(f)
            except:
                print("⚠️ Local JSON invalid, using empty.")

        local_all = _normalize(local_data.get("all_posts", []))
        local_forwarded = _normalize(local_data.get("forwarded", []))

        # Merge: remote > local
        merged_all = {tuple(x) for x in (remote_all + local_all)}
        merged_forwarded = {tuple(x) for x in (remote_forwarded + local_forwarded)}

        merged = {
            "all_posts": [list(x) for x in merged_all],
            "forwarded": [list(x) for x in merged_forwarded]
        }

        # Save
        with open(POSTED_FILE, "w") as f:
            json.dump(merged, f, separators=(",", ":"))
        print(f"✅ Database restored & merged: {len(merged['all_posts'])} posts")
    except Exception as e:
        print(f"⚠️ Could not restore DB: {e}")


def upload_to_github():
    if not os.path.exists(POSTED_FILE):
        return
    with open(POSTED_FILE, "r") as f:
        content = f.read()
    b64_content = base64.b64encode(content.encode()).decode()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers = {"Authorization": f"token {GITHUB_PAT}"}
    sha = None
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        sha = r.json().get("sha")
    data = {"message": "Auto-backup posted.json", "content": b64_content, "branch": "main"}
    if sha:
        data["sha"] = sha
    r = requests.put(url, headers=headers, json=data)
    if r.status_code not in [200, 201]:
        error_msg = f"❌ GitHub backup failed: {r.text}"
        print(error_msg)
        asyncio.create_task(send_alert(error_msg))


# ===================== Local DB Helpers =====================
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return json.load(f)
    return {"all_posts": [], "forwarded": []}


def save_posted(data):
    # Safety
    if not data.get("all_posts") and not data.get("forwarded"):
        print("⚠️ Empty DB, skipping backup.")
        return

    # 🔹 Merge with GitHub latest
    old_data = {}
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}", timeout=10)
        if r.status_code == 200:
            old_data = json.loads(r.text)
    except:
        old_data = {}

    merged_all = {tuple(x) for x in old_data.get("all_posts", []) + data.get("all_posts", [])}
    merged_forwarded = {tuple(x) for x in old_data.get("forwarded", []) + data.get("forwarded", [])}

    merged = {
        "all_posts": [list(x) for x in merged_all],
        "forwarded": [list(x) for x in merged_forwarded]
    }

    # Save locally
    with open(POSTED_FILE, "w") as f:
        json.dump(merged, f, separators=(",", ":"))

    # Upload
    upload_to_github()
    print("✅ DB merged & saved, total posts:", len(merged["all_posts"]))


# ===================== Event: Save new posts =====================
@client.on_message(filters.chat(PRIVATE_CHANNEL_ID))
async def save_new_post(client, message):
    data = load_posted()
    post_key = [message.chat.id, message.id]
    if post_key not in data.get("all_posts", []):
        data["all_posts"].append(post_key)
        save_posted(data)
        print(f"💾 Saved new post {message.id}")


# ===================== Event: Delete posts =====================
@client.on_message_deleted()
async def deleted_post_handler(client, messages):
    data = load_posted()
    for message in messages:
        to_remove = [p for p in data.get("all_posts", []) if p[0] == message.chat.id and p[1] == message.id]
        if to_remove:
            for p in to_remove:
                data["all_posts"].remove(p)
            save_posted(data)
            print(f"🗑️ Deleted post {message.id} removed from DB")
async def deleted_post_handler(client, message):
    data = load_posted()
    to_remove = [p for p in data.get("all_posts", []) if p[0] == message.chat.id and p[1] == message.id]
    if to_remove:
        for p in to_remove:
            data["all_posts"].remove(p)
        save_posted(data)
        print(f"🗑️ Deleted post {message.id} removed from DB")


# ===================== Scheduled Forward =====================
async def forward_scheduled_posts(user_id=None):
    data = load_posted()
    remaining = [post for post in data["all_posts"] if post not in data["forwarded"]]
    if not remaining:
        data["forwarded"] = []
        save_posted(data)
        remaining = data["all_posts"]
    if not remaining:
        return
    selected = random.sample(remaining, min(POSTS_PER_BATCH, len(remaining)))
    for chat_id, msg_id in selected:
        try:
            await client.copy_message(PUBLIC_CHANNEL_ID, chat_id, msg_id)
            data["forwarded"].append([chat_id, msg_id])
        except Exception as e:
            await send_alert(f"Failed to forward {msg_id}: {e}")
    save_posted(data)


# ===================== Commands =====================
@client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        f"✅ Bot chal raha hai!\n⏰ Scheduled: {POSTS_PER_BATCH} posts at 10:00 & 23:00 IST\n"
        "📡 Source: Private channel posts will be forwarded automatically."
    )


@client.on_message(filters.command("postnow") & filters.private)
async def postnow_command(client, message):
    await message.reply_text("⏳ Forwarding posts now...")
    await forward_scheduled_posts(user_id=message.from_user.id)
    await message.reply_text("✅ Posts forwarded!")


@client.on_message(filters.command("test") & filters.private)
async def test_command(client, message):
    data = load_posted()
    remaining = [p for p in data["all_posts"] if p not in data["forwarded"]]
    await message.reply_text(
        f"📊 DB Status:\nTotal saved posts: {len(data['all_posts'])}\n"
        f"Already forwarded: {len(data['forwarded'])}\nRemaining: {len(remaining)}"
    )


# ===================== Main =====================
async def main():
    keep_alive()
    download_from_github()
    await client.start()
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=10, minute=0)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=23, minute=0)
    scheduler.start()
    await asyncio.Event().wait()


client.run(main())
