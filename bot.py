import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime

# ---------- НАСТРОЙКИ ----------
TOKEN = os.getenv("TOKEN")
MAIN_ADMIN = 1072968512076787744
event_admins = {MAIN_ADMIN}

EVENTS_FILE = "events.json"


# ---------- ЗАГРУЗКА / СОХРАНЕНИЕ ----------
def load_events():
    if not os.path.exists(EVENTS_FILE):
        return {}
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_events(events):
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=4, ensure_ascii=False)


events = load_events()


# ---------- EMBED ----------
def build_event_embed(event_id, data):
    now = datetime.now()
    close_dt = datetime.strptime(data["close_datetime"], "%Y-%m-%d %H:%M")

    is_closed = (
        data.get("force_closed", False)
        or now >= close_dt
        or len(data["participants"]) >= data["limit"]
    )

    status_text = "ЗАКРЫТО" if is_closed else "ОТКРЫТО"

    embed = discord.Embed(
        title=data["title"],
        description="",
        color=0xff4444 if is_closed else 0x44ff44
    )

    embed.add_field(name="Статус", value=f"**{status_text}**", inline=False)

    embed.add_field(
        name="Дата и время",
        value=f"📅 **{data['date']}**   ⏰ **{data['time']}**",
        inline=False
    )

    if data["description"]:
        embed.add_field(name="Описание", value=data["description"], inline=False)

    embed.add_field(
        name="Участники",
        value=f"**{len(data['participants'])} / {data['limit']}**",
        inline=False
    )

    # Список участников с временем записи
    if data["participants"]:
        lines = []
        for i, entry in enumerate(data["participants"], start=1):
            uid = entry["id"]
            t = entry["time"]
            lines.append(f"{i}. <@{uid}> — {t}")
        embed.add_field(name="Список участников", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Список участников", value="Пока никого нет", inline=False)

    if data.get("image"):
        embed.set_image(url=data["image"])

    embed.set_footer(text=f"ID: {event_id}")

    return embed


# ---------- VIEW ----------
class EventView(discord.ui.View):
    def __init__(self, event_id, is_admin):
        super().__init__(timeout=None)
        self.event_id = event_id

        self.add_item(SignUpButton(event_id))
        self.add_item(LeaveButton(event_id))

        if is_admin:
            self.add_item(EditButton(event_id))
            self.add_item(DeleteButton(event_id))
            self.add_item(AddImageButton(event_id))
            self.add_item(ClearParticipantsButton(event_id))
            self.add_item(ForceCloseButton(event_id))


# ---------- КНОПКИ ----------
class SignUpButton(discord.ui.Button):
    def __init__(self, event_id):
        super().__init__(label="Записаться", style=discord.ButtonStyle.success)
        self.event_id = event_id

    async def callback(self, interaction):
        data = events[self.event_id]

        # Запрещаем запись, если закрыто
        if data.get("force_closed", False):
            return await interaction.response.send_message("Мероприятие закрыто.", ephemeral=True)

        now = datetime.now()
        close_dt = datetime.strptime(data["close_datetime"], "%Y-%m-%d %H:%M")
        if now >= close_dt:
            return await interaction.response.send_message("Мероприятие закрыто.", ephemeral=True)

        if len(data["participants"]) >= data["limit"]:
            return await interaction.response.send_message("Лимит участников достигнут!", ephemeral=True)

        # Проверка на повторную запись
        for entry in data["participants"]:
            if entry["id"] == interaction.user.id:
                return await interaction.response.send_message("Ты уже записан!", ephemeral=True)

        # Добавляем участника с временем
        data["participants"].append({
            "id": interaction.user.id,
            "time": datetime.now().strftime("%H:%M:%S")
        })

        save_events(events)

        embed = build_event_embed(self.event_id, data)
        await interaction.message.edit(embed=embed, view=EventView(self.event_id, interaction.user.id in event_admins))
        await interaction.response.send_message("Ты записался!", ephemeral=True)


class LeaveButton(discord.ui.Button):
    def __init__(self, event_id):
        super().__init__(label="Отписаться", style=discord.ButtonStyle.secondary)
        self.event_id = event_id

    async def callback(self, interaction):
        data = events[self.event_id]

        # Отписка запрещена, если закрыто
        if data.get("force_closed", False):
            return await interaction.response.send_message("Мероприятие закрыто.", ephemeral=True)

        now = datetime.now()
        close_dt = datetime.strptime(data["close_datetime"], "%Y-%m-%d %H:%M")
        if now >= close_dt:
            return await interaction.response.send_message("Мероприятие закрыто.", ephemeral=True)

        # Удаляем участника
        before = len(data["participants"])
        data["participants"] = [p for p in data["participants"] if p["id"] != interaction.user.id]

        if len(data["participants"]) == before:
            return await interaction.response.send_message("Ты не записан!", ephemeral=True)

        save_events(events)

        embed = build_event_embed(self.event_id, data)
        await interaction.message.edit(embed=embed, view=EventView(self.event_id, interaction.user.id in event_admins))
        await interaction.response.send_message("Ты отписался.", ephemeral=True)


class EditButton(discord.ui.Button):
    def __init__(self, event_id):
        super().__init__(label="Изменить", style=discord.ButtonStyle.primary)
        self.event_id = event_id

    async def callback(self, interaction):
        if interaction.user.id not in event_admins:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        modal = EditEventModal(self.event_id, events[self.event_id])
        await interaction.response.send_modal(modal)


class DeleteButton(discord.ui.Button):
    def __init__(self, event_id):
        super().__init__(label="Удалить", style=discord.ButtonStyle.danger)
        self.event_id = event_id

    async def callback(self, interaction):
        if interaction.user.id not in event_admins:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        del events[self.event_id]
        save_events(events)

        await interaction.message.delete()
        await interaction.response.send_message("Мероприятие удалено.", ephemeral=True)


class AddImageButton(discord.ui.Button):
    def __init__(self, event_id):
        super().__init__(label="Добавить картинку", style=discord.ButtonStyle.secondary)
        self.event_id = event_id

    async def callback(self, interaction):
        if interaction.user.id not in event_admins:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        await interaction.response.send_message("Прикрепи изображение следующим сообщением.", ephemeral=True)

        def check(msg):
            return msg.author.id == interaction.user.id and msg.attachments

        try:
            msg = await interaction.client.wait_for("message", timeout=60, check=check)
        except:
            return

        attachment = msg.attachments[0]
        if not attachment.content_type.startswith("image/"):
            return await msg.reply("Это не изображение.")

        events[self.event_id]["image"] = attachment.url
        save_events(events)

        embed = build_event_embed(self.event_id, events[self.event_id])
        await interaction.message.edit(embed=embed, view=EventView(self.event_id, True))
        await msg.reply("Картинка обновлена!")


class ClearParticipantsButton(discord.ui.Button):
    def __init__(self, event_id):
        super().__init__(label="Очистить участников", style=discord.ButtonStyle.danger)
        self.event_id = event_id

    async def callback(self, interaction):
        if interaction.user.id not in event_admins:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        events[self.event_id]["participants"] = []
        save_events(events)

        embed = build_event_embed(self.event_id, events[self.event_id])
        await interaction.message.edit(embed=embed, view=EventView(self.event_id, True))
        await interaction.response.send_message("Участники очищены.", ephemeral=True)


class ForceCloseButton(discord.ui.Button):
    def __init__(self, event_id):
        super().__init__(label="Закрыть", style=discord.ButtonStyle.danger)
        self.event_id = event_id

    async def callback(self, interaction):
        if interaction.user.id not in event_admins:
            return await interaction.response.send_message("Нет прав.", ephemeral=True)

        events[self.event_id]["force_closed"] = True
        save_events(events)

        embed = build_event_embed(self.event_id, events[self.event_id])
        await interaction.message.edit(embed=embed, view=EventView(self.event_id, True))
        await interaction.response.send_message("Мероприятие закрыто.", ephemeral=True)


# ---------- MODAL ----------
class EditEventModal(discord.ui.Modal, title="Изменить мероприятие"):
    def __init__(self, event_id, data):
        super().__init__()
        self.event_id = event_id

        self.title_input = discord.ui.TextInput(label="Название", default=data["title"])
        self.date_input = discord.ui.TextInput(label="Дата", default=data["date"])
        self.time_input = discord.ui.TextInput(label="Время", default=data["time"])
        self.desc_input = discord.ui.TextInput(label="Описание", default=data["description"], style=discord.TextStyle.paragraph)
        self.limit_input = discord.ui.TextInput(label="Лимит", default=str(data["limit"]))

        self.add_item(self.title_input)
        self.add_item(self.date_input)
        self.add_item(self.time_input)
        self.add_item(self.desc_input)
        self.add_item(self.limit_input)

    async def on_submit(self, interaction):
        data = events[self.event_id]

        data["title"] = self.title_input.value
        data["date"] = self.date_input.value
        data["time"] = self.time_input.value
        data["description"] = self.desc_input.value
        data["limit"] = int(self.limit_input.value)
        data["close_datetime"] = f"{data['date']} {data['time']}"

        save_events(events)

        embed = build_event_embed(self.event_id, data)
        await interaction.message.edit(embed=embed, view=EventView(self.event_id, interaction.user.id in event_admins))
        await interaction.response.send_message("Мероприятие обновлено!", ephemeral=True)


# ---------- СОЗДАНИЕ ----------
class CreateEventModal(discord.ui.Modal, title="Создать мероприятие"):
    title_input = discord.ui.TextInput(label="Название")
    date_input = discord.ui.TextInput(label="Дата (формат: 2026-03-10)")
    time_input = discord.ui.TextInput(label="Время (формат: 21:40)")
    desc_input = discord.ui.TextInput(label="Описание", style=discord.TextStyle.paragraph)
    limit_input = discord.ui.TextInput(label="Лимит")

    async def on_submit(self, interaction):
        event_id = str(int(datetime.now().timestamp()))

        events[event_id] = {
            "title": self.title_input.value,
            "date": self.date_input.value,
            "time": self.time_input.value,
            "description": self.desc_input.value,
            "limit": int(self.limit_input.value),
            "participants": [],
            "image": None,
            "force_closed": False,
            "close_datetime": f"{self.date_input.value} {self.time_input.value}"
        }

        save_events(events)

        embed = build_event_embed(event_id, events[event_id])
        await interaction.response.send_message(
            embed=embed,
            view=EventView(event_id, interaction.user.id in event_admins)
        )


# ---------- БОТ ----------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print("Бот запущен!")


@bot.tree.command(name="event_create", description="Создать мероприятие")
async def event_create(interaction: discord.Interaction):
    if interaction.user.id not in event_admins:
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await interaction.response.send_modal(CreateEventModal())


@bot.tree.command(name="addadmin", description="Добавить администратора")
@app_commands.describe(user="Пользователь")
async def addadmin(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != MAIN_ADMIN:
        return await interaction.response.send_message("Только главный админ может добавлять админов.", ephemeral=True)

    event_admins.add(user.id)
    await interaction.response.send_message(f"{user.mention} теперь админ!", ephemeral=True)

@bot.tree.command(name="flood", description="Отправить 10 одинаковых сообщений")
@app_commands.describe(text="Текст, который нужно отправить 10 раз")
async def flood(interaction: discord.Interaction, text: str):
    # Только админы
    if interaction.user.id not in event_admins:
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await interaction.response.send_message("Флуд запущен!", ephemeral=True)

    for _ in range(10):
        await interaction.channel.send(text)

@bot.tree.command(name="spam", description="Отправить 10 сообщений с упоминанием пользователя")
@app_commands.describe(user="Кого спамить", text="Текст сообщения")
async def spam(interaction: discord.Interaction, user: discord.User, text: str):
    # Только админы
    if interaction.user.id not in event_admins:
        return await interaction.response.send_message("Нет прав.", ephemeral=True)

    await interaction.response.send_message("Спам запущен!", ephemeral=True)

    for _ in range(10):
        await interaction.channel.send(f"{user.mention} {text}")

bot.run(TOKEN)
