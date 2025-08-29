from pyrogram import Client, filters
from pyrogram.types import Message
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

PRIVATE_CHANNEL_ID = -1002458215030
PUBLIC_CHANNEL_ID = -1002469220850

GITHUB_REPO = "shree95692/random-forward-db"
GITHUB_FILE = "posted.json"
GITHUB_PAT = os.getenv("GITHUB_PAT")

POSTS_PER_BATCH = int(os.getenv("POSTS_PER_BATCH", 10))
TIMEZONE = pytz.timezone("Asia/Kolkata")

ADMIN_ID = 5163916480

POSTED_FILE = "posted.json"

app = Client("scheduled_forward_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ===================== Alerts =====================
async def send_alert(text):
    try:
        await app.send_message(ADMIN_ID, f"⚠️ ALERT:\n{text}")
    except:
        print("❌ Failed to send alert to admin")

# ===================== GitHub Helpers =====================
@app.on_message(filters.command("update_from_github") & filters.private)
async def update_from_github_command(client, message: Message):
    await message.reply_text("🔄 GitHub se database restore ho raha hai...")
    try:
        restored_count = download_from_github()
        size = os.path.getsize(POSTED_FILE) if os.path.exists(POSTED_FILE) else 0
        txt = ""
        try:
            with open(POSTED_FILE, "r") as f:
                txt = f.read()
            data = json.loads(txt) if txt.strip() else {"all_posts": [], "forwarded": []}
        except:
            data = {"all_posts": [], "forwarded": []}
        preview = (txt[:800].replace("\n", "\\n")) if txt else "(empty)"
        await message.reply_text(
            f"✅ Database updated from GitHub.\n"
            f"Restored count(returned): {restored_count}\n"
            f"Local file size: {size} bytes\n"
            f"Total saved posts: {len(data.get('all_posts', []))}\n"
            f"Already forwarded: {len(data.get('forwarded', []))}\n\nPreview: {preview}"
        )
    except Exception as e:
        await message.reply_text(f"❌ Error during update: {e}")

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

    data = {
        "message": "Auto-backup posted.json",
        "content": b64_content,
        "branch": "main"
    }
    if sha:
        data["sha"] = sha

    r = requests.put(url, headers=headers, json=data)
    if r.status_code in [200, 201]:
        print("✅ Database backed up to GitHub")
    else:
        error_msg = f"❌ GitHub backup failed: {r.text}"
        print(error_msg)
        asyncio.create_task(send_alert(error_msg))

# ===================== Local DB =====================
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return json.load(f)
    return {"all_posts": [], "forwarded": []}

def save_posted(data):
    if not data.get("all_posts") and not data.get("forwarded"):
        print("⚠️ Empty DB, skipping GitHub backup.")
        return

    old_data = load_posted()

    merged = {
        "all_posts": list({tuple(x) for x in old_data.get("all_posts", []) + data.get("all_posts", [])}),
        "forwarded": list({tuple(x) for x in old_data.get("forwarded", []) + data.get("forwarded", [])})
    }

    merged["all_posts"] = [list(x) for x in merged["all_posts"]]
    merged["forwarded"] = [list(x) for x in merged["forwarded"]]

    with open(POSTED_FILE, "w") as f:
        json.dump(merged, f, separators=(",", ":"))

    upload_to_github()
    print("✅ DB merged & saved, total posts:", len(merged["all_posts"]))

# ===================== Event: New Post =====================
@app.on_message(filters.chat(PRIVATE_CHANNEL_ID))
async def save_new_post(client, message: Message):
    data = load_posted()
    post_key = [message.chat.id, message.id]
    if post_key not in data["all_posts"]:
        data["all_posts"].append(post_key)
        save_posted(data)
        print(f"💾 Saved new post {message.id}")

# ===================== Event: Deleted Post =====================
@app.on_deleted_messages()
async def handle_deleted_messages(client, messages):
    data = load_posted()
    changed = False
    for msg in messages:
        key = [msg.chat.id, msg.id]
        if key in data["all_posts"]:
            data["all_posts"].remove(key)
            changed = True
            print(f"❌ Removed deleted post {msg.id} from DB")
        if key in data["forwarded"]:
            data["forwarded"].remove(key)
    if changed:
        save_posted(data)

# ===================== Scheduled Forward =====================
async def forward_scheduled_posts(user_id=None):
    print(f"[{datetime.now()}] ⏳ Running scheduled forward job...")
    data = load_posted()
    all_posts = data["all_posts"]
    forwarded = data["forwarded"]
    remaining = [p for p in all_posts if p not in forwarded]

    if not remaining:
        data["forwarded"] = []
        save_posted(data)
        remaining = all_posts

    selected = random.sample(remaining, min(POSTS_PER_BATCH, len(remaining)))

    for chat_id, msg_id in selected:
        try:
            await app.copy_message(PUBLIC_CHANNEL_ID, chat_id, msg_id)
            data["forwarded"].append([chat_id, msg_id])
            print(f"✅ Forwarded message {msg_id}")
        except Exception as e:
            await send_alert(f"❌ Failed to forward {msg_id}: {e}")
            if user_id:
                try: await app.send_message(user_id, f"❌ Failed to forward {msg_id}: {e}")
                except: pass

    save_posted(data)

# ===================== Commands =====================
from pyrogram.types import Message

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    await message.reply_text(
        f"✅ Bot chal raha hai!\n"
        f"⏰ Scheduled: {POSTS_PER_BATCH} posts at 10:00 AM & 11:00 PM IST\n"
        f"📡 Source: Private channel ke naye posts ko schedule pe forward karega."
    )

@app.on_message(filters.command("postnow") & filters.private)
async def postnow_command(client, message: Message):
    await message.reply_text("⏳ Abhi random posts forward ho rahe hain...")
    await forward_scheduled_posts(user_id=message.from_user.id)
    await message.reply_text("✅ Posts forward ho gaye!")

@app.on_message(filters.command("test") & filters.private)
async def test_command(client, message: Message):
    data = load_posted()
    await message.reply_text(
        f"📊 Database Status:\n"
        f"Total saved posts: {len(data['all_posts'])}\n"
        f"Already forwarded: {len(data['forwarded'])}\n"
        f"Remaining: {len([p for p in data['all_posts'] if p not in data['forwarded']])}"
    )

# ===================== New Command: Update from GitHub =====================
@app.on_message(filters.command("update_from_github") & filters.private)
async def update_from_github_command(client, message: Message):
    await message.reply_text("🔄 GitHub se database restore ho raha hai...")
    try:
        download_from_github()  # Tumhara existing restore function call
        await message.reply_text("✅ Database successfully restored from GitHub!")
    except Exception as e:
        await message.reply_text(f"❌ Restore failed: {e}")

# ===================== Main =====================
async def main():
    keep_alive()
    download_from_github()
    await app.start()
    print("✅ Bot started and scheduler loaded!")

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=10, minute=0)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=23, minute=0)
    scheduler.start()

    await asyncio.Event().wait()

app.run(main())
