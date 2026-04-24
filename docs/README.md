# **👻🍪 Kookie Chan**

Kookie Chan é um bot em Python desenvolvido para o [servidor](https://discord.gg/TWcCnmxcPN) da rede social brasileira [Kookie](https://kookie.app) mantido pela comunidade.

Ele utiliza técnicas de scraping para acompanhar o status da plataforma e buscar novas publicações na página de Update do Kookie, informando automaticamente os usuários sobre novidades ou eventuais problemas.

## Funcionalidades

- Monitoramento automático do status da rede Kookie.
- Envio automático de mensagens quando um novo Update é publicado.
- Alertas sobre problemas ou indisponibilidade da plataforma.
- Interação prática e automatizada com os usuários no Discord.

## Tecnologias

- Python
- Bibliotecas de scraping e parsing HTML
- Discord.py para integração com o Discord
- MongoDB para persistência de dados

## Instalação

1. Clone o repositório:

```
git clone https://github.com/markelpher/KookieChan.git
```

2. Entre na pasta do projeto:

```
cd KookieChan
```

3. Instale as dependências:

```
pip install -r requirements.txt
```

4. Crie e configure o arquivo `.env` do bot com seu token do Discord e as variáveis necessárias:

```
DISCORD_TOKEN=
UPDATE_CHANNEL_ID=
STATUS_CHANNEL_ID=
KOOKIE_UPDATE_URL=https://kookie.app/announcements
KOOKIE_STATUS_URL=https://kookie.app
MONGO_URI=mongodb+srv://usuario:senha@cluster.mongodb.net/
MONGO_DB=
MONGO_STATUS_COLLECTION=status
MONGO_UPDATE_COLLECTION=updates
MONGO_STATUS_LOGS_COLLECTION=status_logs
MONGO_STATUS_ARCHIVE_COLLECTION=status_archive
MONGO_UPDATE_ARCHIVE_COLLECTION=updates_archive
```

> [!NOTE]
> Use o arquivo [.env.example](https://github.com/markelpher/KookieChan/blob/main/.env.example) para configurar o bot corretamente. Nele também há comentários indicando o que cada variável significa.

## Uso

Após a instalação e configuração:

```
python main.py
```

O bot iniciará e começará a monitorar o status e a página de Update do Kookie, enviando notificações automaticamente no servidor do Discord configurado.

## Como Funciona

### Fluxo de Status

O bot verifica automaticamente o status do Kookie em intervalos regulares.

Quando detecta mudança entre online e offline, ele:

- Envia uma mensagem separada com ping para o cargo configurado;

- Apaga essa mensagem de ping após alguns segundos;

- Atualiza a mensagem principal de status com a menção do cargo;

- Fixa essa mensagem principal no canal;

- Remove mensagens fixadas antigas do próprio bot;

- Apaga também a mensagem automática do Discord informando que uma mensagem foi fixada.

Dessa forma, o canal de status mantém sempre uma única mensagem principal atualizada e fixada, sem acumular várias mensagens antigas.

### Fluxo de Update

O bot também verifica automaticamente a página de Update do Kookie.

Quando encontra uma nova atualização, ele:

- Envia uma nova mensagem no canal com o embed da atualização;

- Fixa essa nova mensagem;

- Remove a mensagem fixada anterior do próprio bot;

- Apaga a mensagem automática do Discord de mensagem fixada;

- Envia uma mensagem separada com ping para o cargo configurado;

- Apaga essa mensagem de ping após alguns segundos;

- Atualiza a nova mensagem enviada com a menção do cargo.

Assim, o histórico de mensagens de Update continua visível normalmente no chat, mas apenas a atualização mais recente permanece fixada no canal.

## Contribuição

Contribuições são bem-vindas. Para mais detalhes, veja a [Página de Contribuição do Projeto](https://github.com/markelpher/KookieChan/blob/main/docs/CONTRIBUTING.md).

## Licença

Este projeto está licenciado sob a [GNU General Public License v3.0](https://github.com/markelpher/KookieChan/blob/main/docs/LICENSE).
