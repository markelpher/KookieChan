import aiohttp
from datetime import datetime
import pytz
import time
import os

# Fuso horário do Brasil
BR_TZ = pytz.timezone("America/Sao_Paulo")

def parse_brazilian_date(date_str: str) -> datetime:
    """Converte string DD/MM/YYYY HH:MM para datetime no fuso de Brasília"""
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y %H:%M")
        return BR_TZ.localize(dt)
    except Exception:
        # Tenta sem horas se falhar
        try:
            dt = datetime.strptime(date_str, "%d/%m/%Y")
            return BR_TZ.localize(dt.replace(hour=0, minute=0))
        except Exception:
            raise ValueError("Formato de data inválido. Use DD/MM/YYYY HH:MM")

async def get_config(db, key, default=None):
    """Busca configuração no MongoDB com fallback para variáveis de ambiente"""
    coll = db["config"]
    doc = await coll.find_one({"_id": "bot_settings"})
    if doc and key in doc:
        return doc[key]
    
    # Fallback para .env
    env_key = key.upper()
    env_val = os.getenv(env_key)
    if env_val is not None:
        # Tenta converter IDs de canal para int
        if "CHANNEL_ID" in env_key or "ROLE_ID" in env_key:
            try:
                return int(env_val)
            except:
                pass
        if env_val.lower() in {"true", "false"}:
            return env_val.lower() == "true"
        return env_val
        
    return default

async def set_config(db, key, value):
    """Salva configuração no MongoDB"""
    coll = db["config"]
    await coll.update_one(
        {"_id": "bot_settings"},
        {"$set": {key: value}},
        upsert=True
    )

def now() -> datetime:
    """Retorna a hora atual em timezone BR_TZ"""
    return datetime.now(tz=BR_TZ)

def format_datetime_br(dt: datetime) -> str:
    """Formata datetime para string dd/mm/yyyy HH:MM:SS em horário de Brasília"""
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.utc).astimezone(BR_TZ)
    else:
        dt = dt.astimezone(BR_TZ)
    return dt.strftime("%d/%m/%Y %H:%M:%S")

def ms_to_str(ms: float) -> str:
    """Converte milissegundos em string formatada (d, h, m) sem segundos"""
    seconds = int(ms / 1000)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    
    if d > 0:
        return f"{d}d {h}h {m:02d}m"
    return f"{h}h {m:02d}m"

async def get_site_status(url: str) -> dict:
    """
    Faz requisição HTTP ao site e retorna dicionário com status
    {'online': bool, 'http_code': int, 'response_time': int, 'timestamp': datetime}
    """
    start_time = time.time()
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url) as response:
                response_time = int((time.time() - start_time) * 1000)
                code = response.status
                online = 200 <= code < 300
                return {
                    "online": online,
                    "http_code": code,
                    "response_time": response_time,
                    "timestamp": now()
                }
        except Exception as e:
            return {
                "online": False,
                "http_code": None,
                "response_time": 0,
                "timestamp": now(),
                "error": str(e)
            }
