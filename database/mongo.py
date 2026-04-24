import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

try:
    import certifi
except ImportError:
    certifi = None


load_dotenv()

_client = None


def _env_with_legacy(primary: str, legacy: str | None = None, default=None):
    value = os.getenv(primary)
    if value is None and legacy:
        value = os.getenv(legacy)
    return value if value is not None else default


def _build_client_options() -> dict:
    uri = os.getenv("MONGO_URI", "")
    options = {
        "serverSelectionTimeoutMS": 10000,
        "connectTimeoutMS": 10000,
    }

    if uri.startswith("mongodb+srv://") and certifi is not None:
        options["tls"] = True
        options["tlsCAFile"] = certifi.where()

    return options


def get_mongo_client() -> AsyncIOMotorClient:
    global _client

    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("A variavel de ambiente MONGO_URI nao foi definida.")

    if _client is None:
        _client = AsyncIOMotorClient(uri, **_build_client_options())

    return _client


def get_database():
    db_name = os.getenv("MONGO_DB")
    if not db_name:
        raise RuntimeError("A variavel de ambiente MONGO_DB nao foi definida.")
    return get_mongo_client()[db_name]


async def init_database():
    db = get_database()
    client = get_mongo_client()
    update_collection = os.getenv("MONGO_UPDATE_COLLECTION", "update")
    update_archive_collection = os.getenv("MONGO_UPDATE_ARCHIVE_COLLECTION", "update_archive")

    collections = {
        "config",
        os.getenv("MONGO_STATUS_COLLECTION", "status"),
        os.getenv("MONGO_STATUS_LOGS_COLLECTION", "status_logs"),
        os.getenv("MONGO_STATUS_ARCHIVE_COLLECTION", "status_archive"),
        update_collection,
        update_archive_collection,
    }

    try:
        await client.admin.command("ping")

        existing = set(await db.list_collection_names())
        for name in sorted(collections - existing):
            await db.create_collection(name)

        await db["config"].update_one(
            {"_id": "bot_settings"},
            {"$setOnInsert": {"created_by": "init_database"}},
            upsert=True,
        )

        await db[update_collection].create_index(
            "title", unique=True
        )
        await db[update_collection].create_index(
            "timestamp"
        )
        await db[os.getenv("MONGO_STATUS_LOGS_COLLECTION", "status_logs")].create_index(
            "timestamp"
        )
        await db[os.getenv("MONGO_STATUS_ARCHIVE_COLLECTION", "status_archive")].create_index(
            "date"
        )
        await db[update_archive_collection].create_index(
            "date"
        )
    except Exception as exc:
        raise RuntimeError(
            "Falha ao inicializar o MongoDB. Verifique MONGO_URI/MONGO_DB e a conectividade TLS com o cluster. "
            f"Detalhe original: {exc}"
        ) from exc

    return db


def close_mongo_client():
    global _client
    if _client is not None:
        _client.close()
        _client = None
