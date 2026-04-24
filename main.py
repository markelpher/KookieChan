import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
import discord
from database.mongo import init_database, close_mongo_client

# -----------------------------
# Configuração inicial
# -----------------------------

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="none", intents=intents)

slash_synced = False


def is_unknown_interaction_error(error) -> bool:
    base_error = getattr(error, "original", error)
    return isinstance(base_error, discord.NotFound) and getattr(base_error, "code", None) == 10062

# -----------------------------
# Carregamento de cogs
# -----------------------------

async def load_cog(cog_name: str):
    try:
        await bot.load_extension(cog_name)
        print(f"[+] Cog '{cog_name}' carregada")
    except Exception as e:
        print(f"[!] Erro ao carregar '{cog_name}': {e}")

async def load_cogs():
    print("⏳ Carregando cogs...")
    tasks_list = []
    for file in os.listdir("./cogs"):
        if file.endswith(".py"):
            cog_name = f"cogs.{file[:-3]}"
            tasks_list.append(load_cog(cog_name))
    if tasks_list:
        await asyncio.gather(*tasks_list)
    print("✅ Todas as cogs carregadas!")

# -----------------------------
# Evento on_ready
# -----------------------------

@bot.event
async def on_ready():
    global slash_synced
    if not slash_synced:
        print("⏳ Iniciando limpeza de duplicatas e sincronização")
        try:
            # 1. Remove comandos registrados diretamente nas guildas para evitar duplicacao
            for guild in bot.guilds:
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
            
            # 2. Sincroniza apenas os comandos globais
            await bot.tree.sync()
            print("✅ Comandos limpos e sincronizados!")
        except Exception as e:
            print(f"[!] Erro ao sincronizar: {e}")
        slash_synced = True
    print(f"✅ Bot {bot.user} está online!")

# -------------------------------------
# Captura de Erros de Comandos Slash
# -------------------------------------

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if is_unknown_interaction_error(error):
        print(f"ℹ️ Interaction expirada em /{interaction.command.name if interaction.command else 'desconhecido'}; erro ignorado.")
        return

    print(f"⚠️ Erro no comando /{interaction.command.name if interaction.command else 'desconhecido'}: {error}")
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Ocorreu um erro ao executar este comando: {error}", ephemeral=True)
    except:
        pass

# -----------------------------
# Função principal
# -----------------------------

async def main():
    await load_cogs()
    print("⏳ Inicializando banco de dados...")
    await init_database()
    print("✅ Banco de dados inicializado!")
    print("⏳ Conectando o bot...")
    try:
        await bot.start(os.getenv("DISCORD_TOKEN"))
    finally:
        close_mongo_client()

# -----------------------------
# Entry point
# -----------------------------

if __name__ == "__main__":
    asyncio.run(main())
