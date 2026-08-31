import os
import asyncio
import tempfile
from pyrogram import Client, filters
from pyrogram.types import Message, InputMediaPhoto

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client(
    "screenshot_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

def time_to_seconds(t: str) -> float:
    parts = list(map(float, t.strip().split(":")))
    if len(parts) == 3:
        return parts[0]*3600 + parts[1]*60 + parts[2]
    elif len(parts) == 2:
        return parts[0]*60 + parts[1]
    return parts[0]

def seconds_to_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

@app.on_message(filters.command("start"))
async def start(_, message: Message):
    await message.reply(
        "**Personal Screenshot & Trim Bot**\n\n"
        "Send me a video, then use:\n\n"
        "• `/ss` → 8 screenshots\n"
        "• `/ss 12` → 12 screenshots (max 20)\n"
        "• `/trim 00:01:20 00:02:45` → Cut a clip\n\n"
        "Every screenshot will have the exact timestamp written on it."
    )

@app.on_message(filters.command("ss") & filters.reply)
async def ss_command(_, message: Message):
    replied = message.reply_to_message
    if not (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        return await message.reply("Please reply to a video.")

    args = message.command[1:]
    interval_seconds = None
    count = 8

    if len(args) == 2 and args[0].lower() == "every":
        try:
            interval_seconds = max(1, float(args[1]))
        except:
            return await message.reply("Usage: `/ss every 10` for one screenshot every 10 seconds.")
    elif len(args) == 1:
        try:
            count = max(1, min(int(args[0]), 100))
        except:
            count = 8

    status = await message.reply("Generating screenshots with timestamps...")

    with tempfile.TemporaryDirectory() as tmp:
        video_path = await replied.download(file_name=os.path.join(tmp, "video.mp4"))

        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path,
            stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        duration = float(stdout.decode().strip() or 0)

        if duration < 1:
            return await status.edit("Could not read video duration.")

        if interval_seconds:
            count = max(1, int(duration // interval_seconds))
            interval = interval_seconds
        else:
            interval = duration / (count + 1)

        screenshots = []

        for i in range(1, count + 1):
            t = interval * i
            timestamp = seconds_to_time(t)
            out_path = os.path.join(tmp, f"ss_{i:02d}.jpg")

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(t),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                out_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()

            if os.path.exists(out_path):
                screenshots.append(out_path)

        if not screenshots:
            return await status.edit("Failed to generate screenshots.")

        for i, path in enumerate(screenshots, start=1):
            t = interval * i
            timestamp = seconds_to_time(t)
            await message.reply_photo(path, caption=f"🕒 {timestamp}")

        await status.delete()

@app.on_message(filters.command("trim") & filters.reply)
async def trim_command(_, message: Message):
    replied = message.reply_to_message
    if not (replied.video or (replied.document and (replied.document.mime_type or "").startswith("video/"))):
        return await message.reply("Please reply to a video.")

    if len(message.command) < 3:
        return await message.reply(
            "Usage:\n`/trim START END`\n\n"
            "Examples:\n"
            "`/trim 00:01:20 00:02:45`\n"
            "`/trim 1:20 2:45`\n"
            "`/trim 80 165`"
        )

    try:
        start = time_to_seconds(message.command[1])
        end = time_to_seconds(message.command[2])
    except:
        return await message.reply("Invalid time format.")

    if end <= start:
        return await message.reply("End time must be greater than start time.")

    status = await message.reply(f"Trimming from {seconds_to_time(start)} → {seconds_to_time(end)}...")

    with tempfile.TemporaryDirectory() as tmp:
        video_path = await replied.download(file_name=os.path.join(tmp, "input.mp4"))
        output_path = os.path.join(tmp, "trimmed.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-to", str(end),
            "-i", video_path,
            "-c", "copy",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()

        if not os.path.exists(output_path):
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-to", str(end),
                "-i", video_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac",
                output_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await proc.wait()

        if os.path.exists(output_path):
            await message.reply_video(
                output_path,
                caption=f"Trimmed: {seconds_to_time(start)} → {seconds_to_time(end)}"
            )
            await status.delete()
        else:
            await status.edit("Failed to trim the video.")

@app.on_message(filters.video | filters.document)
async def on_video(_, message: Message):
    if message.document and not (message.document.mime_type or "").startswith("video/"):
        return
    await message.reply(
        "Video received!\n\n"
        "Reply with:\n"
        "• `/ss` or `/ss 10` → Screenshots\n"
        "• `/trim 00:01:20 00:02:45` → Cut clip"
    )

if __name__ == "__main__":
    print("Bot started...")
    app.run()
