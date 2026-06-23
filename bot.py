# ---------------- IMPORTACIONES ----------------
from flask import Flask
from threading import Thread
import os
import discord
from discord import app_commands
from discord.ui import Select, View, Button
from discord.ext import commands, tasks
import sqlite3
from datetime import datetime
import pytz

# ---------------- ⚠️ CONFIGURA ESTO ⚠️ ----------------
TOKEN = os.getenv("TOKEN")
MI_SERVIDOR_ID = 1406902399968481422       # Pon tu ID de servidor
ROL_MODERADOR_ID = 1518449563915124887     # Pon tu ID de rol moderador

TIMEZONE = pytz.timezone("UTC")
RECORDATORIOS = [60, 15]

PING_ANUNCIO = "<@&1419881877287997542> 📢 ¡Nuevo ping de ava! Revisa las inscripciones 👇"
TEXTO_PIE = "© Misa Amane | Sistema de eventos oficial"
URL_ICONO_PIE = None

# 🎯 Tus roles y emojis
ROLES_ALBION = {
    "Caller": (discord.PartialEmoji(name="caller", id=1518950627047243909), 1),
    "Off-Tank": (discord.PartialEmoji(name="offtank", id=1518950734408716369), 1),
    "Healer": (discord.PartialEmoji(name="healer", id=1518950811621654731), 1),
    "Cobra": (discord.PartialEmoji(name="cobra", id=1518950873319997460), 1),
    "ShadowCaller": (discord.PartialEmoji(name="shadowcaller", id=1518950955079438427), 1),
    "Dps-Soporte": (discord.PartialEmoji(name="soporte", id=1518995821021102150), 1),
    "Dps": (discord.PartialEmoji(name="dps", id=1518951113460547646), 6)
}
# ------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

