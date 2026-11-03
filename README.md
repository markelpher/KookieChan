# 👻🍪 Kookie Chan

Kookie Chan é um bot em Python desenvolvido para o [servidor](https://discord.gg/TWcCnmxcPN) da rede social brasileira [Kookie](https://kookie.app), mantido pela comunidade.

Ele acompanha a disponibilidade da plataforma e procura novidades na página de anúncios, informando os usuários no Discord sobre atualizações e mudanças de status.

## Funcionalidades

- Monitoramento automático da disponibilidade do Kookie.
- Registro das verificações e consulta do histórico de status.
- Busca automática de anúncios e envio de novas atualizações ao Discord.
- Notificações opcionais para cargos em mudanças de status e novos anúncios.
- Painel administrativo para configurar canais, URLs, notificações e métricas.
- Interfaces com Discord Components V2.
- Status personalizado com emoji de fantasma e atividades de “Assistindo” sobre a rede Kookie (`https://kookie.app`), cookies e fantasmas; alternam periodicamente.
- Durante uma queda confirmada, o status personalizado mostra há quanto tempo o Kookie está indisponível e atualiza o contador a cada minuto.

## Tecnologias

- Python e discord.py para o bot e a integração com o Discord.
- aiohttp e Beautiful Soup para requisições HTTP e leitura da página de anúncios.
- Supabase e PostgreSQL para persistência de dados.
- Docker e Docker Compose para implantação opcional.

## Instalação

1. Clone o repositório e entre na pasta:

```sh
git clone https://github.com/markelpher/KookieChan.git
cd KookieChan
```

2. Crie um projeto no Supabase e execute `database/sqls/schema.sql` no SQL Editor. O arquivo cria as tabelas, ativa RLS e configura as permissões necessárias ao bot.

3. Copie `.env.example` para `.env` e preencha as variáveis:

```env
DISCORD_TOKEN=
SUPABASE_URL=https://SEU-PROJETO.supabase.co
SUPABASE_SECRET_KEY=
STATUS_CHECK_INTERVAL_SECONDS=60
STATUS_FAILURE_CONFIRMATIONS=2
```

No painel do Supabase, copie a URL do projeto e crie uma **secret key** (`sb_secret_...`) em **Settings → API Keys**. A URL identifica o projeto; a chave autentica as chamadas à API. A chave secreta ignora as políticas RLS: use-a somente no servidor, nunca no cliente, e não a compartilhe nem a coloque no repositório. Não use uma publishable key. O bot não precisa do Supabase Realtime.

4. Crie um ambiente virtual, instale as dependências e inicie o bot. No PowerShell do Windows:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m src
```

No Linux ou macOS:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m src
```

Os comandos usam explicitamente o Python do ambiente virtual para instalar as dependências e executar o bot. Se ocorrer `ModuleNotFoundError` (por exemplo, `aiohttp`), instale novamente `requirements.txt` usando o Python do mesmo ambiente virtual. Para desenvolvimento e testes, instale `requirements-dev.txt` no lugar de `requirements.txt`.

Não é necessário definir IDs de canais, servidor ou URLs no `.env`. Na primeira inicialização, o bot ainda não monitora nem publica anúncios; um administrador do único servidor onde ele está instalado deve abrir `/configurações`, escolher os canais e informar as URLs. As configurações ficam no Supabase e permanecem após reinícios. Em instalações antigas que só definiam esses valores no `.env` e nunca os salvaram pelo painel, informe-os novamente pela interface; as variáveis antigas não são mais lidas.

O bot precisa de permissões para ler/enviar mensagens e gerenciar mensagens fixadas. Após convidá-lo ao servidor e iniciar, use `/configurações` como administrador para definir os canais e URLs monitorados; esses dados ficam salvos no Supabase. `/status`, `/historico`, `/update`, `/ping` e `/ajuda` estão disponíveis no Discord.

## Comandos

| Comando | Função |
| --- | --- |
| `/status` | Mostra o último status verificado e as métricas. |
| `/historico` | Consulta verificações de status ou anúncios registrados. |
| `/update` | Exibe o anúncio mais recente salvo. |
| `/ping` | Mostra a latência entre o bot e o Discord. |
| `/ajuda` | Abre o menu de ajuda. |
| `/configurações` | Abre o painel de administração. |

As interfaces e mensagens principais usam Discord Components V2 nativos (discord.py 2.7.1 ou superior), sem construir embeds tradicionais como camada intermediária. Em `/configurações` → **Serviços**, administradores podem ativar ou pausar o monitor de status e a coleta/publicação automática de anúncios. Ao pausar, ciclos já em andamento podem terminar; os próximos não iniciam. Anúncios pendentes são preservados para quando o serviço for reativado. Os comandos manuais e o histórico continuam disponíveis. As configurações são globais para a instância oficial, destinada a um único servidor. `/configurações` exige permissão de administrador e só funciona quando o bot está em exatamente um servidor; se estiver em mais de um, o painel bloqueia alterações até que a implantação volte a ser de servidor único. Forks que desejem múltiplos servidores devem implementar configurações isoladas por servidor. A permissão é revalidada nos componentes e formulários.

As verificações de status usam timestamps do Discord, exibidos no fuso configurado por cada pessoa. Como a página de anúncios fornece apenas a data, o bot exibe somente essa data, sem converter para o fuso de quem lê. Ela é interpretada como uma data civil em GMT-3; datas ausentes ou inválidas usam a data da consulta como referência, não como data confirmada de publicação. O ajuste manual de tempo usa GMT-3. O Supabase armazena os instantes com fuso horário.

## Como funciona

### Fluxo de status e contagem de tempo

O monitor verifica o site a cada 60 segundos por padrão; HTTP 2xx é considerado online e outros códigos ou erros de conexão são falhas. Cada resposta é registrada no histórico, inclusive falhas ainda não confirmadas. Por padrão, duas falhas consecutivas são necessárias para confirmar uma queda; uma resposta bem-sucedida reinicia a contagem e uma recuperação é reconhecida na primeira resposta 2xx. Até a confirmação, a mensagem mantém o último status confirmado e indica que a queda está em análise. Na primeira inicialização, o status permanece desconhecido até a primeira resposta 2xx ou a confirmação das falhas.

`STATUS_CHECK_INTERVAL_SECONDS` aceita valores inteiros entre 15 e 3600 segundos, e `STATUS_FAILURE_CONFIRMATIONS` entre 1 e 10. Altere o `.env` e reinicie o bot para aplicar os valores. A contagem de falhas pendentes fica em memória e reinicia com o bot ou após uma lacuna longa. Com mais de uma confirmação, a transição é registrada no momento da confirmação, não no primeiro erro; até lá, a duração é atribuída ao último status confirmado. Portanto, o horário e a duração são estimativas e podem diferir dos reais em mais de um intervalo.

Se a API retornar `permission denied for table` para `service_role`, confira se `database/sqls/schema.sql` foi executado no projeto Supabase configurado. A secret key ignora RLS e deve ser usada apenas no servidor.

Ao detectar uma mudança, o período contínuo anterior é encerrado e sua duração substitui o último período encerrado do mesmo status, salvo nas colunas `total_online` ou `total_offline`. Esses valores não são somas históricas. A mensagem exibe somente o período que acabou de terminar (online ou offline), além do novo contínuo, até a próxima atualização sem mudança de status. O novo período contínuo começa em zero. Valores gravados antes desta mudança permanecem até a próxima transição correspondente ou até as métricas serem zeradas.

Intervalos superiores a 1,5 vez o intervalo configurado (90 segundos por padrão) não são contados, pois seu estado é desconhecido. Após uma lacuna normal, a continuidade começa novamente, nenhuma queda é inferida e os últimos períodos encerrados são preservados. Um início definido manualmente é uma exceção explícita: sua data fica persistida e continua sendo usada após reinicializações enquanto o status não mudar; uma transição de status encerra essa estimativa. O total de quedas conta apenas transições confirmadas de online para offline. No painel, a sincronização manual ajusta apenas o início do período contínuo atual; é uma estimativa informada pelo administrador, não uma verificação histórica. Zerar métricas não apaga o histórico.

O estado e as métricas ficam em colunas tipadas de `status_state`; cada verificação e o estado são gravados juntos em uma transação. O JSON é usado pela API somente para transportar os dados (as configurações continuam em JSON).

Execute apenas uma instância do bot por banco: a sincronização entre ajustes manuais e verificações ocorre dentro do processo, não entre múltiplas instâncias.

O bot mantém uma mensagem de status no canal configurado e tenta fixá-la. A última verificação inclui uma data e um tempo relativo do Discord; quando o bot monta uma resposta e ela está antiga, exibe um aviso de status desconhecido. Enquanto o bot estiver desligado, a mensagem fixa não pode receber um novo aviso, mas o tempo relativo continuará indicando a idade da verificação. Se as notificações estiverem ativadas, uma mudança confirmada pode gerar uma mensagem temporária mencionando o cargo configurado. Mudanças que aconteçam enquanto o bot não está verificando o site não podem ser detectadas.

### Fluxo de anúncios

A página de anúncios é consultada a cada 10 minutos. Anúncios encontrados são salvos como pendentes e só passam a enviados após a confirmação da mensagem no Discord. Se o envio falhar, a fila é processada novamente no próximo ciclo, mesmo quando a consulta à página falhar. O bot tenta fixar cada nova mensagem e, se habilitado, envia uma notificação temporária ao cargo configurado. As mensagens anteriores continuam no histórico do canal.

Para reduzir duplicações após falha entre o envio e a confirmação no banco, o bot procura um identificador na mensagem anterior antes de tentar novamente. Ele precisa de acesso ao histórico do canal; se não conseguir consultá-lo ou o canal da tentativa anterior estiver indisponível, o anúncio permanece pendente. A entrega exatamente uma vez não pode ser garantida em todas as falhas entre Discord e Supabase. Fixação e menção são ações posteriores de melhor esforço, não parte da garantia de envio.

O scraping depende da estrutura HTML da página de anúncios. O parser em `src/announcements/parser.py` registra um aviso quando não encontra os seletores esperados; isso também pode ocorrer se a página não tiver anúncios. Se a página mudar, os seletores podem precisar de atualização.

O parser consulta e interpreta a página; `src/database/announcements.py` cuida da persistência, `src/announcements/service.py` coordena a descoberta e a fila, `src/announcements/delivery.py` gerencia tentativas e recuperação, e `src/announcements/discord.py` publica no Discord. A cog concentra comando e agendamento.

Para habilitar a fila em uma instalação existente, pare o bot e execute novamente `database/sqls/schema.sql` no SQL Editor antes de iniciar a nova versão. Anúncios já registrados serão marcados como enviados para evitar republicação; anúncios novos entram na fila. Faça backup do banco antes de aplicar mudanças no esquema.

## Docker

O Compose compila a imagem localmente e executa o bot; o banco de dados permanece no Supabase. Configure `.env` antes de iniciar:

```sh
docker compose -f docker/compose.yaml up -d --build
```

Para acompanhar os logs ou parar o container:

```sh
docker compose -f docker/compose.yaml logs -f bot
docker compose -f docker/compose.yaml down
```

Veja também o [guia Docker](docs/Docker_Guide.md).

## Estrutura do projeto

```text
KookieChan/
├── src/                    # Código da aplicação
│   ├── cogs/               # Comandos e tarefas do bot
│   ├── database/           # Cliente Supabase e repositórios
│   ├── announcements/      # Busca, fila, coordenação e publicação
│   ├── monitoring/         # Cálculos e serviço de status
│   ├── ui/                 # Componentes reutilizáveis do Discord
│   ├── core/               # Utilitários compartilhados
│   ├── __main__.py         # Ponto de entrada: python -m src
│   └── main.py             # Inicialização do bot
├── database/sqls/          # Esquema SQL para o Supabase
├── docker/                 # Dockerfile e Compose
├── docs/                   # Guias e documentação de contribuição
├── tests/                  # Testes automatizados
└── requirements.txt        # Dependências Python
```

## Testes e integração contínua

Para executar os testes localmente:

```sh
python -m unittest discover -s tests -v
```

O CI também valida o Compose, compila a imagem Docker localmente e verifica os imports e o usuário do container. Ele não publica a imagem e não precisa de credenciais do Docker Hub.

Commits enviados a qualquer branch passam pelo CI. Pull requests executam apenas o CI. Ao enviar uma tag cujo commit pertence ao histórico da `main`, o fluxo cria uma release no GitHub após a validação, com título no formato `Kookie Chan vX.Y.Z` (por exemplo, a tag `1.2.3` ou `v1.2.3` gera `Kookie Chan v1.2.3`). Tags não são criadas automaticamente; uma release já existente é preservada.

Antes de criar a tag, substitua o conteúdo de `CHANGELOG.md` pelas alterações revisadas da nova versão, mantendo somente ela no arquivo. Use o cabeçalho `## [1.2.3]` para a tag `1.2.3` ou `v1.2.3`, ao menos uma categoria `###` e um item iniciado por `- `. A release publica esse Markdown e acrescenta, em seção separada, as notas automáticas do GitHub com PRs e comparação quando disponíveis. O GitHub escolhe a release anterior para a comparação; commits sem PR devem ser descritos manualmente. Se a versão não corresponder à tag ou faltar categoria/item, a publicação falha. O histórico das versões anteriores permanece nas releases já publicadas, não no arquivo.

### Mirrors opcionais

Para não usar GitLab e Codeberg, configure a variável **de repositório do GitHub Actions** `MIRRORS_ENABLED=false` em Settings → Secrets and variables → Actions → Variables. Não é uma variável do `.env`. Nesse modo não são necessários secrets dos mirrors, e a release GitHub e o deploy opcional continuam após o CI. Exclusões e eventos de release também não são espelhados. Para preservar o comportamento anterior, se a variável estiver ausente ou tiver outro valor, os mirrors permanecem ativos.

Quando ativos, branches e tags validadas são espelhadas antes da release, e seus metadados são sincronizados depois. O fluxo exige os secrets `MIRROR_SSH_PRIVATE_KEY`, `MIRROR_SSH_KNOWN_HOSTS`, `GITLAB_PROJECT_ID`, `GITLAB_ACCESS_TOKEN` e `CODEBERG_TOKEN`; as variáveis opcionais de endereço permanecem configuráveis nos workflows. `MIRROR_SSH_KNOWN_HOSTS` contém as chaves públicas verificadas dos servidores em formato `known_hosts`; veja o [guia de contribuição](docs/CONTRIBUTING.md#chaves-ssh-dos-mirrors). Falhas de testes, build ou sincronização impedem a etapa seguinte. Pushes normais não forçam atualizações; divergências devem ser resolvidas manualmente.

Exclusões de branches e tags no GitHub são replicadas nos mirrors por um workflow separado, sem executar o CI. A exclusão é limitada à referência indicada e cancelada se ela tiver sido recriada no GitHub ou alterada no mirror entre a consulta e a exclusão; a `main` é protegida. Para atualizações e exclusões de referências, se um mirror falhar, o fluxo tenta restaurar as alterações já feitas no outro, protegendo mudanças concorrentes. Uma falha de rede ou permissão pode impedir a reversão; nesse caso, os logs indicam reversão incompleta e é necessária intervenção manual.

Publicações, edições e exclusões manuais de releases também são sincronizadas. Se a sincronização falhar, o fluxo tenta restaurar os metadados anteriores nos mirrors, sem sobrescrever alterações concorrentes detectadas. Exclusões automáticas de releases com anexos são bloqueadas, pois os arquivos não podem ser restaurados com segurança. Uma release restaurada após exclusão pode receber outro ID e novas datas; a recriação é cancelada se a tag necessária estiver ausente ou divergente.

O GitHub cria a release antes da sincronização dos metadados com GitLab e Codeberg. Se essa etapa falhar, o fluxo também tenta remover a release do GitHub **somente se ela tiver sido criada pela execução e não tiver sido alterada ou recebido anexos**; a tag é preservada. Releases preexistentes e alterações manuais no GitHub não são revertidas. As referências Git já espelhadas em uma etapa anterior não são revertidas caso a sincronização de releases falhe. Erros de rede, cancelamentos ou alterações simultâneas podem impedir a compensação; confira os logs e revise manualmente qualquer reversão incompleta. As APIs não oferecem uma transação atômica entre os três serviços, e a verificação anterior à reversão não elimina todas as condições de corrida.

### Deploy opcional com Dokploy

O workflow `dokploy.yml` é chamado após a criação da release e, quando os mirrors estão ativos, sua sincronização bem-sucedida. Por padrão, ele fica desativado e não exige uma VPS. Para usá-lo futuramente, configure no repositório GitHub:

- **Variables:** `DOKPLOY_ENABLED=true`, `DOKPLOY_URL` (URL HTTPS do painel) e `DOKPLOY_COMPOSE_ID` (ID do serviço Compose).
- **Secret:** `DOKPLOY_API_KEY` (chave de API criada no Dokploy).

O workflow consulta a API e solicita um deploy de Compose se estiver disponível. Caso o serviço esteja inacessível ou responda erro 5xx na verificação, o deploy é ignorado sem falhar o CI. Credenciais, URL ou configuração inválidas geram erro para não mascarar um problema real. Se a conexão cair depois de enviar a solicitação, o resultado é incerto: verifique o painel antes de tentar novamente. Uma resposta de sucesso apenas confirma que a solicitação foi aceita, não que o deploy terminou corretamente.

O deploy usa a referência configurada no serviço do Dokploy; o workflow **não fixa automaticamente a tag da release**. Configure e confira essa referência antes de ativar a integração, especialmente se houver commits mais recentes. Uma falha no deploy não reverte a release ou os mirrors. Não divulgue a API key e evite manter outro auto-deploy concorrente para o mesmo serviço.

O Dependabot verifica semanalmente atualizações das dependências Python, das GitHub Actions e da imagem base Docker. As atualizações são propostas em pull requests para revisão e validação pelo CI; não são aplicadas automaticamente.

As dependências diretas ficam em `requirements.in`; `requirements.txt` registra versões resolvidas e hashes para Python 3.14. O CI e o Docker instalam esse arquivo. Revise as atualizações do Dependabot e, se necessário, regenere o arquivo conforme o [guia de contribuição](docs/CONTRIBUTING.md#atualizar-dependências).

## Contribuição

Contribuições são bem-vindas! Consulte o [guia de contribuição](docs/CONTRIBUTING.md).

## Licença

Este projeto está licenciado sob a [GNU General Public License v3.0](LICENSE).
