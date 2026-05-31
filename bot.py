import discord
import os
from discord.ext import commands
from discord import ui
from dotenv import load_dotenv
import json
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta
import requests
import signal
import sys
import re
import math
import random

load_dotenv()

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

counting_channels = {}
counting_games = {}
counting_caught_up = {}
user_levels = {}
tree_channels = {}
tree_data = {}
db = None

economy_settings = {}
economy_balances = {}

STATUS_CHANNEL_ID = 1487601977503252560

DATA_FILE_CHANNELS = "counting_channels.json"
DATA_FILE_GAMES = "counting_games.json"
DATA_FILE_LEVELS = "user_levels.json"
DATA_FILE_TREE_CHANNELS = "tree_channels.json"
DATA_FILE_TREE_DATA = "tree_data.json"
DATA_FILE_ECONOMY_SETTINGS = "economy_settings.json"
DATA_FILE_ECONOMY_BALANCES = "economy_balances.json"
DATA_FILE_REPORTS = "reports.json"
DATA_FILE_GAME_SETTINGS = "game_settings.json"
DB_FILE = 'db/mainDB.sqlite'

talked_recently = set()
levels_paused = False
cases = {}
message_case_map = {}
game_settings = {}
user_chickens = {}
roulette_games = {}

def validate_tree_name(name):
    
    if not name or len(name) < 1 or len(name) > 36:
        return False

    return bool(re.match(r'^[a-zA-Z0-9\-\'\s]+$', name))

def save_data():
    
    try:
        import json
        with open(DATA_FILE_CHANNELS, 'w') as f:
            json.dump(counting_channels, f, indent=2)
        with open(DATA_FILE_GAMES, 'w') as f:
            json.dump(counting_games, f, indent=2)
        save_tree_data()
        save_economy_data()
        save_reports()
        save_game_settings()
        print("Data saved successfully")
    except Exception as e:
        print("Error saving data: {}".format(e))

def save_tree_data():
    
    global tree_channels, tree_data
    try:
        import json
        with open(DATA_FILE_TREE_CHANNELS, 'w') as f:
            json.dump(tree_channels, f, indent=2)
        with open(DATA_FILE_TREE_DATA, 'w') as f:
            json.dump(tree_data, f, indent=2)
        print("Tree data saved successfully")
    except Exception as e:
        print("Error saving tree data: {}".format(e))

def load_tree_data():
    
    global tree_channels, tree_data
    try:
        import json
        if os.path.exists(DATA_FILE_TREE_CHANNELS):
            with open(DATA_FILE_TREE_CHANNELS, 'r') as f:
                loaded_channels = json.load(f)
                tree_channels = {int(k): v for k, v in loaded_channels.items()}
            print("Loaded {} tree channels".format(len(tree_channels)))
        else:
            print("Tree channels file {} not found".format(DATA_FILE_TREE_CHANNELS))
            tree_channels = {}
        
        if os.path.exists(DATA_FILE_TREE_DATA):
            with open(DATA_FILE_TREE_DATA, 'r') as f:
                tree_data = json.load(f)
            print("Loaded tree data for {} guilds".format(len(tree_data)))
        else:
            print("Tree data file {} not found".format(DATA_FILE_TREE_DATA))
            tree_data = {}
    except Exception as e:
        print("Error loading tree data: {}".format(e))
        tree_channels = {}
        tree_data = {}

def setup_database():
    
    os.makedirs('db', exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    cursor = db.cursor()
    

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bListRoles (
            guildID TEXT,
            roleName TEXT,
            roleID TEXT,
            PRIMARY KEY (guildID, roleID)
        )
    ''')
    

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS levelRoles (
            guildID TEXT,
            roleID TEXT,
            roleName TEXT,
            level INTEGER,
            PRIMARY KEY (guildID, roleID)
        )
    ''')
    
    db.commit()
    return db

def check_blacklisted_roles(member, guild_id):
    
    cursor = db.cursor()
    cursor.execute(f"SELECT roleName FROM bListRoles WHERE guildID='{guild_id}'")
    blacklisted_roles = [row[0] for row in cursor.fetchall()]
    
    return any(role.name in blacklisted_roles for role in member.roles)

def score_system_json(message):
    
    global levels_paused
    
    if levels_paused:
        return
        
    guild_id = message.guild.id
    user_id = message.author.id
    key = (guild_id, user_id)
    

    if key not in user_levels:
        user_levels[key] = {
            'username': message.author.name,
            'display_name': message.author.display_name,
            'user_id': user_id,
            'total_xp': 0,
            'level': 0,
            'rank': 0
        }
    

    user_data = user_levels[key]
    user_data['username'] = message.author.name
    user_data['display_name'] = message.author.display_name
    user_data['total_xp'] += 1
    

    if user_data['level'] == 0:
        xp_needed = 50
    else:
        xp_needed = int(50 * (1.45 ** user_data['level']))
    

    if user_data['total_xp'] >= xp_needed:
        user_data['level'] += 1
        

        embed = discord.Embed(
            title=message.author.display_name,
            description=f"**CONGRATS**\nYou are now level **{user_data['level']}**!!!",
            color=0x00AE86
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)
        asyncio.create_task(message.channel.send(embed=embed))
    

    update_ranks(guild_id)
    

    save_levels_data()

def update_ranks(guild_id):
    

    guild_users = {}
    for (gid, uid), data in user_levels.items():
        if gid == guild_id:
            guild_users[uid] = data
    

    sorted_users = sorted(guild_users.items(), key=lambda x: x[1]['total_xp'], reverse=True)
    
    for rank, (user_id, data) in enumerate(sorted_users, 1):
        data['rank'] = rank
        user_levels[(guild_id, user_id)] = data

def check_rank_roles(message, level):
    
    guild_id = str(message.guild.id)
    user_id = str(message.author.id)
    
    cursor = db.cursor()
    cursor.execute(
        f"SELECT * FROM levelRoles WHERE guildID='{guild_id}' AND level={level}"
    )
    role_data = cursor.fetchone()
    
    if role_data:
        guild_id, role_id, role_name, role_level = role_data
        role = discord.utils.get(message.guild.roles, name=role_name)
        
        if role and role not in message.author.roles:
            asyncio.create_task(message.author.add_roles(role))

async def remove_from_cooldown(user_id):
    
    await asyncio.sleep(4)
    talked_recently.discard(user_id)

def save_levels_data():
    
    try:
        import json

        json_data = {}
        for (guild_id, user_id), data in user_levels.items():
            key = f"{guild_id}_{user_id}"
            json_data[key] = data
        
        with open(DATA_FILE_LEVELS, 'w') as f:
            json.dump(json_data, f, indent=2)
        print("Levels data saved successfully")
    except Exception as e:
        print("Error saving levels data: {}".format(e))

def load_levels_data():
    
    global user_levels
    try:
        import json
        if os.path.exists(DATA_FILE_LEVELS):
            with open(DATA_FILE_LEVELS, 'r') as f:
                json_data = json.load(f)
            

            user_levels = {}
            for key, data in json_data.items():
                guild_id, user_id = key.split('_')
                user_levels[(int(guild_id), int(user_id))] = data
            
            print("Loaded levels data for {} users".format(len(user_levels)))
        else:
            print("Levels data file {} not found".format(DATA_FILE_LEVELS))
            user_levels = {}
    except Exception as e:
        print("Error loading levels data: {}".format(e))
        user_levels = {}

    
def load_data():
    
    global counting_channels, counting_games, user_levels
    try:
        import json
        print("Looking for data files: {}, {}".format(DATA_FILE_CHANNELS, DATA_FILE_GAMES))
        
        if os.path.exists(DATA_FILE_CHANNELS):
            with open(DATA_FILE_CHANNELS, 'r') as f:
                loaded_channels = json.load(f)

                counting_channels = {int(k): v for k, v in loaded_channels.items()}
            print("Loaded {} registered channels: {}".format(len(counting_channels), list(counting_channels.keys())))
        else:
            print("Channel data file {} not found".format(DATA_FILE_CHANNELS))
        
        if os.path.exists(DATA_FILE_GAMES):
            with open(DATA_FILE_GAMES, 'r') as f:
                loaded_games = json.load(f)

                counting_games = {int(k): v for k, v in loaded_games.items()}
            print("Loaded game data for {} channels: {}".format(len(counting_games), list(counting_games.keys())))
        else:
            print("Game data file {} not found".format(DATA_FILE_GAMES))
        

        load_tree_data()
        

        load_levels_data()
        
        load_economy_data()
        
        load_reports()
        load_game_settings()
            
        print("Final state - Channels: {}, Games: {}".format(counting_channels, counting_games))
    except Exception as e:
        print("Error loading data: {}".format(e))
        counting_channels = {}
        counting_games = {}
        user_levels = {}

def save_economy_data():
    global economy_settings, economy_balances
    try:
        import json
        with open(DATA_FILE_ECONOMY_SETTINGS, 'w') as f:
            json.dump(economy_settings, f, indent=2)
        with open(DATA_FILE_ECONOMY_BALANCES, 'w') as f:
            json.dump(economy_balances, f, indent=2)
        print("Economy data saved successfully")
    except Exception as e:
        print("Error saving economy data: {}".format(e))

def load_economy_data():
    global economy_settings, economy_balances
    try:
        import json
        if os.path.exists(DATA_FILE_ECONOMY_SETTINGS):
            with open(DATA_FILE_ECONOMY_SETTINGS, 'r') as f:
                economy_settings = json.load(f)
            print("Loaded economy settings for {} guilds".format(len(economy_settings)))
        else:
            print("Economy settings file not found")
            economy_settings = {}
        
        if os.path.exists(DATA_FILE_ECONOMY_BALANCES):
            with open(DATA_FILE_ECONOMY_BALANCES, 'r') as f:
                economy_balances = json.load(f)
            print("Loaded economy balances for {} users".format(len(economy_balances)))
        else:
            print("Economy balances file not found")
            economy_balances = {}
    except Exception as e:
        print("Error loading economy data: {}".format(e))
        economy_settings = {}
        economy_balances = {}

def get_economy_settings(guild_id):
    guild_id_str = str(guild_id)
    if guild_id_str not in economy_settings:
        economy_settings[guild_id_str] = {
            "currency": "$",
            "start_balance": 0,
            "max_cash": 0,
            "max_bank": 0,
            "audit_channel": None,
            "role_incomes": [],
            "cooldowns": {
                "work": 30,
                "crime": 30,
                "rob": 30,
                "blackjack": 30
            },
            "crime_settings": {
                "fail_rate": 50,  # percentage
                "fine_type": "fixed",  # "fixed" or "percent"
                "fine_min": 10,
                "fine_max": 100
            },
            "work_settings": {
                "payout_min": 10,
                "payout_max": 100
            },
            "chat_money": {
                "enabled": False,
                "min_amount": 1,
                "max_amount": 10,
                "enabled_channels": []
            }
        }
    return economy_settings[guild_id_str]

def get_user_balance(guild_id, user_id):
    key = "{}_{}".format(guild_id, user_id)
    if key not in economy_balances:
        settings = get_economy_settings(guild_id)
        economy_balances[key] = {
            "cash": settings["start_balance"],
            "bank": 0
        }
    return economy_balances[key]

def save_user_balance(guild_id, user_id):
    save_economy_data()

def format_money(guild_id, amount):
    settings = get_economy_settings(guild_id)
    return "{}{}".format(settings["currency"], amount)

def get_game_settings():
    global game_settings
    if not game_settings:
        game_settings = {
            "bet_limits": {
                "blackjack": {"min": 100, "max": None},
                "roulette": {"min": 100, "max": None},
                "higher-or-lower": {"min": 100, "max": None},
                "chicken-fight": {"min": 100, "max": None},
                "russian-roulette": {"min": 100, "max": None},
                "slot-machine": {"min": 100, "max": None}
            },
            "blackjack_decks": 3,
            "game_cooldown": {"usages": 4, "duration": 300},
            "slot_machine_symbols": [
                {"symbol": "🍒", "multiplier": 2},
                {"symbol": "🍋", "multiplier": 3},
                {"symbol": "🍊", "multiplier": 5},
                {"symbol": "🍇", "multiplier": 8},
                {"symbol": "💎", "multiplier": 15},
                {"symbol": "7️⃣", "multiplier": 25}
            ],
            "chicken_fight_winrate": {"start": 50, "max": 70}
        }
    return game_settings

def save_game_settings():
    global game_settings
    try:
        import json
        with open(DATA_FILE_GAME_SETTINGS, 'w') as f:
            json.dump(game_settings, f, indent=2)
        print("Game settings saved successfully")
    except Exception as e:
        print("Error saving game settings: {}".format(e))

def load_game_settings():
    global game_settings
    try:
        import json
        if os.path.exists(DATA_FILE_GAME_SETTINGS):
            with open(DATA_FILE_GAME_SETTINGS, 'r') as f:
                loaded = json.load(f)
            game_settings = loaded
            print("Loaded game settings")
        else:
            get_game_settings()
    except Exception as e:
        print("Error loading game settings: {}".format(e))
        get_game_settings()

def save_reports():
    global cases, message_case_map
    try:
        import json
        with open(DATA_FILE_REPORTS, 'w') as f:
            json.dump({"cases": cases, "message_case_map": message_case_map}, f, indent=2)
        print("Reports saved successfully")
    except Exception as e:
        print("Error saving reports: {}".format(e))

def load_reports():
    global cases, message_case_map
    try:
        import json
        if os.path.exists(DATA_FILE_REPORTS):
            with open(DATA_FILE_REPORTS, 'r') as f:
                data = json.load(f)
            cases = data.get("cases", {})
            message_case_map = data.get("message_case_map", {})
            open_count = sum(1 for c in cases.values() if c.get("status") == "open")
            print("Loaded {} cases ({} open)".format(len(cases), open_count))
        else:
            cases = {}
            message_case_map = {}
    except Exception as e:
        print("Error loading reports: {}".format(e))
        cases = {}
        message_case_map = {}

def get_next_case_number():
    open_numbers = set()
    for case_num in cases:
        if cases[case_num].get("status") == "open":
            try:
                open_numbers.add(int(case_num))
            except (ValueError, TypeError):
                pass
    n = 1
    while n in open_numbers:
        n += 1
    return n

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} servers')
    
    global db
    db = setup_database()
    load_data()
    
    print("Re-registering persistent views...")
    for guild_id, tree in tree_data.items():
        msg_ids = tree.get("tree_view_messages", [])
        for msg_id in msg_ids:
            view = TreeView(tree, None)
            bot.add_view(view, message_id=msg_id)
            print("  Registered tree view for message {}".format(msg_id))
    
    try:
        synced = await bot.tree.sync()
        print("Synced {} slash command(s)".format(len(synced)))
    except Exception as e:
        print("Failed to sync commands: {}".format(e))
    

    try:
        status_channel = bot.get_channel(STATUS_CHANNEL_ID)
        print("Status channel lookup result: {}".format(status_channel))
        if status_channel:
            await status_channel.send("Bot started", silent=True)
            print("Sent startup message to channel {}".format(STATUS_CHANNEL_ID))
        else:
            print("Could not find status channel {}".format(STATUS_CHANNEL_ID))

            for guild in bot.guilds:
                print("Checking guild: {} (ID: {})".format(guild.name, guild.id))
                for channel in guild.text_channels:
                    if channel.id == STATUS_CHANNEL_ID:
                        print("Found channel in guild {}: {}".format(guild.name, channel.name))
                        break
    except Exception as e:
        print("Error sending startup message: {}".format(e))

    print("Bot ready!")

