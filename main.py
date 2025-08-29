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
PRIVATE_CHANNEL_ID = -1002458215030   # Private channel ID
PUBLIC_CHANNEL_ID = -1002469220850    # Public channel ID

# GitHub config
GITHUB_REPO = "shree95692/random-forward-db"
GITHUB_FILE = "posted.json"
GITHUB_PAT = os.getenv("GITHUB_PAT")  # PAT env me rakho

POSTS_PER_BATCH = int(os.getenv("POSTS_PER_BATCH", 10))
TIMEZONE = pytz.timezone("Asia/Kolkata")

# Admin alerts
ADMIN_ID = 5163916480  # tumhara Telegram ID

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
        print(f"🔎 Restore URL: {url} | Status: {r.status_code}")

        if r.status_code != 200:
            print(f"⚠️ GitHub restore failed: HTTP {r.status_code}")
            return

        if not r.text or not r.text.strip():
            print("⚠️ GitHub returned empty content.")
            return

        # Try parse remote JSON
        try:
            remote_data = json.loads(r.text)
        except Exception as e:
            # Show a bit of the content to help debug
            preview = (r.text[:200] + "...") if len(r.text) > 200 else r.text
            print(f"❌ Remote JSON invalid: {e}\nPreview: {preview}")
            return

        # Helper: normalize and validate list entries (expecting [chat_id, msg_id] style)
        def _normalize_list(lst, src_name="remote"):
            out = []
            if not isinstance(lst, list):
                print(f"⚠️ {src_name} value is not a list, skipping.")
                return out
            for item in lst:
                # Accept lists or tuples with at least two elements
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    out.append([item[0], item[1]])
                else:
                    print(f"⚠️ Skipping invalid entry in {src_name}: {item}")
            return out

        remote_all = _normalize_list(remote_data.get("all_posts", []), "remote.all_posts")
        remote_forwarded = _normalize_list(remote_data.get("forwarded", []), "remote.forwarded")

        # Load local data (if exists)
        local_data = {"all_posts": [], "forwarded": []}
        if os.path.exists(POSTED_FILE):
            try:
                with open(POSTED_FILE, "r") as f:
                    local_data = json.load(f)
                print(f"ℹ️ Local file found: {len(local_data.get('all_posts', []))} posts, "
                      f"{len(local_data.get('forwarded', []))} forwarded")
            except Exception as e:
                print(f"⚠️ Local JSON invalid/unreadable: {e}. Using empty local base.")

        local_all = _normalize_list(local_data.get("all_posts", []), "local.all_posts")
        local_forwarded = _normalize_list(local_data.get("forwarded", []), "local.forwarded")

        # Merge: remote first (priority), then local; use set to deduplicate
        merged_all_set = {tuple(x) for x in (remote_all + local_all)}
        merged_forwarded_set = {tuple(x) for x in (remote_forwarded + local_forwarded)}

        merged = {
            "all_posts": [list(x) for x in merged_all_set],
            "forwarded": [list(x) for x in merged_forwarded_set]
        }

        # If merge ended up empty but local had data, preserve local (safety)
        if not merged["all_posts"] and local_all:
            merged["all_posts"] = local_all
            print("ℹ️ Remote had no valid all_posts; preserving local all_posts.")
        if not merged["forwarded"] and local_forwarded:
            merged["forwarded"] = local_forwarded
            print("ℹ️ Remote had no valid forwarded; preserving local forwarded.")

        # Save final merged DB
        with open(POSTED_FILE, "w") as f:
            json.dump(merged, f, indent=4)

        print(f"✅ Database restored & merged: {len(merged['all_posts'])} posts, {len(merged['forwarded'])} forwarded")

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


# ===================== Local DB Helpers =====================
def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return json.load(f)
    return {"all_posts": [], "forwarded": []}


def save_posted(data):
    # Safety: agar data bilkul hi empty hai to backup mat karo
    if not data.get("all_posts") and not data.get("forwarded"):
        print("⚠️ Empty DB, skipping GitHub backup.")
        return

    # 🔹 Purana data load karo taaki merge ho jaye
    old_data = {}
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, "r") as f:
                old_data = json.load(f)
        except Exception as e:
            print("⚠️ Error reading old POSTED_FILE:", e)

    # 🔹 Merge karo old + new (duplicates hata ke)
    merged = {
        "all_posts": list({tuple(x) for x in old_data.get("all_posts", []) + data.get("all_posts", [])}),
        "forwarded": list({tuple(x) for x in old_data.get("forwarded", []) + data.get("forwarded", [])})
    }

    # 🔹 Set ko list of list me wapas convert karo
    merged["all_posts"] = [list(x) for x in merged["all_posts"]]
    merged["forwarded"] = [list(x) for x in merged["forwarded"]]

    # 🔹 Compact JSON format me save karo
    with open(POSTED_FILE, "w") as f:
        json.dump(merged, f, separators=(",", ":"))

    # 🔹 GitHub pe upload karo
    upload_to_github()
    print("✅ DB merged & saved, total posts:", len(merged["all_posts"]))

# ===================== Event: Save new posts =====================
@client.on_message(filters.chat(PRIVATE_CHANNEL_ID))
async def save_new_post(client, message):
    # Local + GitHub merged data load karo
    data = load_posted()

    post_key = [message.chat.id, message.id]

    if post_key not in data.get("all_posts", []):
        data["all_posts"].append(post_key)

        # Duplicate hatao (safety ke liye, tuple→list convert)
        data["all_posts"] = [list(x) for x in {tuple(p) for p in data.get("all_posts", [])}]
        data["forwarded"] = [list(x) for x in {tuple(p) for p in data.get("forwarded", [])}]

        save_posted(data)
        print(f"💾 Saved new post {message.id} for scheduling")
    else:
        print(f"ℹ️ Post {message.id} already saved, skipping.")

# ===================== Scheduled Forward =====================
async def forward_scheduled_posts(user_id=None):
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
            error_text = f"❌ Failed to forward message {msg_id}: {e}"
            print(error_text)
            await send_alert(error_text)
            if user_id:
                try:
                    await client.send_message(user_id, error_text)
                except:
                    pass

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
    await forward_scheduled_posts(user_id=message.from_user.id)
    await message.reply_text("✅ Posts forward ho gaye!")


@client.on_message(filters.command("test") & filters.private)
async def test_command(client, message):
    data = load_posted()
    await message.reply_text(
        f"📊 Database Status:\n"
        f"Total saved posts: {len(data['all_posts'])}\n"
        f"Already forwarded: {len(data['forwarded'])}\n"
        f"Remaining: {len([p for p in data['all_posts'] if p not in data['forwarded']])}"
    )


# ===================== Main =====================
async def main():
    keep_alive()
    download_from_github()
    await client.start()
    print("✅ Bot started and scheduler loaded!")

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=10, minute=0)
    scheduler.add_job(forward_scheduled_posts, "cron", hour=23, minute=0)
    scheduler.start()

    await asyncio.Event().wait()


client.run(main())
