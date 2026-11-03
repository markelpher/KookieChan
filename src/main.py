"""Inicialização do bot, carregamento de cogs e encerramento dos serviços."""

import asyncio
import logging
import os
import pkgutil

import discord
from discord.ext import commands
from dotenv import load_dotenv

import src.cogs
from src.core.background import cancel_supervised_tasks
from src.core.http import close_http_session
from src.database.database import close_database, init_database

# Configuração inicial

load_dotenv()
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="none", intents=intents)

slash_synced = False


def is_unknown_interaction_error(error) -> bool:
    base_error = getattr(error, "original", error)
    return (
        isinstance(base_error, discord.NotFound)
        and getattr(base_error, "code", None) == 10062
    )


# Carregamento de cogs


async def load_cog(cog_name: str):
    try:
        await bot.load_extension(cog_name)
        logger.info("Cog '%s' carregada", cog_name)
    except Exception as e:
        logger.error("Erro ao carregar '%s' (%s)", cog_name, type(e).__name__)
        raise


async def load_cogs():
    logger.info("Carregando cogs")
    tasks_list = []
    for module in pkgutil.iter_modules(src.cogs.__path__, "src.cogs."):
        if not module.ispkg:
            tasks_list.append(load_cog(module.name))
    if tasks_list:
        await asyncio.gather(*tasks_list)
    logger.info("Todas as cogs carregadas")


# Evento on_ready


@bot.event
async def on_ready():
    global slash_synced
    if not slash_synced:
        logger.info("Sincronizando comandos")
        try:
            # 1. Remove comandos registrados diretamente nas guildas para evitar duplicação.
            for guild in bot.guilds:
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)

            # 2. Sincroniza apenas os comandos globais
            await bot.tree.sync()
            logger.info("Comandos sincronizados")
        except Exception as e:
            logger.error("Erro ao sincronizar comandos (%s)", type(e).__name__)
        slash_synced = True
    logger.info("Bot conectado")


# Captura de Erros de Comandos Slash


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    if is_unknown_interaction_error(error):
        logger.info("Interação expirada")
        return

    logger.error("Erro de comando (%s)", type(error).__name__)
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Não foi possível executar o comando.", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ Não foi possível executar o comando.", ephemeral=True
            )
    except discord.HTTPException:
        logger.warning("Não foi possível responder à interação.")


# Função principal


async def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logger.info("Inicializando banco de dados")
    await init_database()
    logger.info("Banco inicializado; conectando bot")
    try:
        await load_cogs()
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise RuntimeError("A variável DISCORD_TOKEN não foi configurada.")
        await bot.start(token)
    except asyncio.CancelledError:
        logger.info("Interrupção recebida; encerrando o bot e fechando as conexões...")
        raise
    finally:
        try:
            if not bot.is_closed():
                await bot.close()
        finally:
            try:
                await cancel_supervised_tasks(bot)
            finally:
                try:
                    await close_http_session()
                finally:
                    await close_database()


# Ponto de entrada do processo.

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # asyncio.run converte Ctrl+C em cancelamento da tarefa principal.
        # main() já registrou a mensagem e executou a limpeza no finally.
        pass
