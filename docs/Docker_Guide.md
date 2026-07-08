# Guia Docker da Kookie Chan

Este guia explica como rodar a Kookie Chan com Docker Compose usando a imagem `markelpher/kookiechan:latest`, MongoDB e Watchtower para atualização automática do container.

> [!WARNING]
> Mantenha arquivos sensíveis, como `.env`, fora do `dockerfile`. O projeto já usa `env_file` no Compose para carregar as variáveis em tempo de execução.

## 1. Estrutura Docker do projeto

Os arquivos Docker ficam dentro da pasta `docker/`:

```text
KookieChan/
├── docker/
│   ├── dockerfile
│   └── docker-compose.yml
├── cogs/
├── database/
├── main.py
├── utils.py
├── requirements.txt
└── .env.example
```

## 2. Dockerfile

O arquivo `docker/dockerfile` define a imagem da Kookie Chan:

```dockerfile
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY ../requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY ../main.py .
COPY ../utils.py .
COPY ../cogs ./cogs
COPY ../database ./database

ARG FORCE_REBUILD

CMD ["python", "main.py"]
```

Principais pontos:

- Usa `python:3.14-slim` para manter a imagem menor.
- Instala as dependências do `requirements.txt` durante o build.
- Copia `main.py`, `utils.py`, `cogs/` e `database/` para dentro de `/app`.
- Executa o bot com `python main.py`.

## 3. Docker Compose

O arquivo `docker/docker-compose.yml` sobe três serviços:

```yaml
services:
  bot:
    image: markelpher/kookiechan:latest
    container_name: kookiechan
    restart: unless-stopped
    env_file:
      - ../.env
    volumes:
      - ./data:/app/data
    depends_on:
      - mongo
    networks:
      - botnet

  mongo:
    image: mongo:latest
    container_name: mongodb
    restart: unless-stopped
    environment:
      MONGO_INITDB_ROOT_USERNAME: root
      MONGO_INITDB_ROOT_PASSWORD: senha
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db
    networks:
      - botnet

  watchtower:
    image: nickfedor/watchtower:latest
    container_name: watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: --interval 60 bot
    networks:
      - botnet

volumes:
  mongo_data:

networks:
  botnet:
```

Serviços:

- `bot`: container principal da Kookie Chan.
- `mongo`: banco MongoDB usado para persistência.
- `watchtower`: verifica atualizações da imagem e reinicia o bot quando houver uma versão nova.

## 4. Variáveis de ambiente

Crie um arquivo `.env` na raiz do projeto com base em `.env.example`.

Para usar o MongoDB do Compose, a URI pode apontar para o serviço `mongo`:

```env
MONGO_URI=mongodb://root:senha@mongo:27017/
MONGO_DB=kookiechan
```

Mantenha também as variáveis do Discord e URLs do Kookie:

```env
DISCORD_TOKEN=
UPDATE_CHANNEL_ID=
STATUS_CHANNEL_ID=
KOOKIE_UPDATE_URL=https://kookie.app/announcements
KOOKIE_STATUS_URL=https://kookie.app
```

## 5. Rodando com Docker

Na raiz do projeto, suba os containers:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Para recriar os containers e buscar a imagem mais recente:

```bash
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml up -d
```

Para acompanhar os logs do bot:

```bash
docker compose -f docker/docker-compose.yml logs -f bot
```

Para parar tudo:

```bash
docker compose -f docker/docker-compose.yml down
```

## 6. Build automático no GitHub Actions

O workflow `.github/workflows/docker-image-build.yml` publica a imagem `markelpher/kookiechan:latest` no Docker Hub.

Ele usa:

- `docker/setup-qemu-action` para suporte multiarquitetura.
- `docker/setup-buildx-action` para build com Buildx.
- `docker/login-action` para autenticar no Docker Hub.
- `docker/build-push-action` para gerar e publicar a imagem.

As plataformas publicadas atualmente são:

```text
linux/amd64
linux/arm64
```

Secrets necessários no GitHub:

```text
DOCKER_USERNAME
DOCKER_PASSWORD
```

## 7. Dicas de produção

- Faça backup do volume `mongo_data`.
- Use `docker compose -f docker/docker-compose.yml logs -f watchtower` para verificar atualizações automáticas.
- Confira se o `.env` da VPS usa `MONGO_URI=mongodb://root:senha@mongo:27017/` quando o MongoDB for o serviço do Compose.
- Troque a senha padrão do MongoDB antes de expor o serviço em produção.