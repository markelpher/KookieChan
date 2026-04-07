# **👻🍪 Kookie Chan**

Kookie Chan é um bot em Python desenvolvido para o [servidor](https://discord.gg/TWcCnmxcPN) da rede social brasileira [Kookie](https://kookie.app) mantido pela comunidade.

Ele utiliza técnicas de scraping para realizar solicitações, acompanhar status e obter atualizações em tempo real, informando automaticamente os usuários sobre novidades ou eventuais problemas na plataforma.

## Funcionalidades

- Envio de solicitações e monitoramento de status da rede Kookie.

- Notificações automáticas sobre atualizações e novidades.

- Alertas sobre problemas ou indisponibilidade da plataforma.

- Interação direta com os usuários no Discord de forma prática e automatizada.

## Tecnologias

- Python

- Bibliotecas de scraping (como requests e BeautifulSoup)

- Discord.py para integração com Discord

- MongoDB para banco de dados consistente

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

4. Crie e configure o arquivo .env do bot com seu token do Discord e variaveis necessárias:

```
DISCORD_TOKEN=
UPDATES_CHANNEL_ID=
STATUS_CHANNEL_ID=
KOOKIE_UPDATES_URL=
KOOKIE_STATUS_URL=
MONGO_URI=
MONGO_DB=
MONGO_UPDATES_COLLECTION=
MONGO_STATUS_COLLECTION=
MONGO_STATUS_LOGS_COLLECTION=
MONGO_STATUS_ARCHIVE_COLLECTION=
MONGO_UPDATES_ARCHIVE_COLLECTION=
```

## Uso

Após a instalação e configuração:

```
python main.py
```

O bot iniciará e começará a monitorar o status e atualizações do Kookie, enviando notificações automaticamente no servidor do Discord configurado.

## Contribuição

Contribuições são bem-vindas! Para mais detalhes veja a [Pagina de Contibuição do Projeto](https://github.com/markelpher/KookieChan/blob/main/docs/CONTRIBUTING.md)

## Licença

Este projeto está licenciado sob a [GNU General Public License v3.0](https://github.com/markelpher/KookieChan/blob/main/docs/LICENSE)
