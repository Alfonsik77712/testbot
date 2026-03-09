import os
import json
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta

# ---------- НАСТРОЙКИ ----------
MAIN_ADMIN = 1072968512076787744
event_admins = {MAIN_ADMIN}

TOKEN = os.getenv("TOKEN")
MSK = timezone(timedelta(hours=3))
DATA_FILE = "events.json"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- ХРАНЕНИЕ ----------
events = {}
event_messages = {}
main_messages = {}

# ---------- ЗАГРУЗКА ----------
def load_data():
    global events, event_messages, main_messages, event_admins
    if not os.path.exists(DATA_FILE):
        return
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events", {})
    event_messages = data.get("event_messages", {})
    main_messages = data.get("main_messages", {})
    event_admins.update(data.get("event_admins", []))

# ---------- СОХРАНЕНИЕ ----------
def save_data():
    data = {
        "events": events,
        "event_messages": event_messages,
        "main_messages": main_messages,
        "event_admins": list(event_admins)
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ---------- EMBED МЕРОПРИЯТИЯ ----------
def make_event_embed(event: dict) -> discord.Embed:
    users_text = "\n".join(
        [f"{i+1}. <@{uid}> — {t}" for i, (uid, t) in enumerate(event["users"].items())]
    ) or "Пока пусто"

    status = "Открыто" if not event["closed"] else "Закрыто"

    embed = discord.Embed(
        title=event["name"],
        description=(
            f"**Описание:**\n{event['description']}\n\n"
            f"**Статус:** {status}\n"
            f"**Мест:** {len(event['users'])}/{event['max']}\n"
            f"**Закрытие:** {event['close_time']}\n\n"
            f"**Участники:**\n{users_text}"
        ),
        color=0x2f3136 if not event["closed"] else 0x555555,
    )

    if event.get("image_url"):
        embed.set_image(url=event["image_url"])

    return embed

# ---------- EMBED СПИСКА ----------
def make_list_embed(events_dict: dict) -> discord.Embed:
    if not events_dict:
        desc = "Пока нет мероприятий"
    else:
        desc = "\n".join(
            [f"**#{eid}** — {ev['name']} ({len(ev['users'])}/{ev['max']})"
             for eid, ev in events_dict.items()]
        )
    return discord.Embed(title="Список мероприятий", description=desc, color=0x2f3136)

# ---------- VIEW ----------
class EventView(discord.ui.View):
    def __init__(self, guild_id, channel_id, event_id, is_admin=False):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event_id = event_id

        if not is_admin:
            self.children = [self.children[0], self.children[1]]

    @discord.ui.button(label="Записаться", style=discord.ButtonStyle.primary)
    async def join(self, interaction, button):
        await handle_join(interaction, self.guild_id, self.channel_id, self.event_id)

    @discord.ui.button(label="Отписаться", style=discord.ButtonStyle.danger)
    async def leave(self, interaction, button):
        await handle_leave(interaction, self.guild_id, self.channel_id, self.event_id)

    @discord.ui.button(label="Изменить", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction, button):
        if interaction.user.id not in event_admins:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        gid, cid, eid = str(self.guild_id), str(self.channel_id), str(self.event_id)
        event = events[gid][cid][eid]

        modal = EventEditModal(
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            event_id=self.event_id,
            name=event["name"],
            max_people=str(event["max"]),
            close_time=event["close_time"],
            description=event["description"]
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.red)
    async def delete(self, interaction, button):
        if interaction.user.id not in event_admins:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        gid, cid, eid = str(self.guild_id), str(self.channel_id), str(self.event_id)

        msg_id = event_messages[gid][cid][eid]
        try:
            msg = await interaction.channel.fetch_message(msg_id)
            await msg.delete()
        except:
            pass

        del events[gid][cid][eid]
        del event_messages[gid][cid][eid]

        await update_list(self.guild_id, interaction.channel)
        save_data()

        await interaction.response.send_message("Мероприятие удалено.", ephemeral=True)

# ---------- ОБНОВЛЕНИЕ СПИСКА ----------
async def update_list(guild_id, channel):
    gid = str(guild_id)
    cid = str(channel.id)

    embed = make_list_embed(events.get(gid, {}).get(cid, {}))

    if gid not in main_messages:
        main_messages[gid] = {}

    if cid not in main_messages[gid]:
        msg = await channel.send(embed=embed)
        main_messages[gid][cid] = msg.id
        save_data()
        return

    try:
        msg = await channel.fetch_message(main_messages[gid][cid])
        await msg.edit(embed=embed)
    except discord.NotFound:
        msg = await channel.send(embed=embed)
        main_messages[gid][cid] = msg.id

    save_data()

# ---------- ЗАПИСЬ ----------
async def handle_join(interaction, guild_id, channel_id, event_id):
    gid, cid, eid = str(guild_id), str(channel_id), str(event_id)
    event = events[gid][cid][eid]

    if event["closed"]:
        return await interaction.response.send_message("Мероприятие закрыто.", ephemeral=True)

    if str(interaction.user.id) in event["users"]:
        return await interaction.response.send_message("Ты уже записан!", ephemeral=True)

    if len(event["users"]) >= event["max"]:
        return await interaction.response.send_message("Мест больше нет!", ephemeral=True)

    now = datetime.now(MSK).strftime("%H:%M:%S")
    event["users"][str(interaction.user.id)] = now

    msg_id = event_messages[gid][cid][eid]
    msg = await interaction.channel.fetch_message(msg_id)

    is_admin = interaction.user.id in event_admins
    await msg.edit(embed=make_event_embed(event), view=EventView(guild_id, channel_id, event_id, is_admin))

    await update_list(guild_id, interaction.channel)
    save_data()

    await interaction.response.send_message("Ты записан!", ephemeral=True)

async def handle_leave(interaction, guild_id, channel_id, event_id):
    gid, cid, eid = str(guild_id), str(channel_id), str(event_id)
    event = events[gid][cid][eid]

    if str(interaction.user.id) not in event["users"]:
        return await interaction.response.send_message("Ты не записан.", ephemeral=True)

    del event["users"][str(interaction.user.id)]

    msg_id = event_messages[gid][cid][eid]
    msg = await interaction.channel.fetch_message(msg_id)

    is_admin = interaction.user.id in event_admins
    await msg.edit(embed=make_event_embed(event), view=EventView(guild_id, channel_id, event_id, is_admin))

    await update_list(guild_id, interaction.channel)
    save_data()

    await interaction.response.send_message("Ты отписался.", ephemeral=True)

# ---------- АВТО‑ЗАКРЫТИЕ ----------
@tasks.loop(seconds=10)
async def auto_close_events():
    now = datetime.now(MSK)

    for gid, channels in events.items():
        for cid, channel_events in channels.items():
            channel = bot.get_channel(int(cid))
            if not channel:
                continue

            changed = False

            for eid, event in channel_events.items():
                close_dt = datetime.strptime(event["close_time"], "%Y-%m-%d %H:%M").replace(tzinfo=MSK)

                if not event["closed"] and now >= close_dt:
                    event["closed"] = True
                    changed = True

                    msg_id = event_messages[gid][cid][eid]
                    try:
                        msg = await channel.fetch_message(msg_id)
                        await msg.edit(embed=make_event_embed(event), view=None)
                    except:
                        pass

            if changed:
                await update_list(int(gid), channel)
                save_data()

# ---------- MODAL СОЗДАНИЯ ----------
class EventCreateModal(discord.ui.Modal, title="Создание мероприятия"):
    name = discord.ui.TextInput(label="Название", max_length=100)
    max_people = discord.ui.TextInput(label="Максимум участников", max_length=3)
    close_time = discord.ui.TextInput(label="Дата закрытия (YYYY-MM-DD HH:MM)")
    description = discord.ui.TextInput(label="Описание", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        gid = str(interaction.guild.id)
        cid = str(interaction.channel.id)

        events.setdefault(gid, {})
        events[gid].setdefault(cid, {})

        try:
            datetime.strptime(self.close_time.value, "%Y-%m-%d %H:%M")
        except:
            return await interaction.response.send_message("Неверный формат даты.", ephemeral=True)

        event_id = str(max(map(int, events[gid][cid].keys()), default=0) + 1)

        events[gid][cid][event_id] = {
            "name": self.name.value,
            "max": int(self.max_people.value),
            "description": self.description.value,
            "users": {},
            "close_time": self.close_time.value,
            "image_url": None,
            "closed": False,
        }

        event_messages.setdefault(gid, {})
        event_messages[gid].setdefault(cid, {})

        await update_list(int(gid), interaction.channel)

        msg = await interaction.channel.send(
            embed=make_event_embed(events[gid][cid][event_id]),
            view=EventView(int(gid), int(cid), int(event_id), True)
        )
        event_messages[gid][cid][event_id] = msg.id

        save_data()
        await interaction.response.send_message(f"Мероприятие #{event_id} создано!", ephemeral=True)

# ---------- MODAL РЕДАКТИРОВАНИЯ ----------
class EventEditModal(discord.ui.Modal, title="Редактирование мероприятия"):
    def __init__(self, guild_id, channel_id, event_id, name, max_people, close_time, description):
        super().__init__()
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.event_id = event_id

        self.name = discord.ui.TextInput(label="Название", default=name, max_length=100)
        self.max_people = discord.ui.TextInput(label="Максимум участников", default=max_people)
        self.close_time = discord.ui.TextInput(label="Дата закрытия (YYYY-MM-DD HH:MM)", default=close_time)
        self.description = discord.ui.TextInput(label="Описание", style=discord.TextStyle.paragraph, default=description)

        self.add_item(self.name)
        self.add_item(self.max_people)
        self.add_item(self.close_time)
        self.add_item(self.description)

    async def on_submit(self, interaction):
        gid, cid, eid = str(self.guild_id), str(self.channel_id), str(self.event_id)

        try:
            datetime.strptime(self.close_time.value, "%Y-%m-%d %H:%M")
        except:
            return await interaction.response.send_message("Неверный формат даты.", ephemeral=True)

        event = events[gid][cid][eid]
        event["name"] = self.name.value
        event["max"] = int(self.max_people.value)
        event["close_time"] = self.close_time.value
        event["description"] = self.description.value

        msg_id = event_messages[gid][cid][eid]
        msg = await interaction.channel.fetch_message(msg_id)

        await msg.edit(embed=make_event_embed(event),
                       view=EventView(self.guild_id, self.channel_id, self.event_id, True))

        await update_list(self.guild_id, interaction.channel)
        save_data()

        await interaction.response.send_message("Мероприятие обновлено!", ephemeral=True)

# ---------- КОМАНДЫ ----------
@bot.tree.command(name="event_create", description="Создать мероприятие (Modal)")
async def event_create(interaction):
    if interaction.user.id not in event_admins:
        return await interaction.response.send_message("Нет прав.", ephemeral=True)
    await interaction.response.send_modal(EventCreateModal())

@bot.tree.command(name="add_image", description="Добавить изображение к мероприятию")
async def add_image(interaction, event_id: int):
    if interaction.user.id not in event_admins:
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    gid = str(interaction.guild.id)
    cid = str(interaction.channel.id)
    eid = str(event_id)

    if gid not in events or cid not in events[gid] or eid not in events[gid][cid]:
        return await interaction.response.send_message("Мероприятие не найдено.", ephemeral=True)

    await interaction.response.send_message("Прикрепи изображение следующим сообщением.", ephemeral=True)

    def check(msg):
        return msg.author.id == interaction.user.id and msg.channel.id == interaction.channel.id and msg.attachments

    try:
        msg = await bot.wait_for("message", timeout=60, check=check)
    except:
        return await interaction.followup.send("Время вышло.", ephemeral=True)

    url = msg.attachments[0].url
    events[gid][cid][eid]["image_url"] = url
    save_data()

    msg_id = event_messages[gid][cid][eid]
    event_msg = await interaction.channel.fetch_message(msg_id)
    await event_msg.edit(embed=make_event_embed(events[gid][cid][eid]),
                         view=EventView(int(gid), int(cid), int(eid), True))

    await interaction.followup.send("Изображение добавлено!", ephemeral=True)

# ---------- ON_READY ----------
@bot.event
async def on_ready():
    load_data()
    await bot.tree.sync()
    auto_close_events.start()
    print(f"Бот запущен как {bot.user}")

bot.run(TOKEN)
