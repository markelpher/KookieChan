# Guia de execução com Docker

O Docker Compose compila a imagem a partir do código local e executa o bot. O banco permanece no Supabase; o Compose não cria um banco de dados local.

A imagem suporta `amd64` e `arm64` (ARM de 64 bits). Em uma máquina ARM64, o Compose seleciona a arquitetura nativa automaticamente. Para compilar imagens específicas com Buildx, na raiz do repositório:

```sh
docker buildx build --platform linux/amd64 --load --file docker/Dockerfile --tag kookiechan:amd64 .
docker buildx build --platform linux/arm64 --load --file docker/Dockerfile --tag kookiechan:arm64 .
```

O build ARM64 em uma máquina de outra arquitetura requer emulação Buildx habilitada. ARM de 32 bits não é suportado pela imagem-base Python utilizada.

Para compilar as duas arquiteturas em um único comando e publicar uma tag multi-plataforma em um registry, autentique-se nele com `docker login` e use:

```sh
docker buildx build --platform linux/amd64,linux/arm64 --file docker/Dockerfile --tag USUARIO/kookiechan:latest --push .
```

Substitua `USUARIO/kookiechan` pelo nome da imagem no registry. O `--push` publica o índice multi-plataforma; o `--load` não carrega builds com várias plataformas no Docker local.

Para compilar as duas sem publicar no registry, exporte o resultado como um arquivo OCI local:

```sh
docker buildx build --platform linux/amd64,linux/arm64 --file docker/Dockerfile --tag kookiechan:latest --output type=oci,dest=kookiechan-multiarch.tar .
```

Isso cria `kookiechan-multiarch.tar` na pasta atual; não envia a imagem ao Docker Hub nem a carrega automaticamente no armazenamento local do Docker.

A imagem usa uma etapa separada para instalar dependências e executa o bot como usuário sem privilégios de root. O Compose usa um processo `init` e impede a elevação de privilégios. Nenhuma porta precisa ser publicada: o bot inicia conexões de saída.

## Pré-requisitos

- Docker com o plugin Docker Compose.
- Um projeto Supabase configurado e acesso à sua secret key.
- Um bot criado no Discord Developer Portal e adicionado ao servidor.
- Arquivo `.env` na raiz do projeto, baseado em [`.env.example`](../.env.example).

No SQL Editor de um **projeto Supabase novo**, execute [`database/sqls/schema.sql`](../database/sqls/schema.sql). Esse arquivo cria as tabelas, ativa RLS, configura as permissões e instala a função usada para registrar verificações. Em uma instalação existente, pare o bot, faça backup e execute novamente o esquema para aplicar as atualizações idempotentes, inclusive as colunas da fila de anúncios e da persistência do ajuste manual de tempo. Consulte o [README](../README.md) para as variáveis necessárias.

> [!WARNING]
> `SUPABASE_SECRET_KEY` e `DISCORD_TOKEN` são credenciais de servidor. Não publique o `.env`, imagens de tela contendo os valores ou logs que os exponham. A secret key ignora RLS; não a use em aplicativos cliente. Caso uma credencial seja exposta, revogue-a e gere outra.

## Iniciar e acompanhar

Na raiz do repositório:

```sh
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml logs -f bot
```

O Compose lê `../.env` em relação a `docker/docker-compose.yml`. O bot precisa de acesso de rede ao Discord, à API do Supabase e às URLs monitoradas. Após iniciar, use `/configurações` para definir canais, URLs e notificações, e para ativar ou pausar os serviços automáticos; esses valores são persistidos no Supabase.

## Atualizar ou parar

Após alterar o código ou as dependências, reconstrua a imagem:

```sh
docker compose -f docker/docker-compose.yml up -d --build
```

Para encerrar o bot:

```sh
docker compose -f docker/docker-compose.yml down
```

Parar ou recriar o container não apaga os dados armazenados no Supabase. Planeje backups separadamente no seu projeto Supabase.

## Problemas comuns

- **Falha de autenticação:** confira o token do Discord, a URL do projeto e a secret key no `.env`, sem compartilhá-los.
- **`permission denied` ou tabela ausente:** confira se o esquema foi executado no projeto Supabase correto. Em instalações existentes, pare o bot, faça backup e execute o esquema atualizado antes de iniciar a nova versão.
- **Bot conectado, mas sem mensagens:** confira os canais selecionados em `/configurações`, as permissões do bot e os logs.
- **Sem anúncios:** verifique a URL, os logs e se o HTML corresponde aos seletores de `src/announcements/parser.py`. Para tentar novamente envios pendentes, o bot precisa ler o histórico do canal da tentativa anterior.

Antes de compartilhar logs com qualquer pessoa, remova tokens, chaves, URLs com credenciais e outros dados sensíveis.