def init_db():
    db_path = os.path.join(os.path.dirname(__file__), "eventos_bot.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS plantillas
                 (nombre TEXT PRIMARY KEY, datos TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS eventos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  mensaje_id INTEGER, titulo TEXT, fecha TEXT, hora TEXT,
                  fecha_hora TEXT, descripcion TEXT, imagen_url TEXT,
                  roles TEXT, suplentes TEXT, recordatorios_enviados TEXT DEFAULT '',
                  estado TEXT DEFAULT 'activo',  -- Nuevo campo para saber si está cancelado
                  canal_id INTEGER, creador_id INTEGER)''')
    conn.commit()
    conn.close()

init_db()

def tiempo_restante(fecha_evento):
    ahora = datetime.now(TIMEZONE)
    if fecha_evento <= ahora:
        return "⏰ **Evento en curso o finalizado**"
    delta = fecha_evento - ahora
    if delta.days > 0:
        return f"⏳ Faltan **{delta.days}d {delta.seconds//3600}h {(delta.seconds%3600)//60}m**"
    elif delta.seconds >= 3600:
        return f"⏳ Faltan **{delta.seconds//3600}h {(delta.seconds%3600)//60}m**"
    else:
        return f"⏳ Faltan **{(delta.seconds%3600)//60}m**"

@tasks.loop(minutes=1)
async def actualizar_eventos():
    db_path = os.path.join(os.path.dirname(__file__), "eventos_bot.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM eventos WHERE estado = 'activo'")
    eventos = c.fetchall()
    for ev in eventos:
        try:
            ev_id, msg_id, titulo, fecha, hora, fecha_hora_str, desc, img, roles_str, suplentes_str, rec_str, estado, canal_id, creador_id = ev
            fecha_hora = datetime.fromisoformat(fecha_hora_str).replace(tzinfo=TIMEZONE)
            rec_enviados = list(map(int, rec_str.split(","))) if rec_str else []

            canal = bot.get_channel(canal_id)
            if not canal: continue
            try: mensaje = await canal.fetch_message(msg_id)
            except: continue

            embed = mensaje.embeds[0]
            tiempo = tiempo_restante(fecha_hora)
            embed.description = f"""
📅 **Fecha:** {fecha}
🕒 **Hora:** {hora} (UTC / Hora del juego)

{tiempo}

📝 **Detalles:**
{desc}
"""
            embed.set_footer(text=TEXTO_PIE, icon_url=URL_ICONO_PIE)

            delta_min = (fecha_hora - datetime.now(TIMEZONE)).total_seconds() / 60
            for min_rec in RECORDATORIOS:
                if min_rec not in rec_enviados and (min_rec - 1) <= delta_min <= (min_rec + 1):
                    roles = eval(roles_str)
                    suplentes = eval(suplentes_str)
                    menciones = []
                    for r in roles.values():
                        for m in r["miembros"]: menciones.append(f"<@{m['id']}>")
                    for s in suplentes: menciones.append(f"<@{s['id']}>")
                    if menciones:
                        await canal.send(f"🔔 **Recordatorio:** Faltan {min_rec} min para **{titulo}**!\n{' '.join(menciones)}")
                    rec_enviados.append(min_rec)
                    c.execute("UPDATE eventos SET recordatorios_enviados = ? WHERE id = ?", (",".join(map(str, rec_enviados)), ev_id))
                    conn.commit()
            await mensaje.edit(embed=embed)
        except Exception as e:
            print(f"Actualizar error: {e}")
            continue
    conn.close()

# ---------------- COMPONENTES ----------------
class SeleccionRol(Select):
    def __init__(self, datos_evento):
        self.datos = datos_evento
        opciones = []
        for nombre, info in self.datos["roles"].items():
            libres = info["cupo"] - len(info["miembros"])
            if libres > 0:
                opciones.append(discord.SelectOption(label=f"{nombre} ({libres} libres)", value=nombre, emoji=info["emoji"]))
        super().__init__(placeholder="👉 Elige tu rol para inscribirte", min_values=1, max_values=1, options=opciones[:25])

    async def callback(self, interaction: discord.Interaction):
        rol = self.values[0]
        info = self.datos["roles"][rol]
        uid = interaction.user.id
        ya = any(uid == m["id"] for r in self.datos["roles"].values() for m in r["miembros"]) or any(uid == s["id"] for s in self.datos["suplentes"])
        if ya: return await interaction.response.send_message("⚠️ Ya estás inscrito en este evento", ephemeral=True)
        if len(info["miembros"]) >= info["cupo"]: return await interaction.response.send_message("❌ Cupo lleno, elige otro rol o ve a suplente", ephemeral=True)
        info["miembros"].append({"id": uid})
        await actualizar_visual(interaction, self.datos)
        await interaction.response.send_message(f"✅ Inscrito como **{rol}**", ephemeral=True)


class SeleccionSuplente(Select):
    def __init__(self, datos_evento):
        self.datos = datos_evento
        opciones = [discord.SelectOption(label=f"Suplente: {n}", value=n, emoji=e["emoji"]) for n,e in datos_evento["roles"].items()]
        super().__init__(placeholder="🪑 Elige rol para ser suplente", min_values=1, max_values=1, options=opciones[:25])

    async def callback(self, interaction: discord.Interaction):
        rol = self.values[0]
        uid = interaction.user.id
        ya_inscrito = any(uid == m["id"] for r in self.datos["roles"].values() for m in r["miembros"]) or any(uid == s["id"] for s in self.datos["suplentes"])
        if ya_inscrito:
            return await interaction.response.send_message("⚠️ Ya estás inscrito como titular o suplente", ephemeral=True)
        self.datos["suplentes"].append({"id": uid, "rol": rol, "emoji": str(self.datos["roles"][rol]["emoji"])})
        await actualizar_visual(interaction, self.datos)
        await interaction.response.send_message(f"🪑 Anotado como suplente de **{rol}**", ephemeral=True)


class BotonBanquillo(Button):
    def __init__(self, datos):
        super().__init__(label="Banquillo", style=discord.ButtonStyle.secondary, emoji="🪑")
        self.datos = datos
    async def callback(self, i):
        vista = View(timeout=60)
        vista.add_item(SeleccionSuplente(self.datos))
        await i.response.send_message("Elige el rol para ser suplente:", view=vista, ephemeral=True)


class BotonCancelar(Button):
    def __init__(self, datos):
        super().__init__(label="Cancelar", style=discord.ButtonStyle.danger, emoji="❌")
        self.datos = datos
    async def callback(self, i):
        uid = i.user.id
        eliminado = False
        for r in self.datos["roles"].values():
            if any(m["id"] == uid for m in r["miembros"]):
                r["miembros"] = [m for m in r["miembros"] if m["id"] != uid]
                eliminado = True
                break
        if not eliminado:
            self.datos["suplentes"] = [s for s in self.datos["suplentes"] if s["id"] != uid]
            eliminado = True
        if eliminado:
            await actualizar_visual(i, self.datos)
            await i.response.send_message("✅ Inscripción cancelada", ephemeral=True)
        else:
            await i.response.send_message("ℹ️ No estabas inscrito", ephemeral=True)


class BotonGestionar(Button):
    def __init__(self, datos):
        super().__init__(label="Gestionar", style=discord.ButtonStyle.primary, emoji="⚙️")
        self.datos = datos

    async def callback(self, i: discord.Interaction):
        if not any(role.id == ROL_MODERADOR_ID for role in i.user.roles):
            return await i.response.send_message("❌ Solo moderadores pueden usar esta opción", ephemeral=True)

        opciones = []
        for rol_nombre, info_rol in self.datos["roles"].items():
            for miembro in info_rol["miembros"]:
                usuario = i.guild.get_member(miembro["id"])
                nombre = usuario.display_name if usuario else f"ID:{miembro['id']}"
                opciones.append(
                    discord.SelectOption(
                        label=f"{rol_nombre} | {nombre}",
                        value=f"titular:{rol_nombre}:{miembro['id']}",
                        emoji=info_rol["emoji"]
                    )
                )
        for suplente in self.datos["suplentes"]:
            usuario = i.guild.get_member(suplente["id"])
            nombre = usuario.display_name if usuario else f"ID:{suplente['id']}"
            opciones.append(
                discord.SelectOption(
                    label=f"Suplente {suplente['rol']} | {nombre}",
                    value=f"suplente:{suplente['rol']}:{suplente['id']}",
                    emoji=suplente["emoji"]
                )
            )

        if not opciones:
            return await i.response.send_message("ℹ️ No hay participantes inscritos aún", ephemeral=True)

        class MenuExpulsar(Select):
            def __init__(self, datos):
                self.datos = datos
                super().__init__(placeholder="Selecciona para quitar de la actividad", options=opciones[:25], min_values=1, max_values=1)

            async def callback(self, inter: discord.Interaction):
                if not any(role.id == ROL_MODERADOR_ID for role in inter.user.roles):
                    return await inter.response.send_message("❌ Sin permisos", ephemeral=True)

                tipo, rol, usuario_id = self.values[0].split(":")
                usuario_id = int(usuario_id)
                usuario = inter.guild.get_member(usuario_id)
                eliminado = False

                if tipo == "titular":
                    self.datos["roles"][rol]["miembros"] = [m for m in self.datos["roles"][rol]["miembros"] if m["id"] != usuario_id]
                    eliminado = True
                elif tipo == "suplente":
                    self.datos["suplentes"] = [s for s in self.datos["suplentes"] if s["id"] != usuario_id]
                    eliminado = True

                if eliminado:
                    if usuario:
                        try:
                            await usuario.send(f"⚠️ Has sido eliminado del evento **{inter.message.embeds[0].title}**.\nSi quieres volver a participar, puedes anotarte nuevamente mientras haya cupo.")
                        except:
                            pass

                    db_path = os.path.join(os.path.dirname(__file__), "eventos_bot.db")
                    conn = sqlite3.connect(db_path)
                    c = conn.cursor()
                    c.execute("UPDATE eventos SET roles=?, suplentes=? WHERE mensaje_id=?",
                              (str(self.datos["roles"]), str(self.datos["suplentes"]), inter.message.id))
                    conn.commit()
                    conn.close()

                    await actualizar_visual(inter, self.datos)
                    await inter.response.send_message(f"✅ Usuario eliminado correctamente", ephemeral=True)
                else:
                    await inter.response.send_message("❌ No se pudo encontrar al usuario", ephemeral=True)

        vista = View(timeout=60)
        vista.add_item(MenuExpulsar(self.datos))
        await i.response.send_message("📋 **Lista de participantes**\nElige a quien quieras quitar:", view=vista, ephemeral=True)


# ✅ NUEVO BOTÓN: CALL OUT
class BotonCallOut(Button):
    def __init__(self, datos):
        super().__init__(label="Call Out", style=discord.ButtonStyle.danger, emoji="🚫")
        self.datos = datos

    async def callback(self, i: discord.Interaction):
        # Solo moderadores
        if not any(role.id == ROL_MODERADOR_ID for role in i.user.roles):
            return await i.response.send_message("❌ Solo moderadores pueden cancelar eventos", ephemeral=True)

        embed = i.message.embeds[0]
        embed.title = f"❌ EVENTO CANCELADO | {embed.title}"
        embed.description = f"""
📅 **Fecha:** {embed.description.split('**Fecha:**')[1].split('**Hora:**')[0].strip()}
🕒 **Hora:** {embed.description.split('**Hora:**')[1].split('**Detalles:**')[0].strip()}

⚠️ **MOTIVO:** Cancelado por falta de participantes o decisión de organización.

📝 **Detalles:**
{embed.description.split('**Detalles:**')[1].strip()}
"""
        embed.clear_fields()
        embed.add_field(name="❌ Estado", value="Este evento ha sido cerrado y ya no se aceptan inscripciones.", inline=False)
        embed.color = discord.Color.red()

        # Desactivar todos los botones
        vista_desactivada = View()
        for item in i.message.components[0].children:
            item.disabled = True
            vista_desactivada.add_item(item)

        await i.message.edit(embed=embed, view=vista_desactivada)

        # Guardar como cancelado en la base de datos
        db_path = os.path.join(os.path.dirname(__file__), "eventos_bot.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("UPDATE eventos SET estado = 'cancelado', recordatorios_enviados = 'todos' WHERE mensaje_id = ?", (i.message.id,))
        conn.commit()
        conn.close()

        await i.response.send_message("✅ Evento cancelado y cerrado correctamente", ephemeral=True)


async def actualizar_visual(interaction, datos):
    try:
        msg = interaction.message
        if not msg or not msg.embeds:
            return

        embed = discord.Embed(
            title=msg.embeds[0].title,
            description=msg.embeds[0].description,
            color=msg.embeds[0].color
        )

        if msg.embeds[0].image:
            embed.set_image(url=msg.embeds[0].image.url)

        for nombre, info in datos["roles"].items():
            nombres = ", ".join(f"<@{m['id']}>" for m in info["miembros"]) or "-"
            embed.add_field(
                name=f"{info['emoji']} {nombre} ({len(info['miembros'])}/{info['cupo']})",
                value=nombres,
                inline=False
            )

        suplentes_txt = "\n".join(f"{s['emoji']} <@{s['id']}>" for s in datos["suplentes"]) or "-"
        embed.add_field(name="🪑 Banquillo / Suplentes", value=suplentes_txt, inline=False)

        embed.set_footer(text=TEXTO_PIE, icon_url=URL_ICONO_PIE)

        # ✅ Agregamos el nuevo botón aquí
        vista = View(timeout=None)
        vista.add_item(SeleccionRol(datos))
        vista.add_item(BotonBanquillo(datos))
        vista.add_item(BotonCancelar(datos))
        vista.add_item(BotonGestionar(datos))
        vista.add_item(BotonCallOut(datos))  # Nuevo botón

        await msg.edit(embed=embed, view=vista)

        db_path = os.path.join(os.path.dirname(__file__), "eventos_bot.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("UPDATE eventos SET roles=?, suplentes=? WHERE mensaje_id=?",
                  (str(datos["roles"]), str(datos["suplentes"]), msg.id))
        conn.commit()
        conn.close()

    except Exception as e:
        print(f"Error actualizando visual: {e}")


# ---------------- INICIO DEL BOT ----------------
@bot.event
async def on_ready():
    guild = discord.Object(id=MI_SERVIDOR_ID)
    await tree.sync(guild=guild)
    print(f"✅ Bot conectado: {bot.user}")
    print("✅ Comandos sincronizados | Zona horaria: UTC")

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Developer • Misa Amane"
        ),
        status=discord.Status.online
    )

    actualizar_eventos.start()


@tree.command(name="crear_evento", description="Crear evento en hora UTC del juego")
@app_commands.describe(
    titulo="Ej: GO AVA / ZV / MIST",
    fecha="DD/MM/AAAA",
    hora="HH:MM (hora UTC)",
    descripcion="Detalles del evento",
    imagen="URL de imagen opcional"
)
async def crear_evento(interaction: discord.Interaction, titulo: str, fecha: str, hora: str, descripcion: str = "", imagen: str = None):
    try:
        fecha_hora = TIMEZONE.localize(datetime.strptime(f"{fecha} {hora}", "%d/%m/%Y %H:%M"))
    except:
        return await interaction.response.send_message("❌ Fecha/hora inválida. Usa formato DD/MM/AAAA HH:MM en hora UTC", ephemeral=True)

    datos = {"roles": {n: {"emoji": e, "cupo": c, "miembros": []} for n,(e,c) in ROLES_ALBION.items()}, "suplentes": []}
    tiempo = tiempo_restante(fecha_hora)

    embed = discord.Embed(color=0x2C2F33, title=titulo, description=f"""
📅 **Fecha:** {fecha}
🕒 **Hora:** {hora} (UTC / Hora del juego)

{tiempo}

📝 **Detalles:**
{descripcion}
""")
    if imagen: embed.set_image(url=imagen)
    embed.set_footer(text=TEXTO_PIE, icon_url=URL_ICONO_PIE)

    for n, inf in datos["roles"].items():
        embed.add_field(name=f"{inf['emoji']} {n} (0/{inf['cupo']})", value="-", inline=False)
    embed.add_field(name="🪑 Banquillo / Suplentes", value="-", inline=False)

    vista = View(timeout=None)
    vista.add_item(SeleccionRol(datos))
    vista.add_item(BotonBanquillo(datos))
    vista.add_item(BotonCancelar(datos))
    vista.add_item(BotonGestionar(datos))
    vista.add_item(BotonCallOut(datos))  # Nuevo botón en eventos nuevos

    await interaction.channel.send(PING_ANUNCIO)
    msg = await interaction.channel.send(embed=embed, view=vista)
    await interaction.response.send_message("✅ Evento creado correctamente", ephemeral=True)

    try:
        db_path = os.path.join(os.path.dirname(__file__), "eventos_bot.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("INSERT INTO eventos (mensaje_id, titulo, fecha, hora, fecha_hora, descripcion, imagen_url, roles, suplentes, recordatorios_enviados, estado, canal_id, creador_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (msg.id, titulo, fecha, hora, fecha_hora.isoformat(), descripcion, imagen, str(datos["roles"]), str(datos["suplentes"]), "", "activo", interaction.channel.id, interaction.user.id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error guardando en BD: {e}")


@tree.command(name="guardar_plantilla", description="Guardar configuración de roles")
async def guardar_plantilla(interaction: discord.Interaction, nombre: str):
    db_path = os.path.join(os.path.dirname(__file__), "eventos_bot.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO plantillas VALUES (?, ?)", (nombre.lower(), str(ROLES_ALBION)))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Plantilla '{nombre}' guardada", ephemeral=True)


@tree.command(name="usar_plantilla", description="Cargar plantilla de roles")
async def usar_plantilla(interaction: discord.Interaction, nombre: str):
    db_path = os.path.join(os.path.dirname(__file__), "eventos_bot.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT datos FROM plantillas WHERE nombre=?", (nombre.lower(),))
    res = c.fetchone()
    conn.close()
    if res:
        global ROLES_ALBION
        ROLES_ALBION = eval(res[0])
        await interaction.response.send_message(f"✅ Plantilla '{nombre}' cargada", ephemeral=True)
    else:
        await interaction.response.send_message("❌ No se encontró la plantilla", ephemeral=True)

app = Flask("")
@app.route("/")
def ping():
    return "Bot activo ✅"

def run_web():
    app.run(host="0.0.0.0", port=10000)  # Puerto obligatorio en Render

def mantener_encendido():
    t = Thread(target=run_web, daemon=True)
    t.start()

# --- LLÁMALO JUSTO ANTES DE bot.run() ---
mantener_encendido()
bot.run(TOKEN)