@bot.tree.command(name="hello", description="Get a friendly greeting")
async def hello(interaction: discord.Interaction):
    
    await interaction.response.send_message(f'whats up why you ping me')

@bot.tree.command(name="purge-all", description="Delete ALL messages in the current channel")
async def purge_all(interaction: discord.Interaction):
    
    

    required_roles = [
        1334353078564163624, 1436499751825576020, 1467687379262378087,
        1335076929342144603, 1334347690338947163, 1381402498786660472
    ]
    
    user_roles = [role.id for role in interaction.user.roles]
    has_permission = any(role_id in user_roles for role_id in required_roles)
    
    if not has_permission:

        error_embed = discord.Embed(
            title="Oops..",
            description="You don't have elevated permissions to run this.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=error_embed)
        return
    
    try:

        await interaction.response.send_message("Purging all messages in this channel...", ephemeral=True)
        

        deleted_messages = await interaction.channel.purge(limit=None)
        

        confirm_embed = discord.Embed(
            title="Channel Purged",
            description=f"Successfully deleted {len(deleted_messages) - 1} messages from this channel.",
            color=discord.Color.green()
        )
        confirm_embed.set_footer(text=f"Requested by {interaction.user.name}")
        
        await interaction.channel.send(embed=confirm_embed, delete_after=10)
        
    except discord.Forbidden:
        await interaction.edit_original_response(content="I don't have permission to delete messages in this channel!")
    except Exception as e:
        await interaction.edit_original_response(content=f"An error occurred: {str(e)}")

@bot.tree.command(name="purge", description="Delete a specified number of messages in the current channel")
@discord.app_commands.describe(amount="Number of messages to delete (1-1000)")
async def purge(interaction: discord.Interaction, amount: int):
    
    

    blacklisted_users = [1119752421317558394]
    if interaction.user.id in blacklisted_users:
        error_embed = discord.Embed(
            title="Access Denied",
            description="You are not allowed to use this command.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=error_embed)
        return
    

    required_roles = [
        1334353078564163624, 1436499751825576020, 1467687379262378087,
        1335076929342144603, 1334347690338947163, 1381402498786660472
    ]
    
    user_roles = [role.id for role in interaction.user.roles]
    has_permission = any(role_id in user_roles for role_id in required_roles)
    
    if not has_permission:

        error_embed = discord.Embed(
            title="Oops..",
            description="You don't have elevated permissions to run this.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=error_embed)
        return
    

    if amount < 1 or amount > 1000:
        await interaction.response.send_message("Please specify a number between 1 and 1000!", ephemeral=True)
        return
    
    try:

        await interaction.response.send_message(f"Purging {amount} messages...", ephemeral=True)
        

        deleted_messages = await interaction.channel.purge(limit=amount + 1)
        

        confirm_embed = discord.Embed(
            title="Messages Purged",
            description=f"Successfully deleted {len(deleted_messages) - 1} messages.",
            color=discord.Color.green()
        )
        confirm_embed.set_footer(text=f"Requested by {interaction.user.name}")
        
        await interaction.channel.send(embed=confirm_embed, delete_after=5)
        
    except discord.Forbidden:
        await interaction.edit_original_response(content="I don't have permission to delete messages in this channel!")
    except Exception as e:
        await interaction.edit_original_response(content=f"An error occurred: {str(e)}")

@bot.tree.command(name="msg_sender", description="Get information about a message by its ID")
@discord.app_commands.describe(message_id="The ID of the message to look up")
async def msg_sender(interaction: discord.Interaction, message_id: str):
    
    

    required_roles = [
        1334353078564163624, 1436499751825576020, 1467687379262378087,
        1335076929342144603, 1334347690338947163, 1381402498786660472
    ]
    
    user_roles = [role.id for role in interaction.user.roles]
    has_permission = any(role_id in user_roles for role_id in required_roles)
    
    if not has_permission:

        error_embed = discord.Embed(
            title="Oops..",
            description="You don't have elevated permissions to run this.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=error_embed, ephemeral=True)
        return
    
    try:

        msg_id = int(message_id)
        

        scanning_embed = discord.Embed(
            title="Scanning...",
            description="Scanning all channels for message...",
            color=discord.Color.yellow()
        )
        await interaction.response.send_message(embed=scanning_embed)
        scanning_message = await interaction.original_response()
        

        found_message = None
        channel_count = 0
        scanned_channels = []
        

        for channel in interaction.guild.text_channels:
            try:
                channel_count += 1
                scanned_channels.append(f"#{channel.name} (ID: {channel.id})")
                message = await channel.fetch_message(msg_id)
                found_message = message
                break
            except discord.NotFound:
                continue
            except discord.Forbidden:
                continue
        

        if not found_message:
            for channel in interaction.guild.channels:
                try:

                    if isinstance(channel, discord.TextChannel):
                        channel_count += 1
                        scanned_channels.append(f"#{channel.name} (ID: {channel.id})")
                        message = await channel.fetch_message(msg_id)
                        found_message = message
                        break
                except discord.NotFound:
                    continue
                except discord.Forbidden:
                    continue
                except Exception:
                    continue
        
        await scanning_message.delete()
        
        if found_message:

            embed = discord.Embed(
                title="Message Information",
                color=discord.Color.green()
            )
            embed.add_field(name="User", value=f"{found_message.author.mention} sent this message!", inline=False)
            embed.add_field(name="Contents", value=found_message.content or "*No content*", inline=False)
            embed.add_field(name="Channel", value=f"<#{found_message.channel.id}> (ID: {found_message.channel.id})", inline=False)
            embed.add_field(name="Message ID", value=f"`{found_message.id}`", inline=False)
            embed.set_footer(text=f"Found in {channel_count} channels • Requested by {interaction.user.name}")
            

            await interaction.channel.send(embed=embed)
        else:

            embed = discord.Embed(
                title="Message Not Found",
                description=f"Message ID `{msg_id}` was not found in any of the {channel_count} accessible channels.",
                color=discord.Color.red()
            )
            embed.set_footer(text=f"Scanned {channel_count} channels • Requested by {interaction.user.name}")
            
            if scanned_channels:
                channels_text = "\n".join(scanned_channels[:20])
                if len(scanned_channels) > 20:
                    channels_text += f"\n... and {len(scanned_channels) - 20} more"
                embed.add_field(name="Scanned Channels", value=f"```{channels_text}```", inline=False)
            
            await interaction.channel.send(embed=embed)
        
    except ValueError:
        await interaction.response.send_message("Invalid message ID format!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="activity-counting", description="Manage counting activities")
@discord.app_commands.describe(
    action="The action to perform",
    number="The number to set as current count (only for set-count action)"
)
@discord.app_commands.choices(
    action=[
        discord.app_commands.Choice(name="register", value="register"),
        discord.app_commands.Choice(name="unregister", value="unregister"),
        discord.app_commands.Choice(name="start", value="start"),
        discord.app_commands.Choice(name="stop", value="stop"),
        discord.app_commands.Choice(name="set-count", value="set-count")
    ]
)
async def activity_counting(interaction: discord.Interaction, action: str, number: int = None):
    
    channel_id = interaction.channel.id
    

    required_roles = [1467889239512580261]
    user_roles = [role.id for role in interaction.user.roles]
    has_permission = any(role_id in user_roles for role_id in required_roles)
    
    if not has_permission:
        error_embed = discord.Embed(
            title="Oops..",
            description="You don't have elevated permissions to run this.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=error_embed, ephemeral=True)
        return
    
    if action == "register":
            if channel_id in counting_channels:
                error_embed = discord.Embed(
                    title="Channel Already Registered",
                    description="This channel is already registered as a counting channel!",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
                return
            
            counting_channels[channel_id] = True
            save_data()
            
            success_embed = discord.Embed(
                title="Channel Registered",
                description=f"This channel has been registered as a counting channel! Use `/activity counting start` to begin a game.",
                color=discord.Color.green()
            )
            success_embed.set_footer(text=f"Requested by {interaction.user.name}")
            await interaction.response.send_message(embed=success_embed)
            
    elif action == "unregister":
        if channel_id not in counting_channels:
            error_embed = discord.Embed(
                title="Channel Not Registered",
                description="This channel is not registered as a counting channel!",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        if channel_id in counting_games and counting_games[channel_id]["active"]:
            error_embed = discord.Embed(
                title="Game In Progress",
                description="You cannot unregister a channel while a counting game is running! Use `/activity-counting stop` first.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        del counting_channels[channel_id]
        save_data()
        
        success_embed = discord.Embed(
            title="Channel Unregistered",
            description="This channel has been unregistered as a counting channel.",
            color=discord.Color.green()
        )
        success_embed.set_footer(text=f"Requested by {interaction.user.name}")
        await interaction.response.send_message(embed=success_embed)
        
    elif action == "start":
        if channel_id not in counting_channels:
            error_embed = discord.Embed(
                title="Channel Not Registered",
                description="This channel is not registered as a counting channel! Use `/activity-counting register` first.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        if channel_id in counting_games and counting_games[channel_id]["active"]:
            error_embed = discord.Embed(
                title="Game Already Running",
                description="A counting game is already in progress in this channel!",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        counting_games[channel_id] = {"current_number": 0, "active": True, "last_user": None}
        save_data()
        
        start_embed = discord.Embed(
            title="Counting game started.",
            description="The first correct number is 1.",
            color=discord.Color.green()
        )
        start_embed.set_footer(text=f"Started by {interaction.user.name}")
        await interaction.response.send_message(embed=start_embed)
        
    elif action == "stop":
        if channel_id not in counting_games or not counting_games[channel_id]["active"]:
            error_embed = discord.Embed(
                title="No Game Running",
                description="There is no counting game running in this channel!",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        counting_games[channel_id]["active"] = False
        save_data()
        
        stop_embed = discord.Embed(
            title="Counting Game Stopped",
            description="The counting game has been stopped. You can start a new game with `/activity-counting start`.",
            color=discord.Color.red()
        )
        stop_embed.set_footer(text=f"Stopped by {interaction.user.name}")
        await interaction.response.send_message(embed=stop_embed)
        
    elif action == "set-count":
        if number is None:
            await interaction.response.send_message("Please provide a number to set!", ephemeral=True)
            return
        
        if channel_id not in counting_games or not counting_games[channel_id]["active"]:
            error_embed = discord.Embed(
                title="No Game Running",
                description="There is no counting game running in this channel!",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        if number < 0:
            await interaction.response.send_message("Number must be 0 or greater!", ephemeral=True)
            return
        
        counting_games[channel_id]["current_number"] = number
        counting_games[channel_id]["last_user"] = None
        save_data()
        
        set_embed = discord.Embed(
            title="Count updated.",
            description=f"Current count has been updated now to {number}. Continue the game as normal.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=set_embed)

@bot.tree.command(name="activity-levels", description="Manage level activities")
@discord.app_commands.describe(
    action="The action to perform",
    level="The level for role management (only for rlevel-add action)",
    role_name="The role name for role management (only for blacklist and rlevel actions)"
)
@discord.app_commands.choices(
    action=[
        discord.app_commands.Choice(name="rank", value="rank"),
        discord.app_commands.Choice(name="leaderboard", value="leaderboard"),
        discord.app_commands.Choice(name="blacklist-add", value="blacklist-add"),
        discord.app_commands.Choice(name="blacklist-remove", value="blacklist-remove"),
        discord.app_commands.Choice(name="rlevel-add", value="rlevel-add"),
        discord.app_commands.Choice(name="rlevel-remove", value="rlevel-remove"),
        discord.app_commands.Choice(name="reset-levels", value="reset-levels"),
        discord.app_commands.Choice(name="pause-global", value="pause-global"),
        discord.app_commands.Choice(name="resume-global", value="resume-global")
    ]
)
async def activity_levels(interaction: discord.Interaction, action: str, level: int = None, role_name: str = None):
    
    global levels_paused
    guild_id = interaction.guild.id
    

    if action in ["reset-levels", "pause-global", "resume-global"]:
        if interaction.user.id != 775397655576707103:
            await interaction.response.send_message("You must be VinnyPix to execute these commands!", ephemeral=True)
            return
        
        if action == "reset-levels":
            confirm_embed = discord.Embed(
                title="⚠️ Confirm Reset Levels",
                description="Are you sure you want to delete EVERYONE'S levels and XP in this server?\n\nReact with CHECKMARK or X.\n\nCHECKMARK = Deleted.\nX = Cancelled.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=confirm_embed)
            
            msg = await interaction.original_response()
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            
            def check(reaction, user):
                return user.id == interaction.user.id and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id
            
            try:
                reaction, user = await bot.wait_for("reaction_add", timeout=30.0, check=check)
                
                if str(reaction.emoji) == "✅":

                    keys_to_remove = []
                    for (gid, uid) in user_levels.keys():
                        if gid == guild_id:
                            keys_to_remove.append((gid, uid))
                    
                    for key in keys_to_remove:
                        del user_levels[key]
                    
                    save_levels_data()
                    
                    reset_embed = discord.Embed(
                        title="SUCCESS: Levels Reset",
                        description="All levels and XP have been deleted for this server.",
                        color=discord.Color.green()
                    )
                    await interaction.followup.send(embed=reset_embed)
                else:
                    cancel_embed = discord.Embed(
title="CANCELLED",
                        description="Level reset has been cancelled.",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=cancel_embed)
                    
            except asyncio.TimeoutError:
                timeout_embed = discord.Embed(
                    title="⏰ Timeout",
                    description="Level reset confirmation timed out.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=timeout_embed)
            except Exception as e:
                print("Error in reset-levels reaction handling: {}".format(e))
        
        elif action == "pause-global":
            if levels_paused:
                await interaction.response.send_message("Leveling is already paused!", ephemeral=True)
                return
            
            levels_paused = True
            pause_embed = discord.Embed(
                title="⏸️ Leveling Paused",
                description="Global leveling and XP gain has been paused.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=pause_embed)
        
        elif action == "resume-global":
            if not levels_paused:
                await interaction.response.send_message("Leveling is not currently paused!", ephemeral=True)
                return
            
            levels_paused = False
            resume_embed = discord.Embed(
                title="▶️ Leveling Resumed",
                description="Global leveling and XP gain has been resumed.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=resume_embed)
        
        return
    

    if action in ["blacklist-add", "blacklist-remove", "rlevel-add", "rlevel-remove"]:
        amari_mod_role = discord.utils.get(interaction.guild.roles, name="AmariMod")
        
        if not amari_mod_role:
            await interaction.response.send_message('Please make a role named "AmariMod" and assign it to yourself to be able to use this command.')
            return
        
        if amari_mod_role not in interaction.user.roles:
            await interaction.response.send_message("Sorry you don't have access to this command.")
            return
        
        if action == "blacklist-add":
            if not role_name:
                await interaction.response.send_message("Please provide a role name!")
                return
            
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            
            if not role:
                await interaction.response.send_message(f"No role found {role_name}. Remember it is case sensitive.")
                return
            
            cursor = db.cursor()
            try:
                cursor.execute(
                    "INSERT INTO bListRoles (guildID, roleName, roleID) VALUES (?, ?, ?)",
                    (str(guild_id), role.name, str(role.id))
                )
                db.commit()
                await interaction.response.send_message(f"{role_name} has been added to the points system blacklist.")
            except sqlite3.IntegrityError:
                await interaction.response.send_message(f"{role_name} is already blacklisted.")
        
        elif action == "blacklist-remove":
            if not role_name:
                await interaction.response.send_message("Please provide a role name!")
                return
            
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            
            if not role:
                await interaction.response.send_message(f"No role found {role_name}. Remember it is case sensitive.")
                return
            
            cursor = db.cursor()
            cursor.execute(
                f"DELETE FROM bListRoles WHERE guildID = {guild_id} AND roleID = {role.id}"
            )
            db.commit()
            await interaction.response.send_message(f"{role_name} has been removed from the blacklist.")
        
        elif action == "rlevel-add":
            if not level or not role_name:
                await interaction.response.send_message("Please provide both level and role name!")
                return
            
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            
            if not role:
                await interaction.response.send_message(f"No role found {role_name}")
                return
            
            cursor = db.cursor()
            cursor.execute(
                f"SELECT * FROM levelRoles WHERE guildID = {guild_id} AND roleID = {role.id}"
            )
            existing = cursor.fetchone()
            
            if not existing:
                cursor.execute(
                    "INSERT INTO levelRoles (guildID, roleID, roleName, level) VALUES (?, ?, ?, ?)",
                    (str(guild_id), str(role.id), role_name, level)
                )
                await interaction.response.send_message(f"{role_name} has been set for level {level}.")
            else:
                cursor.execute(
                    f"UPDATE levelRoles SET level = {level} WHERE guildID='{guild_id}' AND roleID='{role.id}'"
                )
                await interaction.response.send_message(f"{role_name} has been updated for level {level}.")
            
            db.commit()
        
        elif action == "rlevel-remove":
            if not role_name:
                await interaction.response.send_message("Please provide a role name!")
                return
            
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            
            if not role:
                await interaction.response.send_message(f"There is no role named {role_name}.")
                return
            
            cursor = db.cursor()
            cursor.execute(
                f"DELETE FROM levelRoles WHERE guildID = {guild_id} AND roleID = {role.id}"
            )
            db.commit()
            await interaction.response.send_message(f"{role_name} has been removed from rlevel.")
    

    elif action == "rank":
        member = interaction.user
        key = (guild_id, member.id)
        
        if key not in user_levels:
            await interaction.response.send_message("Sorry you don't have any points. Start chatting to earn them!")
            return
        
        user_data = user_levels[key]
        

        current_level = user_data['level']
        current_xp = user_data['total_xp']
        
        if current_level == 0:
            xp_needed = 50
        else:
            xp_needed = int(50 * (1.45 ** current_level))
        
        xp_remaining = xp_needed - current_xp
        
        if xp_remaining <= 0:
            progress_text = "Ready to level up!"
        else:
            progress_text = f"{xp_remaining} XP needed for next level"
        
        embed = discord.Embed(
            title=member.name,
            description=f"**Level:** {user_data['level']}\n**Exp:** {user_data['total_xp']}/{xp_needed}\n**Rank:** {user_data['rank']}\n**Progress:** {progress_text}",
            color=0x00AE86
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await interaction.response.send_message(embed=embed)
    
    elif action == "leaderboard":

        guild_users = []
        for (gid, uid), data in user_levels.items():
            if gid == guild_id:
                guild_users.append(data)
        

        guild_users.sort(key=lambda x: x['total_xp'], reverse=True)
        
        if not guild_users:
            lead_out = "Sorry there is no leaderboards yet. Start chatting!"
        else:
            leaderboard_lines = []
            for i, user_data in enumerate(guild_users[:10], 1):
                leaderboard_lines.append(f"{i}. {user_data['username']} - Level {user_data['level']} ({user_data['total_xp']} XP)")
            lead_out = "\n".join(leaderboard_lines)
        
        embed = discord.Embed(
            color=0x00AE86
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.add_field(
            name=f"Leaderboards for **{interaction.guild.name}**",
            value=lead_out,
            inline=True
        )
        
        await interaction.response.send_message(embed=embed)

class ReportModal(ui.Modal, title="Submit a Report"):
    report_type = ui.TextInput(label="Report Type", placeholder="Bug", default="Bug")
    bug_description = ui.TextInput(label="Bug Description", style=discord.TextStyle.paragraph, placeholder="Describe the bug...", required=True, max_length=1000)

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        submitter = self.interaction.user
        report_type = self.report_type.value
        bug_desc = self.bug_description.value
        
        case_num = get_next_case_number()
        case_num_str = str(case_num)
        
        cases[case_num_str] = {
            "submitter_id": submitter.id,
            "submitter_name": submitter.name,
            "report_type": report_type,
            "description": bug_desc,
            "status": "open"
        }
        
        embed = discord.Embed(
            title="**Case #{}**".format(case_num_str),
            color=discord.Color.orange()
        )
        embed.add_field(name="Submitter", value="`{}` (<@{}>)".format(submitter.name, submitter.id), inline=False)
        embed.add_field(name="Report Type", value=report_type, inline=False)
        embed.add_field(name="Description", value=bug_desc, inline=False)
        embed.set_footer(text="Reply with !resolve [message] to resolve this case")
        
        target_user_ids = [775397655576707103, 1417671348767035552]
        for user_id in target_user_ids:
            try:
                user = await bot.fetch_user(user_id)
                msg = await user.send(embed=embed)
                message_case_map[str(msg.id)] = case_num_str
            except Exception as e:
                print("Failed to send case {} to user {}: {}".format(case_num_str, user_id, e))
        
        save_reports()
        
        await interaction.response.send_message("Your report has been submitted as **Case #{}**!".format(case_num_str), ephemeral=True)

@bot.tree.command(name="report", description="Submit a bug report")
async def report(interaction: discord.Interaction):
    await interaction.response.send_modal(ReportModal(interaction))

def get_guild_tree(guild_id):
    
    return tree_data.get(guild_id)

def get_or_create_tree_player(guild_id, user_id):
    
    tree = tree_data.get(guild_id)
    if not tree:
        return None
    
    for contributor in tree["contributors"]:
        if contributor["userId"] == user_id:
            return contributor
    

    new_player = {"userId": user_id, "count": 0, "notifyXp": True, "level": 0, "xp": 0}
    tree["contributors"].append(new_player)
    save_data()
    return new_player

def get_tree_height(tree):
    
    return tree["size"]

def get_next_tree_level_required_xp(level):
    
    if level == 0:
        return 50
    else:
        return int(50 * (1.45 ** level))

class ConfigView(ui.View):
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.user_id = user_id
    
    @ui.button(label="Toggle", style=discord.ButtonStyle.primary, custom_id="tree_config_toggle")
    async def toggle(self, interaction: discord.Interaction, button: ui.Button):
        tree = tree_data.get(self.guild_id)
        if not tree:
            await interaction.response.send_message("Tree not found!", ephemeral=True)
            return
        
        for contributor in tree["contributors"]:
            if contributor["userId"] == self.user_id:
                contributor["notifyXp"] = not contributor["notifyXp"]
                save_data()
                
                embed = discord.Embed(
                    title="XP Notifications",
                    description=f"Whether to tell you how much XP was gained from watering a tree.\n\nCurrent: **{'Enabled' if contributor['notifyXp'] else 'Disabled'}**"
                )
                
                await interaction.response.edit_message(embed=embed, view=self)
                return
        
        await interaction.response.send_message("Player not found!", ephemeral=True)

def build_tree_embed(tree, starting=False):
    
    embed = discord.Embed(
        title=f"🌳 {tree['name']}",
        description=f"Size: {tree['size']} | Watered {tree['waterCount']} times",
        color=discord.Color.green()
    )
    if starting:
        embed.description = f"A new tree has been planted! Name: {tree['name']}"
    return embed

def build_background_embed(tree, current_background, position, background_names, backgrounds):
    
    embed = discord.Embed(
        title="🎨 Tree Backgrounds",
        description=f"Current background: **{background_names.get(current_background, 'Default')}**\n\nSelect a background:",
        color=discord.Color.blue()
    )
    return embed

class PlantConfirmationView(ui.View):
    def __init__(self, name):
        super().__init__(timeout=60)
        self.name = name
    
    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = str(interaction.guild.id)
        

        tree_data[guild_id] = {
            "name": self.name,
            "size": 0,
            "waterCount": 0,
            "contributors": []
        }
        save_data()
        
        embed = discord.Embed(
            title="🌳 Tree Planted!",
            description=f"Your tree ``{self.name}`` has been successfully planted!",
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)
    
    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
title="❌ Cancelled",
            description="Tree planting has been cancelled.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

class TreeView(ui.View):
    def __init__(self, tree, player):
        super().__init__(timeout=None)
        self.tree = tree
        self.player = player
        self.water_queue = []
        self.processing_water = False
    
    @ui.button(label="💧 Water", style=discord.ButtonStyle.primary, custom_id="tree_water")
    async def water(self, interaction: discord.Interaction, button: ui.Button):
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        tree = tree_data.get(guild_id)
        if not tree:
            await interaction.response.send_message("Tree not found!", ephemeral=True)
            return
        
        # Add this click to the queue
        self.water_queue.append((interaction, user_id, guild_id))
        
        # Acknowledge the click immediately
        await interaction.response.defer()
        
        # Start processing if not already running
        if not self.processing_water:
            self.processing_water = True
            asyncio.create_task(self.process_water_queue())
    
    async def process_water_queue(self):
        while self.water_queue:
            interaction, user_id, guild_id = self.water_queue.pop(0)
            
            # Wait 2 seconds before processing
            await asyncio.sleep(2)
            
            # Get fresh tree data
            tree = tree_data.get(guild_id)
            if not tree:
                continue
            
            # Update tree
            tree["size"] += 1
            tree["waterCount"] += 1
            
            # Use get_or_create_tree_player to ensure user is in contributors list
            player = get_or_create_tree_player(guild_id, user_id)
            if player:
                player["count"] += 1
            
            save_data()
            
            # Update the message with new tree state
            try:
                embed = build_tree_embed(tree)
                await interaction.edit_original_response(embed=embed, view=self)
            except:
                # If the original message is no longer available, just continue
                pass
        
        self.processing_water = False

class BackgroundView(ui.View):
    def __init__(self, tree, current_background, background_names, backgrounds):
        super().__init__(timeout=60)
        self.tree = tree
        self.current_background = current_background
        self.background_names = background_names
        self.backgrounds = backgrounds
        self.position = 0
        
        for bg_name in background_names.keys():
            self.add_item(ui.Button(label=bg_name, style=discord.ButtonStyle.secondary))

@bot.tree.command(name="activity-tree", description="Manage tree activities")
@discord.app_commands.describe(
    action="The action to perform",
    name="Tree name (only for plant action)",
    target="User whose profile you want to view (only for profile action)",
    page="Leaderboard page (only for leaderboard and forest actions)"
)
@discord.app_commands.choices(
    action=[
        discord.app_commands.Choice(name="register", value="register"),
        discord.app_commands.Choice(name="unregister", value="unregister"),
        discord.app_commands.Choice(name="plant", value="plant"),
        discord.app_commands.Choice(name="tree", value="tree"),
        discord.app_commands.Choice(name="leaderboard", value="leaderboard"),
        discord.app_commands.Choice(name="forest", value="forest"),
        discord.app_commands.Choice(name="profile", value="profile"),
        discord.app_commands.Choice(name="background", value="background"),
        discord.app_commands.Choice(name="config", value="config")
    ]
)
async def activity_tree(interaction: discord.Interaction, action: str, name: str = None, target: discord.Member = None, page: int = 1):
    
    guild_id = str(interaction.guild.id)
    channel_id = interaction.channel.id
    

    if action == "register":
        if not interaction.user.guild_permissions.administrator:
            error_embed = discord.Embed(
                title="Permission Denied",
                description="You need administrator permissions to register a tree channel.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        if channel_id in tree_channels:
            error_embed = discord.Embed(
                title="Channel Already Registered",
                description="This channel is already registered as a tree channel!",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        tree_channels[channel_id] = True
        save_data()
        
        success_embed = discord.Embed(
            title="Channel Registered",
            description=f"This channel has been registered as a tree channel! Use `/activity-tree plant` to plant a tree.",
            color=discord.Color.green()
        )
        success_embed.set_footer(text=f"Requested by {interaction.user.name}")
        await interaction.response.send_message(embed=success_embed)
    
    elif action == "unregister":
        if not interaction.user.guild_permissions.administrator:
            error_embed = discord.Embed(
                title="Permission Denied",
                description="You need administrator permissions to unregister a tree channel.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        if channel_id not in tree_channels:
            error_embed = discord.Embed(
                title="Channel Not Registered",
                description="This channel is not registered as a tree channel!",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        del tree_channels[channel_id]
        save_data()
        
        success_embed = discord.Embed(
            title="Channel Unregistered",
            description="This channel has been unregistered as a tree channel.",
            color=discord.Color.green()
        )
        success_embed.set_footer(text=f"Requested by {interaction.user.name}")
        await interaction.response.send_message(embed=success_embed)
    
    elif action == "plant":
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need administrator permissions to plant a tree.", ephemeral=True)
            return
        
        if channel_id not in tree_channels:
            error_embed = discord.Embed(
                title="Channel Not Registered",
                description="This channel is not registered as a tree channel! Use `/activity-tree register` first.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        if not name:
            await interaction.response.send_message("Please provide a name for your tree!", ephemeral=True)
            return
        

        if guild_id in tree_data:
            await interaction.response.send_message(
                f"A tree has already been planted in this server called ``{tree_data[guild_id]['name']}``. You can only have one per community.",
                ephemeral=True
            )
            return
        

        if not validate_tree_name(name):
            await interaction.response.send_message(
                "Your tree name must be 1-36 characters, and contain only alphanumeric characters, hyphens, and apostrophes.",
                ephemeral=True
            )
            return
        

        embed = discord.Embed(
            title=f"Are you sure you want to call your tree ``{name}``?",
            description="*Your tree name is public, so please avoid any profanity/nsfw/links.* ***Thanks! :)***"
        )
        embed.set_footer(
            text="If there is a problem the name will first be changed along with a warning, repeat offenses will have it locked to something boring."
        )
        
        view = PlantConfirmationView(name)
        await interaction.response.send_message(embed=embed, view=view)
    
    elif action == "tree":
        if channel_id not in tree_channels:
            error_embed = discord.Embed(
                title="Channel Not Registered",
                description="This channel is not registered as a tree channel! Use `/activity-tree register` first.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        tree = get_guild_tree(guild_id)
        if not tree:
            await interaction.response.send_message("Use /activity-tree plant to plant a tree for your server first.")
            return
        
        player = get_or_create_tree_player(guild_id, str(interaction.user.id))
        
        await interaction.response.defer()
        embed = build_tree_embed(tree, starting=False)
        view = TreeView(tree, player)
        msg = await interaction.followup.send(embed=embed, view=view)
        
        if "tree_view_messages" not in tree:
            tree["tree_view_messages"] = []
        tree["tree_view_messages"].append(msg.id)
        save_data()
    
    elif action == "leaderboard":
        if channel_id not in tree_channels:
            error_embed = discord.Embed(
                title="Channel Not Registered",
                description="This channel is not registered as a tree channel! Use `/activity-tree register` first.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        tree = get_guild_tree(guild_id)
        if not tree:
            await interaction.response.send_message("Use /activity-tree plant to plant a tree for your server first.", ephemeral=True)
            return
        
        if page < 1 or page > 10:
            await interaction.response.send_message("Page must be between 1 and 10.", ephemeral=True)
            return
        
        contributors = sorted(tree["contributors"], key=lambda x: x["count"], reverse=True)
        
        if not contributors:
            embed = discord.Embed(title="Greatest Gardeners", description="This page is empty.")
            await interaction.response.send_message(embed=embed)
            return
        
        medal_emojis = ["🥇", "🥈", "🥉"]
        description = ""
        
        start = (page - 1) * 10
        
        for i in range(start, min(start + 10, len(contributors))):
            contributor = contributors[i]
            medal = medal_emojis[i] if i < 3 else f"``{i + 1}{' ' if i < 9 else ''}``"
            description += f"{medal} - 💧{contributor['count']} <@{contributor['userId']}>\n"
        
        if start >= len(contributors):
            description = "This page is empty."
        
        embed = discord.Embed(title="Greatest Gardeners", description=description)
        await interaction.response.send_message(embed=embed)
    
    elif action == "forest":
        if page < 1 or page > 10:
            await interaction.response.send_message("Page must be between 1 and 10.", ephemeral=True)
            return
        

        trees = []
        for gid, tdata in tree_data.items():
            trees.append(tdata)
        
        trees.sort(key=lambda x: x["size"], reverse=True)
        
        if not trees:
            embed = discord.Embed(title="Forest", description="No trees have been planted yet.")
            await interaction.response.send_message(embed=embed)
            return
        
        medal_emojis = ["🥇", "🥈", "🥉"]
        description = "The tallest trees in all the Discord servers.\n\n"
        
        start = (page - 1) * 10
        
        for i in range(start, min(start + 10, len(trees))):
            tree = trees[i]
            pos = i + start
            medal = medal_emojis[i] if i < 3 else f"``{pos + 1}{' ' if pos < 9 else ''}``"
            height = get_tree_height(tree)
            description += f"{medal} - ``{tree['name']}`` - {height}ft\n"
        
        embed = discord.Embed(title="Forest", description=description)
        await interaction.response.send_message(embed=embed)
    
    elif action == "profile":
        if channel_id not in tree_channels:
            error_embed = discord.Embed(
                title="Channel Not Registered",
                description="This channel is not registered as a tree channel! Use `/activity-tree register` first.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        tree = get_guild_tree(guild_id)
        if not tree:
            await interaction.response.send_message("Use /activity-tree plant to plant a tree for your server first.", ephemeral=True)
            return
        
        user = target or interaction.user
        player = get_or_create_tree_player(guild_id, str(user.id))
        
        nick = user.nick if user.nick else user.name
        
        contributor = None
        for c in tree["contributors"]:
            if c["userId"] == str(user.id):
                contributor = c
                break
        
        if contributor:
            sorted_contributors = sorted(tree["contributors"], key=lambda x: x["count"], reverse=True)
            rank = sorted_contributors.index(contributor) + 1
            contrib_text = f"watered ``{tree['name']}`` {contributor['count']} times and are ranked #{rank}/{len(tree['contributors'])} in this community."
        else:
            contrib_text = "not yet watered the tree."
        
        embed = discord.Embed(
            title=f"{nick}'s Profile",
            description=f"Level: **{player['level']}**\nXP: {player['xp']}/{get_next_tree_level_required_xp(player['level'])}\n\n"
                        f"{'You have' if user.id == interaction.user.id else 'This player has'} {contrib_text}"
        )
        
        await interaction.response.send_message(embed=embed)
    
    elif action == "background":
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need administrator permissions to change the background.", ephemeral=True)
            return
        
        if channel_id not in tree_channels:
            error_embed = discord.Embed(
                title="Channel Not Registered",
                description="This channel is not registered as a tree channel! Use `/activity-tree register` first.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        
        tree = get_guild_tree(guild_id)
        if not tree:
            await interaction.response.send_message("Use /activity-tree plant to plant a tree for your server first.", ephemeral=True)
            return
        
        backgrounds = {
            "Ground": 0,
            "Sky": 5,
            "SpaceEdge": 1000
        }
        background_names = list(backgrounds.keys())
        
        current_background = tree.get("background", "Ground")
        position = background_names.index(current_background)
        
        embed = build_background_embed(tree, current_background, position, background_names, backgrounds)
        view = BackgroundView(tree, current_background, background_names, backgrounds)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    elif action == "config":
        player = get_or_create_tree_player(guild_id, str(interaction.user.id))
        
        embed = discord.Embed(
            title="XP Notifications",
            description=f"Whether to tell you how much XP was gained from watering a tree.\n\nCurrent: **{'Enabled' if player['notifyXp'] else 'Disabled'}**"
        )
        
        view = ConfigView(guild_id, str(interaction.user.id))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

def get_gambling_disclaimer():
    return "\n\n**Disclaimer:** We do not condone illegal gambling in real life."

async def log_economy_transaction(guild_id, transaction_type, user_id, amount, details=""):
    settings = get_economy_settings(guild_id)
    if not settings.get("audit_channel"):
        return
    
    channel = bot.get_channel(settings["audit_channel"])
    if not channel:
        return
    
    embed = discord.Embed(
        title="Economy Transaction",
        color=discord.Color.blue()
    )
    embed.add_field(name="Type", value=transaction_type, inline=True)
    embed.add_field(name="User", value="<@{}>".format(user_id), inline=True)
    embed.add_field(name="Amount", value=format_money(guild_id, amount), inline=True)
    if details:
        embed.add_field(name="Details", value=details, inline=False)
    
    await channel.send(embed=embed)

async def _handle_economy_action(interaction, guild_id, user_id, settings, action, amount_int, target, role_id, balance_type, channel_id, page, sort_by):
    if action == "set-currency":
        if not symbol:
            await interaction.response.send_message("Please provide a currency symbol!", ephemeral=True)
            return
        
        if symbol == "default":
            settings["currency"] = "$"
        else:
            settings["currency"] = symbol
        
        save_economy_data()
        
        embed = discord.Embed(
            title="Currency Set",
            description="Currency symbol has been set to {}".format(settings["currency"]),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "set-start-balance":
        if amount_int is None:
            await interaction.response.send_message("Please provide a valid amount!", ephemeral=True)
            return
        
        if amount_int < 0:
            await interaction.response.send_message("Amount cannot be negative!", ephemeral=True)
            return
        
        settings["start_balance"] = amount_int
        save_economy_data()
        
        embed = discord.Embed(
            title="Starting Balance Set",
            description="New members will start with {}".format(format_money(guild_id, amount_int)),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "money-audit-log":
        if channel_id and channel_id.lower() == "disable":
            settings["audit_channel"] = None
            save_economy_data()
            
            embed = discord.Embed(
                title="Audit Log Disabled",
                description="Money transaction logging has been disabled",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
        elif channel_id:
            try:
                channel = await interaction.guild.fetch_channel(int(channel_id))
                settings["audit_channel"] = channel_id
                save_economy_data()
                
                embed = discord.Embed(
                    title="Audit Log Set",
                    description="Money transactions will be logged to <#{}>".format(channel_id),
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed)
            except:
                await interaction.response.send_message("Invalid channel ID!", ephemeral=True)
    
    elif action == "maximum-balance":
        if amount_int is None:
            await interaction.response.send_message("Please provide a valid amount!", ephemeral=True)
            return
        
        if amount_int < 0:
            await interaction.response.send_message("Amount cannot be negative!", ephemeral=True)
            return
        
        if not balance_type:
            await interaction.response.send_message("Please specify cash or bank!", ephemeral=True)
            return
        
        if balance_type == "cash":
            settings["max_cash"] = amount_int
        else:
            settings["max_bank"] = amount_int
        
        save_economy_data()
        
        embed = discord.Embed(
            title="Maximum Balance Set",
            description="Maximum {} balance set to {}".format(balance_type, format_money(guild_id, amount_int)),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "money-audit-log":
        if channel_id and channel_id.lower() == "disable":
            settings["audit_channel"] = None
            save_economy_data()
            
            embed = discord.Embed(
                title="Audit Log Disabled",
                description="Money transaction logging has been disabled",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        if not channel_id:
            await interaction.response.send_message("Please provide a channel ID or 'disable'!", ephemeral=True)
            return
        
        try:
            channel_id_int = int(channel_id)
        except ValueError:
            await interaction.response.send_message("Invalid channel ID!", ephemeral=True)
            return
        
        settings["audit_channel"] = channel_id_int
        save_economy_data()
        
        embed = discord.Embed(
            title="Audit Log Enabled",
            description="Money transactions will be logged to <#{}>".format(channel_id),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "add-money":
        if not target:
            await interaction.response.send_message("Please mention a user!", ephemeral=True)
            return
        
        if amount_int is None:
            await interaction.response.send_message("Please provide a valid amount!", ephemeral=True)
            return
        
        if amount_int <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        balance = get_user_balance(guild_id, target.id)
        
        if not balance_type or balance_type == "cash":
            new_cash = balance["cash"] + amount_int
            if settings["max_cash"] > 0 and new_cash > settings["max_cash"]:
                new_cash = settings["max_cash"]
            balance["cash"] = new_cash
        else:
            new_bank = balance["bank"] + amount_int
            if settings["max_bank"] > 0 and new_bank > settings["max_bank"]:
                new_bank = settings["max_bank"]
            balance["bank"] = new_bank
        
        save_user_balance(guild_id, target.id)
        await log_economy_transaction(guild_id, "ADD MONEY", target.id, amount_int, "Added by admin")
        
        embed = discord.Embed(
            title="Money Added",
            description="Added {} to {}".format(format_money(guild_id, amount_int), target.mention),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "add-money-role":
        if not role_id:
            await interaction.response.send_message("Please provide a role ID!", ephemeral=True)
            return
        
        if amount_int is None:
            await interaction.response.send_message("Please provide a valid amount!", ephemeral=True)
            return
        
        if amount_int <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        try:
            role_id_int = int(role_id)
        except ValueError:
            await interaction.response.send_message("Invalid role ID!", ephemeral=True)
            return
        
        role = discord.utils.get(interaction.guild.roles, id=role_id_int)
        if not role:
            await interaction.response.send_message("Role not found!", ephemeral=True)
            return
        
        count = 0
        for member in interaction.guild.members:
            if role in member.roles and not member.bot:
                balance = get_user_balance(guild_id, member.id)
                if not balance_type or balance_type == "cash":
                    new_cash = balance["cash"] + amount_int
                    if settings["max_cash"] > 0 and new_cash > settings["max_cash"]:
                        new_cash = settings["max_cash"]
                    balance["cash"] = new_cash
                else:
                    new_bank = balance["bank"] + amount_int
                    if settings["max_bank"] > 0 and new_bank > settings["max_bank"]:
                        new_bank = settings["max_bank"]
                    balance["bank"] = new_bank
                save_user_balance(guild_id, member.id)
                count += 1
        
        await log_economy_transaction(guild_id, "ADD MONEY ROLE", user_id, amount_int, "Added to {} members with role {}".format(count, role.name))
        
        embed = discord.Embed(
            title="Money Added to Role",
            description="Added {} to {} members with role {}".format(format_money(guild_id, amount_int), count, role.name),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "remove-money":
        if not target:
            await interaction.response.send_message("Please mention a user!", ephemeral=True)
            return
        
        if amount_int is None:
            await interaction.response.send_message("Please provide a valid amount!", ephemeral=True)
            return
        
        if amount_int <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        balance = get_user_balance(guild_id, target.id)
        
        if not balance_type or balance_type == "cash":
            balance["cash"] = max(0, balance["cash"] - amount_int)
        else:
            balance["bank"] = max(0, balance["bank"] - amount_int)
        
        save_user_balance(guild_id, target.id)
        await log_economy_transaction(guild_id, "REMOVE MONEY", target.id, amount_int, "Removed by admin")
        
        embed = discord.Embed(
            title="Money Removed",
            description="Removed {} from {}".format(format_money(guild_id, amount_int), target.mention),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "remove-money-role":
        if not role_id:
            await interaction.response.send_message("Please provide a role ID!", ephemeral=True)
            return
        
        if amount_int is None:
            await interaction.response.send_message("Please provide a valid amount!", ephemeral=True)
            return
        
        if amount_int <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        try:
            role_id_int = int(role_id)
        except ValueError:
            await interaction.response.send_message("Invalid role ID!", ephemeral=True)
            return
        
        role = discord.utils.get(interaction.guild.roles, id=role_id_int)
        if not role:
            await interaction.response.send_message("Role not found!", ephemeral=True)
            return
        
        count = 0
        for member in interaction.guild.members:
            if role in member.roles and not member.bot:
                balance = get_user_balance(guild_id, member.id)
                if not balance_type or balance_type == "cash":
                    balance["cash"] = max(0, balance["cash"] - amount_int)
                else:
                    balance["bank"] = max(0, balance["bank"] - amount_int)
                save_user_balance(guild_id, member.id)
                count += 1
        
        await log_economy_transaction(guild_id, "REMOVE MONEY ROLE", user_id, amount_int, "Removed from {} members with role {}".format(count, role.name))
        
        embed = discord.Embed(
            title="Money Removed from Role",
            description="Removed {} from {} members with role {}".format(format_money(guild_id, amount_int), count, role.name),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "economy-stats":
        total_users = 0
        total_cash = 0
        total_bank = 0
        
        for key, data in economy_balances.items():
            gid, uid = key.split("_")
            if int(gid) == guild_id:
                total_users += 1
                total_cash += data.get("cash", 0)
                total_bank += data.get("bank", 0)
        
        embed = discord.Embed(
            title="Economy Statistics",
            color=discord.Color.blue()
        )
        embed.add_field(name="Total Users", value=str(total_users), inline=True)
        embed.add_field(name="Total Cash", value=format_money(guild_id, total_cash), inline=True)
        embed.add_field(name="Total Bank", value=format_money(guild_id, total_bank), inline=True)
        embed.add_field(name="Currency", value=settings["currency"], inline=True)
        embed.add_field(name="Start Balance", value=format_money(guild_id, settings["start_balance"]), inline=True)
        embed.add_field(name="Max Cash", value=format_money(guild_id, settings["max_cash"]) if settings["max_cash"] > 0 else "Disabled", inline=True)
        embed.add_field(name="Max Bank", value=format_money(guild_id, settings["max_bank"]) if settings["max_bank"] > 0 else "Disabled", inline=True)
        
        await interaction.response.send_message(embed=embed)
    
    elif action == "deposit":
        if amount_int is None:
            await interaction.response.send_message("Please provide an amount to deposit!", ephemeral=True)
            return
        
        balance = get_user_balance(guild_id, user_id)
        
        if amount_int == -1:
            amount_int = balance["cash"]
        
        if amount_int <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        if amount_int > balance["cash"]:
            await interaction.response.send_message("You don't have enough cash!", ephemeral=True)
            return
        
        balance["cash"] -= amount_int
        new_bank = balance["bank"] + amount_int
        if settings["max_bank"] > 0 and new_bank > settings["max_bank"]:
            new_bank = settings["max_bank"]
        balance["bank"] = new_bank
        save_user_balance(guild_id, user_id)
        
        embed = discord.Embed(
            title="Deposited",
            description="Deposited {} to your bank".format(format_money(guild_id, amount_int)),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "withdraw":
        if amount_int is None:
            await interaction.response.send_message("Please provide an amount to withdraw!", ephemeral=True)
            return
        
        balance = get_user_balance(guild_id, user_id)
        
        if amount_int == -1:
            amount_int = balance["bank"]
        
        if amount_int <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        if amount_int > balance["bank"]:
            await interaction.response.send_message("You don't have enough money in bank!", ephemeral=True)
            return
        
        balance["bank"] -= amount_int
        new_cash = balance["cash"] + amount_int
        if settings["max_cash"] > 0 and new_cash > settings["max_cash"]:
            new_cash = settings["max_cash"]
        balance["cash"] = new_cash
        save_user_balance(guild_id, user_id)
        
        embed = discord.Embed(
            title="Withdrawn",
            description="Withdrawn {} from your bank".format(format_money(guild_id, amount_int)),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "give-money":
        if not target:
            await interaction.response.send_message("Please mention a user!", ephemeral=True)
            return
        
        if amount_int is None:
            await interaction.response.send_message("Please provide an amount!", ephemeral=True)
            return
        
        if target.id == user_id:
            await interaction.response.send_message("You cannot give money to yourself!", ephemeral=True)
            return
        
        if amount_int <= 0:
            await interaction.response.send_message("Amount must be positive!", ephemeral=True)
            return
        
        balance = get_user_balance(guild_id, user_id)
        
        if amount_int == -1:
            amount_int = balance["cash"]
        
        if amount_int > balance["cash"]:
            await interaction.response.send_message("You don't have enough cash!", ephemeral=True)
            return
        
        balance["cash"] -= amount_int
        save_user_balance(guild_id, user_id)
        
        target_balance = get_user_balance(guild_id, target.id)
        new_cash = target_balance["cash"] + amount_int
        if settings["max_cash"] > 0 and new_cash > settings["max_cash"]:
            new_cash = settings["max_cash"]
        target_balance["cash"] = new_cash
        save_user_balance(guild_id, target.id)
        
        await log_economy_transaction(guild_id, "GIVE MONEY", user_id, amount_int, "Gave to {}".format(target.name))
        
        embed = discord.Embed(
            title="Money Given",
            description="You gave {} to {}".format(format_money(guild_id, amount_int), target.mention),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "money":
        if not target:
            target = interaction.user
        
        balance = get_user_balance(guild_id, target.id)
        
        leaderboard = []
        for key, data in economy_balances.items():
            gid, uid = key.split("_")
            if int(gid) == guild_id:
                total = data.get("cash", 0) + data.get("bank", 0)
                leaderboard.append((int(uid), total))
        
        leaderboard.sort(key=lambda x: x[1], reverse=True)
        
        rank = 0
        for i, (uid, total) in enumerate(leaderboard):
            if uid == target.id:
                rank = i + 1
                break
        
        embed = discord.Embed(
            title="{}'s Balance".format(target.display_name),
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Cash", value=format_money(guild_id, balance["cash"]), inline=True)
        embed.add_field(name="Bank", value=format_money(guild_id, balance["bank"]), inline=True)
        embed.add_field(name="Total", value=format_money(guild_id, balance["cash"] + balance["bank"]), inline=True)
        embed.add_field(name="Rank", value="#{}".format(rank), inline=True)
        
        await interaction.response.send_message(embed=embed)
    
    elif action == "leaderboard":
        leaderboard = []
        for key, data in economy_balances.items():
            gid, uid = key.split("_")
            if int(gid) == guild_id:
                cash = data.get("cash", 0)
                bank = data.get("bank", 0)
                total = cash + bank
                leaderboard.append((int(uid), cash, bank, total))
        
        if sort_by == "cash":
            leaderboard.sort(key=lambda x: x[1], reverse=True)
        elif sort_by == "bank":
            leaderboard.sort(key=lambda x: x[2], reverse=True)
        else:
            leaderboard.sort(key=lambda x: x[3], reverse=True)
        
        items_per_page = 10
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_data = leaderboard[start_idx:end_idx]
        
        if not page_data:
            await interaction.response.send_message("No data on this page!", ephemeral=True)
            return
        
        description = ""
        for i, (uid, cash, bank, total) in enumerate(page_data, start=start_idx + 1):
            member = None
            try:
                member = await interaction.guild.fetch_member(uid)
            except:
                pass
            
            if member:
                name = member.display_name
            else:
                name = "Unknown"
            
            if sort_by == "cash":
                value = format_money(guild_id, cash)
            elif sort_by == "bank":
                value = format_money(guild_id, bank)
            else:
                value = format_money(guild_id, total)
            description += "{}. {} - {}\n".format(i, name, value)
        
        embed = discord.Embed(
            title="Money Leaderboard - {}".format(sort_by.capitalize()),
            description=description,
            color=discord.Color.gold()
        )
        embed.set_footer(text="Page {}/{}".format(page, (len(leaderboard) - 1) // items_per_page + 1))
        
        await interaction.response.send_message(embed=embed)
    
    elif action == "clean-leaderboard":
        keys_to_remove = []
        
        if target:
            key = "{}_{}".format(guild_id, target.id)
            if key in economy_balances:
                keys_to_remove.append(key)
        else:
            current_members = set(m.id for m in interaction.guild.members)
            for key, data in economy_balances.items():
                gid, uid = key.split("_")
                if int(gid) == guild_id:
                    if int(uid) not in current_members:
                        keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del economy_balances[key]
        
        save_economy_data()
        
        if target:
            embed = discord.Embed(
                title="Leaderboard Cleaned",
                description="Removed {}'s data from the leaderboard".format(target.display_name),
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="Leaderboard Cleaned",
                description="Removed {} users who are no longer in the server".format(len(keys_to_remove)),
                color=discord.Color.green()
            )
        await interaction.response.send_message(embed=embed)
    
    elif action == "reset-money":
        if not target:
            target = interaction.user
        
        balance = get_user_balance(guild_id, target.id)
        balance["cash"] = settings["start_balance"]
        balance["bank"] = 0
        save_user_balance(guild_id, target.id)
        
        embed = discord.Embed(
            title="Money Reset",
            description="{}'s balance has been reset".format(target.display_name),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    elif action == "reset-economy":
        confirm_embed = discord.Embed(
            title="Confirm Economy Reset",
            description="Are you sure you want to reset EVERYONE'S money in this server?\n\nReact with CHECKMARK or X.\n\nCHECKMARK = Reset\nX = Cancel",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=confirm_embed)
        
        msg = await interaction.original_response()
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        
        def check(reaction, user):
            return user.id == interaction.user.id and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id
        
        try:
            reaction, user = await bot.wait_for("reaction_add", timeout=30.0, check=check)
            
            if str(reaction.emoji) == "✅":
                for key in list(economy_balances.keys()):
                    gid, uid = key.split("_")
                    if int(gid) == guild_id:
                        economy_balances[key]["cash"] = settings["start_balance"]
                        economy_balances[key]["bank"] = 0
                
                save_economy_data()
                
                reset_embed = discord.Embed(
                    title="Economy Reset",
                    description="All balances have been reset!",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=reset_embed)
            else:
                cancel_embed = discord.Embed(
                    title="Cancelled",
                    description="Economy reset has been cancelled.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=cancel_embed)
        
        except asyncio.TimeoutError:
            timeout_embed = discord.Embed(
                title="Timeout",
                description="Confirmation timed out.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=timeout_embed)
    
    elif action == "work":
        balance = get_user_balance(guild_id, user_id)
        
        jobs = [
            ("delivered pizzas", 50, 150),
            ("mowed lawns", 30, 100),
            ("fixed computers", 100, 250),
            ("walked dogs", 25, 80),
            ("stacked shelves", 40, 120),
            ("tutored students", 80, 200),
            ("painted houses", 150, 350),
            ("fixed plumbing", 120, 300),
            ("designed websites", 200, 500),
            ("wrote articles", 60, 150)
        ]
        
        job_verb, min_pay, max_pay = random.choice(jobs)
        earned = random.randint(min_pay, max_pay)
        
        new_cash = balance["cash"] + earned
        if settings["max_cash"] > 0 and new_cash > settings["max_cash"]:
            new_cash = settings["max_cash"]
        balance["cash"] = new_cash
        save_user_balance(guild_id, user_id)
        
        embed = discord.Embed(
            title="Work Complete!",
            description="You **{}** and earned {}!".format(job_verb, format_money(guild_id, earned)),
            color=discord.Color.green()
        )
        embed.set_footer(text="New balance: {}".format(format_money(guild_id, balance["cash"] + balance["bank"])))
        await interaction.response.send_message(embed=embed)
    
    elif action == "rob":
        if not target:
            await interaction.response.send_message("Please mention a user to rob!", ephemeral=True)
            return
        
        if target.id == user_id:
            await interaction.response.send_message("You can't rob yourself!", ephemeral=True)
            return
        
        target_balance = get_user_balance(guild_id, target.id)
        
        if target_balance["cash"] <= 0:
            await interaction.response.send_message("That user has no cash to rob!", ephemeral=True)
            return
        
        success_chance = 45
        success = random.randint(1, 100) <= success_chance
        
        if success:
            stolen = random.randint(1, target_balance["cash"])
            
            balance = get_user_balance(guild_id, user_id)
            new_cash = balance["cash"] + stolen
            if settings["max_cash"] > 0 and new_cash > settings["max_cash"]:
                new_cash = settings["max_cash"]
            balance["cash"] = new_cash
            
            target_balance["cash"] -= stolen
            save_user_balance(guild_id, target.id)
            save_user_balance(guild_id, user_id)
            
            embed = discord.Embed(
                title="Robbery Successful!",
                description="You robbed {} from {}!".format(format_money(guild_id, stolen), target.display_name),
                color=discord.Color.green()
            )
            embed.set_footer(text="New balance: {}".format(format_money(guild_id, balance["cash"] + balance["bank"])))
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="Robbery Failed!",
                description="You got caught trying to rob {}!".format(target.display_name),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
    
    elif action == "crime":
        crimes = [
            ("Pickpocketed a tourist", 20, 100, 30),
            ("Sold fake designer bags", 50, 200, 40),
            ("Hacked a bank account", 100, 500, 35),
            ("Ran a Ponzi scheme", 200, 800, 25),
            ("Smuggled rare items", 150, 600, 30),
            ("Counterfeited money", 100, 400, 35),
            ("Broke into a house", 80, 300, 40),
            ("Stole a car", 150, 500, 25),
            ("Committed identity theft", 100, 400, 30),
            ("Laundered money", 200, 700, 20)
        ]
        
        crime_name, min_reward, max_reward, fail_penalty_percent = random.choice(crimes)
        success = random.randint(1, 100) > fail_penalty_percent
        
        if success:
            earned = random.randint(min_reward, max_reward)
            balance = get_user_balance(guild_id, user_id)
            new_cash = balance["cash"] + earned
            if settings["max_cash"] > 0 and new_cash > settings["max_cash"]:
                new_cash = settings["max_cash"]
            balance["cash"] = new_cash
            save_user_balance(guild_id, user_id)
            
            embed = discord.Embed(
                title="Crime Successful!",
                description="You **{}** and got away with {}!".format(crime_name, format_money(guild_id, earned)),
                color=discord.Color.green()
            )
            embed.set_footer(text="New balance: {}".format(format_money(guild_id, balance["cash"] + balance["bank"])))
            await interaction.response.send_message(embed=embed)
        else:
            balance = get_user_balance(guild_id, user_id)
            loss = random.randint(int(balance["cash"] * 0.1), int(balance["cash"] * 0.3))
            loss = min(loss, balance["cash"])
            
            balance["cash"] -= loss
            save_user_balance(guild_id, user_id)
            
            embed = discord.Embed(
                title="Crime Failed!",
                description="You got caught trying to **{}**! You lost {} as a fine!".format(crime_name, format_money(guild_id, loss)),
                color=discord.Color.red()
            )
            embed.set_footer(text="New balance: {}".format(format_money(guild_id, balance["cash"] + balance["bank"])))
            await interaction.response.send_message(embed=embed)

@bot.tree.command(name="activity-economy", description="Economy commands")
@discord.app_commands.describe(
    action="The action to perform",
    symbol="Currency symbol to use",
    amount="Amount of money (or 'all' for deposit/withdraw/give/gamble)",
    target="User to target",
    role_id="Role ID to target",
    balance_type="cash or bank",
    channel_id="Channel ID for audit log",
    page="Page number for leaderboard",
    sort_by="What to sort leaderboard by"
)
@discord.app_commands.choices(
    action=[
        discord.app_commands.Choice(name="deposit", value="deposit"),
        discord.app_commands.Choice(name="withdraw", value="withdraw"),
        discord.app_commands.Choice(name="give-money", value="give-money"),
        discord.app_commands.Choice(name="money", value="money"),
        discord.app_commands.Choice(name="leaderboard", value="leaderboard"),
        discord.app_commands.Choice(name="work", value="work"),
        discord.app_commands.Choice(name="rob", value="rob"),
        discord.app_commands.Choice(name="crime", value="crime"),
        discord.app_commands.Choice(name="collect-income", value="collect-income")
    ],
    balance_type=[
        discord.app_commands.Choice(name="cash", value="cash"),
        discord.app_commands.Choice(name="bank", value="bank")
    ],
    sort_by=[
        discord.app_commands.Choice(name="cash", value="cash"),
        discord.app_commands.Choice(name="bank", value="bank"),
        discord.app_commands.Choice(name="total", value="total")
    ]
)
async def activity_economy(interaction: discord.Interaction, action: str, symbol: str = None, amount: str = None, target: discord.Member = None, role_id: str = None, balance_type: str = None, channel_id: str = None, page: int = 1, sort_by: str = "total"):
    amount_int = None
    if amount is not None:
        if amount.lower() == "all":
            amount_int = -1
        else:
            try:
                amount_int = int(amount)
            except ValueError:
                pass
    guild_id = interaction.guild.id
    user_id = interaction.user.id
    settings = get_economy_settings(guild_id)
    
    await _handle_economy_action(interaction, guild_id, user_id, settings, action, amount_int, target, role_id, balance_type, channel_id, page, sort_by)

@bot.tree.command(name="activity-economy-admin", description="Admin economy commands")
@discord.app_commands.describe(
    action="The action to perform",
    symbol="Currency symbol to use",
    amount="Amount of money",
    target="User to target",
    role_id="Role ID to target",
    balance_type="cash or bank",
    channel_id="Channel ID for audit log",
    page="Page number for leaderboard",
    sort_by="What to sort leaderboard by"
)
@discord.app_commands.choices(
    action=[
        discord.app_commands.Choice(name="set-currency", value="set-currency"),
        discord.app_commands.Choice(name="set-start-balance", value="set-start-balance"),
        discord.app_commands.Choice(name="money-audit-log", value="money-audit-log"),
        discord.app_commands.Choice(name="maximum-balance", value="maximum-balance"),
        discord.app_commands.Choice(name="add-money", value="add-money"),
        discord.app_commands.Choice(name="add-money-role", value="add-money-role"),
        discord.app_commands.Choice(name="remove-money", value="remove-money"),
        discord.app_commands.Choice(name="remove-money-role", value="remove-money-role"),
        discord.app_commands.Choice(name="economy-stats", value="economy-stats"),
        discord.app_commands.Choice(name="clean-leaderboard", value="clean-leaderboard"),
        discord.app_commands.Choice(name="reset-money", value="reset-money"),
        discord.app_commands.Choice(name="reset-economy", value="reset-economy"),
        discord.app_commands.Choice(name="role-income", value="role-income"),
        discord.app_commands.Choice(name="set-cooldown", value="set-cooldown"),
        discord.app_commands.Choice(name="set-fine-amount", value="set-fine-amount"),
        discord.app_commands.Choice(name="set-payout", value="set-payout"),
        discord.app_commands.Choice(name="set-fail-rate", value="set-fail-rate"),
        discord.app_commands.Choice(name="set-fine-type", value="set-fine-type"),
        discord.app_commands.Choice(name="chat-money-amount", value="chat-money-amount"),
        discord.app_commands.Choice(name="chat-money-channels", value="chat-money-channels")
    ],
    balance_type=[
        discord.app_commands.Choice(name="cash", value="cash"),
        discord.app_commands.Choice(name="bank", value="bank")
    ],
    sort_by=[
        discord.app_commands.Choice(name="cash", value="cash"),
        discord.app_commands.Choice(name="bank", value="bank"),
        discord.app_commands.Choice(name="total", value="total")
    ]
)
async def activity_economy_admin(interaction: discord.Interaction, action: str, symbol: str = None, amount: str = None, target: discord.Member = None, role_id: str = None, balance_type: str = None, channel_id: str = None, page: int = 1, sort_by: str = "total"):
    amount_int = None
    if amount is not None:
        if amount.lower() == "all":
            amount_int = -1
        else:
            try:
                amount_int = int(amount)
            except ValueError:
                pass
    guild_id = interaction.guild.id
    user_id = interaction.user.id
    settings = get_economy_settings(guild_id)
    
    required_roles = [1467889239512580261]
    user_roles = [role.id for role in interaction.user.roles]
    has_permission = any(role_id in user_roles for role_id in required_roles)
    
    if not has_permission:
        error_embed = discord.Embed(
            title="Permission Denied",
            description="You don't have permission to use this command.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=error_embed, ephemeral=True)
        return
    
    await _handle_economy_action(interaction, guild_id, user_id, settings, action, amount_int, target, role_id, balance_type, channel_id, page, sort_by)

RED_NUMBERS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
BLACK_NUMBERS = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

@bot.tree.command(name="activity-games", description="Play games and manage game settings")
@discord.app_commands.describe(
    action="The action to perform",
    game="The game to target (for set-bet-limit)",
    limit_type="min or max (for set-bet-limit)",
    amount="Bet amount or limit amount or cooldown duration",
    decks="Number of decks for blackjack (for set-blackjack-decks)",
    usages="Number of usages (for set-game-cooldown)",
    symbol="Symbol to add (for slot-machine-symbol)",
    multiplier="Multiplier for symbol (for slot-machine-symbol)",
    percentage="Percentage value (for chicken-fight-winrate)",
    space="Roulette betting space (single number, odd/even, red/black, or range)",
    target="User to target (for russian-roulette)",
    options="Max number or comma-separated options (for roll)",
    guess="Your guess for higher-lower (higher/lower/same)"
)
@discord.app_commands.choices(
    action=[
        discord.app_commands.Choice(name="blackjack", value="blackjack"),
        discord.app_commands.Choice(name="roulette", value="roulette"),
        discord.app_commands.Choice(name="roulette-info", value="roulette-info"),
        discord.app_commands.Choice(name="set-bet-limit", value="set-bet-limit"),
        discord.app_commands.Choice(name="set-blackjack-decks", value="set-blackjack-decks"),
        discord.app_commands.Choice(name="set-game-cooldown", value="set-game-cooldown"),
        discord.app_commands.Choice(name="slot-machine-symbol", value="slot-machine-symbol"),
        discord.app_commands.Choice(name="chicken-fight-winrate", value="chicken-fight-winrate"),
        discord.app_commands.Choice(name="higher-lower", value="higher-lower"),
        discord.app_commands.Choice(name="chicken-fight", value="chicken-fight"),
        discord.app_commands.Choice(name="russian-roulette", value="russian-roulette"),
        discord.app_commands.Choice(name="roll", value="roll"),
        discord.app_commands.Choice(name="slot-machine", value="slot-machine")
    ]
)
@discord.app_commands.choices(
    guess=[
        discord.app_commands.Choice(name="higher", value="higher"),
        discord.app_commands.Choice(name="lower", value="lower"),
        discord.app_commands.Choice(name="same", value="same")
    ]
)
async def activity_games(interaction: discord.Interaction, action: str, game: str = None, limit_type: str = None, amount: str = None, decks: int = None, usages: int = None, symbol: str = None, multiplier: float = None, percentage: str = None, space: str = None, target: discord.Member = None, options: str = None, guess: str = None):
    guild_id = interaction.guild.id
    user_id = interaction.user.id
    settings = get_game_settings()
    
    admin_actions = ["set-bet-limit", "set-blackjack-decks", "set-game-cooldown", "slot-machine-symbol", "chicken-fight-winrate"]
    
    if action in admin_actions:
        required_roles = [1467889239512580261]
        user_roles = [role.id for role in interaction.user.roles]
        has_permission = any(role_id in user_roles for role_id in required_roles)
        if not has_permission:
            error_embed = discord.Embed(title="Permission Denied", description="You don't have permission to use this command.", color=discord.Color.red())
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
    
    if action == "set-bet-limit":
        if not game or not limit_type or amount is None:
            await interaction.response.send_message("Please provide game, min/max, and amount!", ephemeral=True)
            return
        try:
            bet_amount = int(amount)
        except ValueError:
            await interaction.response.send_message("Invalid amount!", ephemeral=True)
            return
        if game not in settings["bet_limits"]:
            await interaction.response.send_message("Invalid game! Options: {}".format(", ".join(settings["bet_limits"].keys())), ephemeral=True)
            return
        if limit_type not in ("min", "max"):
            await interaction.response.send_message("Use 'min' or 'max' for limit_type!", ephemeral=True)
            return
        if bet_amount < 0:
            await interaction.response.send_message("Amount cannot be negative!", ephemeral=True)
            return
        if limit_type == "min":
            settings["bet_limits"][game]["min"] = bet_amount
        else:
            settings["bet_limits"][game]["max"] = bet_amount if bet_amount > 0 else None
        save_game_settings()
        embed = discord.Embed(title="Bet Limit Set", description="{} {} bet limit for {} set to {}".format(game, limit_type, game, bet_amount if limit_type == "min" else (bet_amount if bet_amount > 0 else "none")), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
    
    elif action == "set-blackjack-decks":
        if decks is None or decks < 1 or decks > 10:
            await interaction.response.send_message("Please provide a number between 1 and 10!", ephemeral=True)
            return
        settings["blackjack_decks"] = decks
        save_game_settings()
        embed = discord.Embed(title="Blackjack Decks Set", description="Using {} decks for blackjack.".format(decks), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
    
    elif action == "set-game-cooldown":
        if usages is None or not amount:
            await interaction.response.send_message("Please provide usages and duration! (eg. 4 5m)", ephemeral=True)
            return
        duration_str = amount
        duration_seconds = 0
        if duration_str.endswith("m"):
            duration_seconds = int(duration_str[:-1]) * 60
        elif duration_str.endswith("s"):
            duration_seconds = int(duration_str[:-1])
        elif duration_str.endswith("h"):
            duration_seconds = int(duration_str[:-1]) * 3600
        else:
            try:
                duration_seconds = int(duration_str)
            except ValueError:
                await interaction.response.send_message("Invalid duration! Use format like 5m, 30s, 1h.", ephemeral=True)
                return
        settings["game_cooldown"]["usages"] = usages
        settings["game_cooldown"]["duration"] = duration_seconds
        save_game_settings()
        embed = discord.Embed(title="Game Cooldown Set", description="{} usages every {} seconds.".format(usages, duration_seconds), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
    
    elif action == "slot-machine-symbol":
        if not symbol:
            await interaction.response.send_message("Provide a symbol to add or 'remove all' to reset.", ephemeral=True)
            return
        if symbol.lower() == "remove all":
            settings["slot_machine_symbols"] = [
                {"symbol": "🍒", "multiplier": 2},
                {"symbol": "🍋", "multiplier": 3},
                {"symbol": "🍊", "multiplier": 5},
                {"symbol": "🍇", "multiplier": 8},
                {"symbol": "💎", "multiplier": 15},
                {"symbol": "7️⃣", "multiplier": 25}
            ]
            save_game_settings()
            await interaction.response.send_message("Slot machine symbols reset to defaults.")
            return
        mult = multiplier if multiplier else 1.0
        settings["slot_machine_symbols"].append({"symbol": symbol, "multiplier": mult})
        save_game_settings()
        embed = discord.Embed(title="Symbol Added", description="Added {} with multiplier {}.".format(symbol, mult), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
    
    elif action == "chicken-fight-winrate":
        if not percentage:
            await interaction.response.send_message("Please provide start or max and a percentage! (eg. start 50%)", ephemeral=True)
            return
        pct = percentage.replace("%", "")
        try:
            pct_val = int(pct)
        except ValueError:
            await interaction.response.send_message("Invalid percentage!", ephemeral=True)
            return
        if pct_val < 0 or pct_val > 100:
            await interaction.response.send_message("Percentage must be between 0 and 100!", ephemeral=True)
            return
        if limit_type == "start":
            settings["chicken_fight_winrate"]["start"] = pct_val
        elif limit_type == "max":
            settings["chicken_fight_winrate"]["max"] = pct_val
        else:
            await interaction.response.send_message("Specify 'start' or 'max' as the limit_type!", ephemeral=True)
            return
        save_game_settings()
        embed = discord.Embed(title="Win Rate Set", description="Chicken fight {} win rate set to {}%".format(limit_type, pct_val), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)
    
    elif action == "roulette-info":
        embed = discord.Embed(title="Roulette Information", color=discord.Color.blue())
        embed.add_field(name="Betting Spaces", value="""Single number (0-36): 35x payout
1-12 / 13-24 / 25-36: 2x payout
odd / even: 1x payout
red / black: 1x payout""", inline=False)
        embed.add_field(name="Roulette Layout", value="""0: Green
Red: 1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36
Black: 2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35""", inline=False)
        await interaction.response.send_message(embed=embed)
    
    elif action == "blackjack":
        if not amount:
            await interaction.response.send_message("Please provide a bet amount!", ephemeral=True)
            return
        bet_int = None
        if amount.lower() == "all":
            bet_int = get_user_balance(guild_id, user_id)["cash"]
        else:
            try:
                bet_int = int(amount)
            except ValueError:
                pass
        if bet_int is None or bet_int <= 0:
            await interaction.response.send_message("Invalid bet amount!", ephemeral=True)
            return
        min_bet = settings["bet_limits"]["blackjack"]["min"]
        max_bet = settings["bet_limits"]["blackjack"]["max"]
        if bet_int < min_bet:
            await interaction.response.send_message("Minimum bet is {}!".format(format_money(guild_id, min_bet)), ephemeral=True)
            return
        if max_bet and bet_int > max_bet:
            await interaction.response.send_message("Maximum bet is {}!".format(format_money(guild_id, max_bet)), ephemeral=True)
            return
        balance = get_user_balance(guild_id, user_id)
        if bet_int > balance["cash"]:
            await interaction.response.send_message("You don't have enough cash!", ephemeral=True)
            return
        decks = settings["blackjack_decks"]
        shoe = []
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        for _ in range(decks):
            for r in ranks:
                shoe.append(r)
        random.shuffle(shoe)
        def draw():
            return shoe.pop()
        def card_value(card):
            if card in ["J", "Q", "K"]:
                return 10
            elif card == "A":
                return 11
            else:
                return int(card)
        def hand_value(hand):
            value = sum(card_value(c) for c in hand)
            aces = hand.count("A")
            while value > 21 and aces > 0:
                value -= 10
                aces -= 1
            return value
        player_hand = [draw(), draw()]
        dealer_hand = [draw(), draw()]
        player_total = hand_value(player_hand)
        while hand_value(dealer_hand) < 17:
            dealer_hand.append(draw())
        dealer_total = hand_value(dealer_hand)
        result = ""
        color = discord.Color.red()
        if player_total > 21:
            result = "You busted! Dealer wins."
            balance["cash"] -= bet_int
        elif dealer_total > 21:
            result = "Dealer busts! You win!"
            balance["cash"] += bet_int
            color = discord.Color.green()
        elif player_total > dealer_total:
            result = "You win!"
            balance["cash"] += bet_int
            color = discord.Color.green()
        elif player_total < dealer_total:
            result = "Dealer wins."
            balance["cash"] -= bet_int
        else:
            result = "Push! It's a tie."
        save_user_balance(guild_id, user_id)
        embed = discord.Embed(title="Blackjack ({} decks)".format(decks), description="Your hand: {} ({})\nDealer hand: {} ({})\n\n**{}**".format(" ".join(player_hand), player_total, " ".join(dealer_hand), dealer_total, result), color=color)
        embed.set_footer(text="Your balance: {}".format(format_money(guild_id, balance["cash"])))
        embed.add_field(name="Disclaimer", value="We do not condone illegal gambling in real life.")
        await interaction.response.send_message(embed=embed)
    
    elif action == "roulette":
        if not amount:
            await interaction.response.send_message("Please provide a bet amount!", ephemeral=True)
            return
        bet_int = None
        if amount.lower() == "all":
            bet_int = get_user_balance(guild_id, user_id)["cash"]
        else:
            try:
                bet_int = int(amount)
            except ValueError:
                pass
        if bet_int is None or bet_int <= 0:
            await interaction.response.send_message("Invalid bet amount!", ephemeral=True)
            return
        min_bet = settings["bet_limits"]["roulette"]["min"]
        max_bet = settings["bet_limits"]["roulette"]["max"]
        if bet_int < min_bet:
            await interaction.response.send_message("Minimum bet is {}!".format(format_money(guild_id, min_bet)), ephemeral=True)
            return
        if max_bet and bet_int > max_bet:
            await interaction.response.send_message("Maximum bet is {}!".format(format_money(guild_id, max_bet)), ephemeral=True)
            return
        balance = get_user_balance(guild_id, user_id)
        if bet_int > balance["cash"]:
            await interaction.response.send_message("You don't have enough cash!", ephemeral=True)
            return
        if not space:
            await interaction.response.send_message("Please specify a betting space! Use /activity-games roulette-info to see options.", ephemeral=True)
            return
        space_lower = space.lower()
        matched_space = None
        payout = 0
        try:
            num = int(space)
            if 0 <= num <= 36:
                matched_space = ("straight", num)
                payout = 35
        except ValueError:
            pass
        if not matched_space:
            if space_lower in ("odd", "even"):
                matched_space = ("even_money", space_lower)
                payout = 1
            elif space_lower in ("red", "rd", "black"):
                matched_space = ("even_money", space_lower)
                payout = 1
            elif space_lower in ("1-12", "13-24", "25-36"):
                matched_space = ("dozen", space_lower)
                payout = 2
        if not matched_space:
            await interaction.response.send_message("Invalid betting space! Use /activity-games roulette-info to see options.", ephemeral=True)
            return
        winning_number = random.randint(0, 36)
        is_red = winning_number in RED_NUMBERS
        is_black = winning_number in BLACK_NUMBERS
        is_green = winning_number == 0
        won = False
        space_type, space_value = matched_space
        if space_type == "straight":
            if winning_number == space_value:
                won = True
        elif space_type == "even_money":
            if space_value in ("red", "rd") and is_red:
                won = True
            elif space_value == "black" and is_black:
                won = True
            elif space_value == "odd" and winning_number % 2 == 1 and not is_green:
                won = True
            elif space_value == "even" and winning_number % 2 == 0 and not is_green and winning_number != 0:
                won = True
        elif space_type == "dozen":
            if space_value == "1-12" and 1 <= winning_number <= 12:
                won = True
            elif space_value == "13-24" and 13 <= winning_number <= 24:
                won = True
            elif space_value == "25-36" and 25 <= winning_number <= 36:
                won = True
        color_name = "green" if is_green else ("red" if is_red else "black")
        result_text = "The ball landed on **{} {}**!".format(winning_number, color_name)
        color = discord.Color.red()
        if won:
            win_amount = bet_int * payout
            balance["cash"] += win_amount
            result_text += "\n\nYou won {}! ({}x payout)".format(format_money(guild_id, win_amount), payout)
            color = discord.Color.green()
        else:
            balance["cash"] -= bet_int
            result_text += "\n\nYou lost {}.".format(format_money(guild_id, bet_int))
        save_user_balance(guild_id, user_id)
        embed = discord.Embed(title="Roulette - Bet on {}".format(space), description=result_text, color=color)
        embed.set_footer(text="Your balance: {}".format(format_money(guild_id, balance["cash"])))
        embed.add_field(name="Disclaimer", value="We do not condone illegal gambling in real life.")
        await interaction.response.send_message(embed=embed)
    
    elif action == "higher-lower":
        if not guess or guess not in ("higher", "lower", "same"):
            await interaction.response.send_message("Please choose higher, lower, or same as your guess!", ephemeral=True)
            return
        if not amount:
            await interaction.response.send_message("Please provide a bet amount!", ephemeral=True)
            return
        bet_int = None
        if amount.lower() == "all":
            bet_int = get_user_balance(guild_id, user_id)["cash"]
        else:
            try:
                bet_int = int(amount)
            except ValueError:
                pass
        if bet_int is None or bet_int <= 0:
            await interaction.response.send_message("Invalid bet amount!", ephemeral=True)
            return
        min_bet = settings["bet_limits"]["higher-or-lower"]["min"]
        max_bet = settings["bet_limits"]["higher-or-lower"]["max"]
        if bet_int < min_bet:
            await interaction.response.send_message("Minimum bet is {}!".format(format_money(guild_id, min_bet)), ephemeral=True)
            return
        if max_bet and bet_int > max_bet:
            await interaction.response.send_message("Maximum bet is {}!".format(format_money(guild_id, max_bet)), ephemeral=True)
            return
        balance = get_user_balance(guild_id, user_id)
        if bet_int > balance["cash"]:
            await interaction.response.send_message("You don't have enough cash!", ephemeral=True)
            return
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        def card_value(card):
            return ranks.index(card)
        card1 = random.choice(ranks)
        card2 = random.choice(ranks)
        val1 = card_value(card1)
        val2 = card_value(card2)
        if val2 > val1:
            actual = "higher"
        elif val2 < val1:
            actual = "lower"
        else:
            actual = "same"
        correct = guess == actual
        result_text = "Your card: **{}**\n".format(card1)
        color = discord.Color.red()
        if correct:
            result_text += "Next card: **{}** - {}! You guessed right!".format(card2, actual.capitalize())
            balance["cash"] += bet_int
            color = discord.Color.green()
        else:
            result_text += "Next card: **{}** - {}! You guessed **{}**.".format(card2, actual.capitalize(), guess)
            balance["cash"] -= bet_int
        save_user_balance(guild_id, user_id)
        embed = discord.Embed(title="Higher or Lower", description=result_text, color=color)
        embed.set_footer(text="Your balance: {}".format(format_money(guild_id, balance["cash"])))
        await interaction.response.send_message(embed=embed)
    
    elif action == "chicken-fight":
        if not amount:
            await interaction.response.send_message("Please provide a bet amount!", ephemeral=True)
            return
        bet_int = None
        if amount.lower() == "all":
            bet_int = get_user_balance(guild_id, user_id)["cash"]
        else:
            try:
                bet_int = int(amount)
            except ValueError:
                pass
        if bet_int is None or bet_int <= 0:
            await interaction.response.send_message("Invalid bet amount!", ephemeral=True)
            return
        min_bet = settings["bet_limits"]["chicken-fight"]["min"]
        max_bet = settings["bet_limits"]["chicken-fight"]["max"]
        if bet_int < min_bet:
            await interaction.response.send_message("Minimum bet is {}!".format(format_money(guild_id, min_bet)), ephemeral=True)
            return
        if max_bet and bet_int > max_bet:
            await interaction.response.send_message("Maximum bet is {}!".format(format_money(guild_id, max_bet)), ephemeral=True)
            return
        balance = get_user_balance(guild_id, user_id)
        if bet_int > balance["cash"]:
            await interaction.response.send_message("You don't have enough cash!", ephemeral=True)
            return
        uid_str = str(user_id)
        chicken = user_chickens.get(uid_str, {"wins": 0})
        start_rate = settings["chicken_fight_winrate"]["start"]
        max_rate = settings["chicken_fight_winrate"]["max"]
        win_rate = min(start_rate + chicken["wins"], max_rate)
        roll = random.randint(1, 100)
        won = roll <= win_rate
        color = discord.Color.red()
        result_text = "Your chicken struts into the ring...\nWin chance: {}%\n".format(win_rate)
        if won:
            chicken["wins"] = chicken.get("wins", 0) + 1
            result_text += "Your chicken WINS! 🐔💪"
            balance["cash"] += bet_int
            color = discord.Color.green()
        else:
            chicken["wins"] = 0
            result_text += "Your chicken lost... 🐔💀"
            balance["cash"] -= bet_int
        user_chickens[uid_str] = chicken
        save_user_balance(guild_id, user_id)
        embed = discord.Embed(title="Chicken Fight", description=result_text, color=color)
        embed.set_footer(text="Your balance: {}".format(format_money(guild_id, balance["cash"])))
        await interaction.response.send_message(embed=embed)
    
    elif action == "russian-roulette":
        if not target:
            await interaction.response.send_message("Please mention a player to play against!", ephemeral=True)
            return
        if target.id == user_id:
            await interaction.response.send_message("You can't play Russian Roulette with yourself!", ephemeral=True)
            return
        if not amount:
            await interaction.response.send_message("Please provide a bet amount!", ephemeral=True)
            return
        bet_int = None
        if amount.lower() == "all":
            bet_int = get_user_balance(guild_id, user_id)["cash"]
        else:
            try:
                bet_int = int(amount)
            except ValueError:
                pass
        if bet_int is None or bet_int <= 0:
            await interaction.response.send_message("Invalid bet amount!", ephemeral=True)
            return
        min_bet = settings["bet_limits"]["russian-roulette"]["min"]
        max_bet = settings["bet_limits"]["russian-roulette"]["max"]
        if bet_int < min_bet:
            await interaction.response.send_message("Minimum bet is {}!".format(format_money(guild_id, min_bet)), ephemeral=True)
            return
        if max_bet and bet_int > max_bet:
            await interaction.response.send_message("Maximum bet is {}!".format(format_money(guild_id, max_bet)), ephemeral=True)
            return
        balance = get_user_balance(guild_id, user_id)
        if bet_int > balance["cash"]:
            await interaction.response.send_message("You don't have enough cash!", ephemeral=True)
            return
        target_balance = get_user_balance(guild_id, target.id)
        if bet_int > target_balance["cash"]:
            await interaction.response.send_message("{} doesn't have enough cash!".format(target.display_name), ephemeral=True)
            return
        chamber = random.randint(1, 6)
        loser_id = user_id if chamber <= 3 else target.id
        winner_id = target.id if loser_id == user_id else user_id
        winner_balance = get_user_balance(guild_id, winner_id)
        loser_balance = get_user_balance(guild_id, loser_id)
        loser_balance["cash"] -= bet_int
        winner_balance["cash"] += bet_int
        save_user_balance(guild_id, loser_id)
        save_user_balance(guild_id, winner_id)
        loser = interaction.guild.get_member(loser_id)
        embed = discord.Embed(title="🔫 Russian Roulette", description="The chamber was pulled...\n\n<@{}> loses! 💀\n\n<@{}> wins {}!".format(loser_id, winner_id, format_money(guild_id, bet_int)), color=discord.Color.red())
        await interaction.response.send_message(embed=embed)
        if loser:
            try:
                await loser.timeout(discord.utils.utcnow() + timedelta(minutes=5), reason="Lost Russian Roulette")
            except:
                pass
    
    elif action == "roll":
        if not options:
            await interaction.response.send_message("Provide a number (e.g. 6) or comma-separated options!", ephemeral=True)
            return
        if "," in options:
            choices_list = [opt.strip() for opt in options.split(",")]
            result = random.choice(choices_list)
            await interaction.response.send_message("🎲 The chosen option is: **{}**!".format(result))
        else:
            try:
                max_num = int(options)
                if max_num < 1:
                    await interaction.response.send_message("Number must be at least 1!", ephemeral=True)
                    return
                result = random.randint(1, max_num)
                await interaction.response.send_message("🎲 You rolled a **{}**! (1-{})".format(result, max_num))
            except ValueError:
                await interaction.response.send_message("Invalid input! Use a number or comma-separated options.", ephemeral=True)
    
    elif action == "slot-machine":
        if not amount:
            await interaction.response.send_message("Please provide a bet amount!", ephemeral=True)
            return
        bet_int = None
        if amount.lower() == "all":
            bet_int = get_user_balance(guild_id, user_id)["cash"]
        else:
            try:
                bet_int = int(amount)
            except ValueError:
                pass
        if bet_int is None or bet_int <= 0:
            await interaction.response.send_message("Invalid bet amount!", ephemeral=True)
            return
        min_bet = settings["bet_limits"]["slot-machine"]["min"]
        max_bet = settings["bet_limits"]["slot-machine"]["max"]
        if bet_int < min_bet:
            await interaction.response.send_message("Minimum bet is {}!".format(format_money(guild_id, min_bet)), ephemeral=True)
            return
        if max_bet and bet_int > max_bet:
            await interaction.response.send_message("Maximum bet is {}!".format(format_money(guild_id, max_bet)), ephemeral=True)
            return
        balance = get_user_balance(guild_id, user_id)
        if bet_int > balance["cash"]:
            await interaction.response.send_message("You don't have enough cash!", ephemeral=True)
            return
        symbols = [s["symbol"] for s in settings["slot_machine_symbols"]]
        multipliers = {s["symbol"]: s["multiplier"] for s in settings["slot_machine_symbols"]}
        grid = [[random.choice(symbols) for _ in range(3)] for _ in range(3)]
        middle_row = grid[1]
        result_text = "```\n"
        for row in grid:
            result_text += "  ".join(row) + "\n"
        result_text += "```\n"
        color = discord.Color.red()
        if middle_row[0] == middle_row[1] == middle_row[2]:
            sym = middle_row[0]
            win_mult = multipliers.get(sym, 1)
            win_amount = int(bet_int * win_mult)
            balance["cash"] += win_amount
            result_text += "JACKPOT! Three {} in a row! You won {}! ({}x multiplier)".format(sym, format_money(guild_id, win_amount), win_mult)
            color = discord.Color.green()
        else:
            balance["cash"] -= bet_int
            result_text += "No match. You lost {}.".format(format_money(guild_id, bet_int))
        save_user_balance(guild_id, user_id)
        embed = discord.Embed(title="🎰 Slot Machine", description=result_text, color=color)
        embed.set_footer(text="Your balance: {}".format(format_money(guild_id, balance["cash"])))
        await interaction.response.send_message(embed=embed)


@bot.event
async def on_message(message):

    if message.author.bot:
        return
    
    if isinstance(message.channel, discord.DMChannel):
        target_user_ids = [775397655576707103, 1417671348767035552]
        if message.author.id in target_user_ids and message.content.startswith("!resolve "):
            ref_msg_id = str(message.reference.message_id) if message.reference and message.reference.message_id else None
            case_num = message_case_map.get(ref_msg_id) if ref_msg_id else None
            
            if not case_num:
                no_case_embed = discord.Embed(
                    title="Error",
                    description="Reply to a case notification message to resolve it.",
                    color=discord.Color.red()
                )
                await message.channel.send(embed=no_case_embed)
                return
            
            resolve_msg = message.content[len("!resolve "):]
            case = cases.get(case_num)
            
            if not case or case.get("status") != "open":
                already_embed = discord.Embed(
                    title="Already Resolved",
                    description="Case #{} is already resolved.".format(case_num),
                    color=discord.Color.orange()
                )
                await message.channel.send(embed=already_embed)
                return
            
            case["status"] = "resolved"
            
            stale_keys = [k for k, v in message_case_map.items() if v == case_num]
            for k in stale_keys:
                del message_case_map[k]
            
            save_reports()
            
            try:
                submitter = await bot.fetch_user(case["submitter_id"])
                resolve_embed = discord.Embed(
                    title="Case #{} Resolved".format(case_num),
                    color=discord.Color.green()
                )
                resolve_embed.add_field(name="Resolved by", value="<@{}>".format(message.author.id), inline=False)
                resolve_embed.add_field(name="Message", value=resolve_msg, inline=False)
                await submitter.send(embed=resolve_embed)
            except Exception as e:
                print("Failed to notify submitter for case {}: {}".format(case_num, e))
                await message.channel.send("Failed to notify the submitter, but case has been resolved.")
                return
            
            confirm_embed = discord.Embed(
                title="Case #{} Resolved".format(case_num),
                description="The submitter has been notified.",
                color=discord.Color.green()
            )
            await message.channel.send(embed=confirm_embed)
            return
        
        cmd = message.content.lower()
        admin_role_id = 1467889239512580261

        if cmd == "join":
            for guild in bot.guilds:
                member = guild.get_member(message.author.id)
                if member and any(r.id == admin_role_id for r in member.roles):
                    if member.voice and member.voice.channel:
                        vc = member.voice.channel
                        if guild.voice_client:
                            await guild.voice_client.move_to(vc)
                        else:
                            await vc.connect()
                        await message.channel.send("Joined {}.".format(vc.name))
                        return
            await message.channel.send("You don't have permission or you're not in a voice channel.")
            return

        elif cmd in ("au-mute", "au-talk", "disconnect"):
            target_guild = None
            for guild in bot.guilds:
                member = guild.get_member(message.author.id)
                if member and any(r.id == admin_role_id for r in member.roles):
                    if guild.voice_client:
                        target_guild = guild
                        break

            if not target_guild:
                await message.channel.send("I'm not in a voice channel.")
                return

            vc = target_guild.voice_client

            if cmd == "au-mute":
                for m in vc.channel.members:
                    if not m.bot:
                        await m.edit(mute=True, deafen=True)
                await message.channel.send("Server muted and deafened everyone.")

            elif cmd == "au-talk":
                for m in vc.channel.members:
                    if not m.bot:
                        await m.edit(mute=False, deafen=False)
                await message.channel.send("Server unmuted and undeafened everyone.")

            elif cmd == "disconnect":
                await vc.disconnect()
                await message.channel.send("Disconnected from voice channel.")

            return
        
        return
    
    print(f"=== MESSAGE RECEIVED ===")
    print(f"Message: \"{message.content}\"")
    print(f"Sender: \"{message.author.name}\" | \"{message.author.display_name}\"")
    print(f"Channel: \"{message.channel.name}\"")
    

    channel_id = message.channel.id
    if channel_id not in counting_channels:

        if not check_blacklisted_roles(message.author, str(message.guild.id)):

            if str(message.guild.id) not in ["264445053596991498", "110373943822540800"] and channel_id != 1444654050418360450:
                user_id = str(message.author.id)
                if user_id not in talked_recently:
                    score_system_json(message)
                    talked_recently.add(user_id)
                    

                    asyncio.create_task(remove_from_cooldown(user_id))
    

    print(f"Checking counting logic - Channel ID: {channel_id}")
    if channel_id in counting_channels:
        print(f"Channel registered: True")
        if channel_id in counting_games and counting_games[channel_id]["active"]:
            print(f"Active game: True")
        else:
            print(f"Active game: False")
    else:
        print(f"Channel not registered as counting channel")
    

    print(f"Checking for reply command in message: '{message.content}'")
    if message.content.startswith("reply "):
        print(f"Reply command detected: {message.content}")
        await handle_reply_command(message)
        return
    
    if channel_id not in counting_channels:
        return
    
    if channel_id not in counting_games or not counting_games[channel_id]["active"]:
        return
    

    try:
        content = message.content.strip()
        

        if not content.isdigit():
            return
        

        if (message.embeds or message.attachments or 
            message.stickers or message.components):
            await message.add_reaction("❌")
            no_number_embed = discord.Embed(
                title="No Number Found",
                description="You need to say a number! This is a counting channel. Restarting...",
                color=discord.Color.red()
            )
            await message.reply(embed=no_number_embed)
            counting_games[channel_id] = {"current_number": 0, "active": True, "last_user": None}
            save_data()
            return
        

        if len(content) == 0:
            await message.add_reaction("❌")
            no_number_embed = discord.Embed(
                title="No Number Found",
                description="You need to say a number! This is a counting channel. Restarting...",
                color=discord.Color.red()
            )
            await message.reply(embed=no_number_embed)
            counting_games[channel_id] = {"current_number": 0, "active": True, "last_user": None}
            save_data()
            return
        
        number = int(content)
        current_number = counting_games[channel_id]["current_number"]
        expected_number = current_number + 1
        
        if number == expected_number:
            counting_caught_up[channel_id] = True

            last_user = counting_games[channel_id].get("last_user")
            if last_user == message.author.id:
                await message.add_reaction("❌")
                same_person_embed = discord.Embed(
                    title="Same Person Counted Twice!",
                    description="You can't count twice in a row! Learn from the old bot! Restarting...",
                    color=discord.Color.orange()
                )
                await message.reply(embed=same_person_embed)
                counting_games[channel_id] = {"current_number": 0, "active": True, "last_user": None}
                save_data()
                return
            

            await message.add_reaction("✅")
            counting_games[channel_id]["current_number"] = number
            counting_games[channel_id]["last_user"] = message.author.id
            save_data()
        elif number > expected_number and not counting_caught_up.get(channel_id):
            last_user = counting_games[channel_id].get("last_user")
            if last_user == message.author.id:
                await message.add_reaction("❌")
                same_person_embed = discord.Embed(
                    title="Same Person Counted Twice!",
                    description="You can't count twice in a row! Learning from the old bot! Restarting...",
                    color=discord.Color.orange()
                )
                await message.reply(embed=same_person_embed)
                counting_games[channel_id] = {"current_number": 0, "active": True, "last_user": None}
                save_data()
                return
            
            counting_caught_up[channel_id] = True
            await message.add_reaction("✅")
            counting_games[channel_id]["current_number"] = number
            counting_games[channel_id]["last_user"] = message.author.id
            save_data()
        else:
            await message.add_reaction("❌")

            game_over_embed = discord.Embed(
                title="Game over!",
                description="You messed up the count! Restarting....",
                color=discord.Color.red()
            )
            
            await message.reply(embed=game_over_embed)
            counting_games[channel_id] = {"current_number": 0, "active": True, "last_user": None}
            save_data()
            
    except Exception as e:
        print(f"Error in counting game: {e}")

@bot.event
async def on_application_command_error(interaction: discord.Interaction, error):
    if isinstance(error, discord.app_commands.CommandNotFound):
        try:
            await interaction.response.send_message("Command not found!", ephemeral=True)
        except discord.errors.NotFound:
            pass
    elif isinstance(error, discord.app_commands.CommandInvokeError):
        if isinstance(error.__cause__, discord.errors.NotFound) and error.__cause__.code == 10062:
            print(f"Unknown interaction error (likely expired): {error.__cause__}")
        else:
            print(f'Command invoke error: {error}')
            try:
                await interaction.response.send_message("An error occurred while running this command.", ephemeral=True)
            except discord.errors.NotFound:
                pass
    else:
        print(f'Slash command error: {error}')
        try:
            await interaction.response.send_message("An error occurred while running this command.", ephemeral=True)
        except discord.errors.NotFound:
            pass

@bot.tree.command(name="dev-info", description="Display development information (admin only)")
async def dev_info(interaction: discord.Interaction):
    
    if interaction.guild is None:
        allowed_users = [775397655576707103]
        if interaction.user.id not in allowed_users:
            error_embed = discord.Embed(
                title="Access Denied",
                description="This command can only be used by the bot owner in DMs.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
    else:
        required_roles = [1467889239512580261]
        user_roles = [role.id for role in interaction.user.roles]
        has_permission = any(role_id in user_roles for role_id in required_roles)
        
        if not has_permission:
            error_embed = discord.Embed(
                title="Access Denied",
                description="You don't have permission to use this command.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
    
    import os
    import time
    

    start_time = time.time()
    await interaction.response.defer(ephemeral=True)
    end_time = time.time()
    ping_ms = round((end_time - start_time) * 1000)
    

    script_path = os.path.abspath(__file__)
    mod_time = os.path.getmtime(__file__)
    mod_datetime = datetime.fromtimestamp(mod_time)
    now = datetime.now()
    time_diff = now - mod_datetime
    

    if time_diff.days > 0:
        if time_diff.days == 1:
            time_str = "1 day ago"
        elif time_diff.days < 7:
            time_str = f"{time_diff.days} days ago"
        elif time_diff.days < 30:
            weeks = time_diff.days // 7
            time_str = f"{weeks} week{'s' if weeks != 1 else ''} ago"
        else:
            months = time_diff.days // 30
            time_str = f"{months} month{'s' if months != 1 else ''} ago"
    else:
        hours = time_diff.seconds // 3600
        if hours > 0:
            time_str = f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            minutes = time_diff.seconds // 60
            time_str = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    

    json_files = []
    if os.path.exists(DATA_FILE_CHANNELS):
        json_files.append("counting_channels.json")
    if os.path.exists(DATA_FILE_GAMES):
        json_files.append("counting_games.json")
    if os.path.exists(DATA_FILE_LEVELS):
        json_files.append("user_levels.json")
    

    if len(json_files) == 6:
        detects_msg = f"detected {', '.join(json_files)}"
    elif len(json_files) > 0:
        detects_msg = f"detected {', '.join(json_files)}"
    else:
        detects_msg = "detected no .json"
    

    with open(__file__, 'r') as f:
        line_count = sum(1 for _ in f)
    

    embed = discord.Embed(
        title="Development Information",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="ping", value=f"{ping_ms}ms", inline=False)
    embed.add_field(name="path", value=f"'{script_path}'", inline=False)
    embed.add_field(name="bot.py was last updated", value=f"{time_str}", inline=False)
    embed.add_field(name="detects", value=detects_msg, inline=False)
    embed.add_field(name="bot.py is", value=f"{line_count} lines long", inline=False)
    embed.set_footer(text="made by vinnypix - https://vinnypix.ca")
    
    await interaction.followup.send(embed=embed)

async def send_shutdown_message():
    
    try:
        status_channel = bot.get_channel(STATUS_CHANNEL_ID)
        if status_channel:
            await status_channel.send("Bot stopping", silent=True)
            print(f"Sent shutdown message to channel {STATUS_CHANNEL_ID}")
        else:
            print(f"Could not find status channel {STATUS_CHANNEL_ID}")
    except Exception as e:
        print(f"Error sending shutdown message: {e}")

def signal_handler(sig, frame):
    
    print("\nShutdown signal received...")
    if bot.is_ready():

        try:
            import requests
            import time
            

            token = os.getenv('DISCORD_TOKEN')
            if token:
                print("Sending shutdown message via API...")
                

                headers = {
                    'Authorization': f'Bot {token}',
                    'Content-Type': 'application/json'
                }
                data = {
                    'content': 'Bot stopping',
                    'flags': 1 << 2
                }
                
                response = requests.post(
                    f'https://discord.com/api/v10/channels/{STATUS_CHANNEL_ID}/messages',
                    headers=headers,
                    json=data,
                    timeout=10
                )
                
                if response.status_code == 200:
                    print(f"Successfully sent shutdown message to channel {STATUS_CHANNEL_ID}")
                else:
                    print(f"Failed to send shutdown message: HTTP {response.status_code}")
                    print(f"Response: {response.text}")
            else:
                print("No Discord token available for shutdown message")
                
        except Exception as e:
            print(f"Error sending shutdown message: {e}")
    else:
        print("Bot not ready, skipping shutdown message")
    

    time.sleep(0.5)
    sys.exit(0)

async def handle_reply_command(message):
    
    try:
        print(f"Processing reply command: {message.content}")
        content = message.content[6:].strip()
        
        if not content:
            await message.reply("Usage: reply [messageID] [message]")
            return
        

        parts = content.split(' ', 1)
        if len(parts) < 2:
            await message.reply("Usage: reply [messageID] [message]")
            return
        
        message_id_str = parts[0]
        reply_content = parts[1]
        
        try:
            target_message_id = int(message_id_str)
        except ValueError:
            await message.reply("Invalid message ID format!")
            return
        

        try:
            target_message = await message.channel.fetch_message(target_message_id)
            

            reply_embed = discord.Embed(
                description=reply_content,
                color=discord.Color.blue()
            )
            reply_embed.set_footer(text=f"Replying to {target_message.author.name}'s message (ID: {target_message.id})")
            
            await message.channel.send(embed=reply_embed, reference=target_message)
            
        except discord.NotFound:
            await message.reply(f"Message with ID `{target_message_id}` not found in this channel!")
        except discord.Forbidden:
            await message.reply("I don't have permission to access that message!")
            
    except Exception as e:
        print(f"Error in handle_reply_command: {e}")
        await message.reply("An error occurred while processing your reply command.")

if __name__ == "__main__":

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("Error: DISCORD_TOKEN not found in environment variables!")
        print("Please create a .env file with your Discord bot token.")
    else:
        bot.run(token)
