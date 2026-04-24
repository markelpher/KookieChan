import os
from database.mongo import get_mongo_client, get_database

# -------------------- VARIÁVEIS DE AMBIENTE --------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017") # URI do MongoDB
MONGO_DB = os.getenv("MONGO_DB") # Nome do banco
MONGO_STATUS_COLLECTION = os.getenv("MONGO_STATUS_COLLECTION", "status") # Nome da coleção
MONGO_UPDATE_COLLECTION = os.getenv("MONGO_UPDATE_COLLECTION", "update") # Coleção de update

# -------------------- CONEXÃO --------------------
client = get_mongo_client()
db = get_database()

# Coleções
status_collection = db[MONGO_STATUS_COLLECTION]
update_collection = db[MONGO_UPDATE_COLLECTION]

print(f"[MongoDB] Conectado ao banco '{MONGO_DB}' em {MONGO_URI}")
