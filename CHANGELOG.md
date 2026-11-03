# Changelog

## [1.4.0]

### Atenção ao atualizar

- A persistência passou de MongoDB para Supabase. Configure um projeto Supabase, execute `database/sqls/schema.sql` no SQL Editor e informe `SUPABASE_URL` e `SUPABASE_SECRET_KEY` no `.env`. Não há migração automática dos dados antigos do MongoDB; faça backup e planeje a migração antes de substituir a instalação.
- Canais, cargos e URLs de monitoramento e anúncios são configurados pelo comando `/configurações`, não mais pelos IDs e URLs antigos no `.env`. Na primeira inicialização, configure os serviços antes de esperar verificações ou publicações automáticas.
- A configuração oficial é global e destinada a um único servidor. O painel administrativo bloqueia alterações quando o bot está em mais de um servidor.
- A inicialização Python agora é feita com `python -m src`. Para Docker Compose, use `docker compose -f docker/compose.yaml up -d --build`.
- Em uma instalação Supabase existente, pare o bot, faça backup e execute novamente o esquema antes de iniciar esta versão. Anúncios já registrados no Supabase são marcados como enviados para evitar republicações.

### Monitoramento de status

- Quedas passam a exigir falhas consecutivas para confirmação; por padrão são duas falhas, enquanto a recuperação é reconhecida na primeira resposta bem-sucedida. O intervalo e a quantidade de confirmações podem ser configurados no `.env`.
- Lacunas longas entre verificações não são contabilizadas como tempo online ou offline e não provocam quedas presumidas. Uma mensagem antiga apresenta aviso de status desconhecido quando atualizada ou consultada.
- O contador de quedas considera somente transições confirmadas de online para offline. As métricas de tempo concluído representam o último período encerrado de cada estado, não a soma histórica.
- Ajustes manuais alteram a estimativa do período atual sem criar verificações históricas. Verificações e ajustes são serializados, e o estado só avança em memória após persistência bem-sucedida.
- A verificação e o estado correspondente são registrados juntos pela função transacional `record_status_check` no Supabase.

### Anúncios

- Anúncios descobertos entram em uma fila persistente e só são marcados como enviados após a confirmação da mensagem no Discord. Falhas são retomadas nos ciclos seguintes, inclusive quando a consulta à página falha.
- Tentativas de envio incertas usam um identificador na mensagem e o histórico do canal para reduzir duplicações. Se o histórico necessário estiver indisponível, o anúncio permanece pendente; a entrega exatamente uma vez não é garantida em todas as falhas.
- O processamento separa leitura da página, persistência, coordenação, entrega e publicação. Páginas vazias, erros de acesso e HTML inesperado não devem gerar anúncios fabricados.

### Interface e configuração no Discord

- As interfaces principais passam a usar Discord Components V2. O painel administrativo permite configurar canais, URLs e notificações e pausar ou reativar separadamente o monitoramento e a publicação de anúncios.
- Permissões administrativas são verificadas também nas interações posteriores, como botões, seleções e formulários. URLs configuradas são validadas para restringir acesso a endereços internos e outras origens inseguras.
- Horários das verificações usam timestamps do Discord; datas de anúncios são exibidas como datas civis, sem conversão de fuso para cada usuário.

### Segurança, implantação e dependências

- O esquema Supabase ativa RLS e concede à `service_role` os privilégios necessários. A secret key deve permanecer exclusivamente no servidor.
- A imagem Docker usa usuário não root e instala apenas dependências de produção; o Compose mantém o `.env` fora da imagem e ativa `no-new-privileges`.
- Dependências de produção e desenvolvimento passam a ter arquivos de entrada e locks separados, com versões e hashes registrados. O projeto usa Python 3.14 no CI e na imagem Docker.
- A aplicação foi reorganizada em `src/`, separando cogs, monitoramento, anúncios, banco de dados, utilitários e componentes compartilhados. Tarefas em segundo plano têm ciclo de vida supervisionado.

### CI, releases e integrações

- O CI verifica sintaxe, lint, tipos, vulnerabilidades, testes e cobertura, além de validar o Compose e o build Docker. O build de CI não publica imagem no Docker Hub.
- Releases são criadas após a validação de uma tag no histórico da `main`. As notas usam a versão correspondente deste `CHANGELOG.md` e incluem em seção separada as notas automáticas do GitHub para PRs e comparação. Releases existentes são preservadas.
- Mirrors para GitLab e Codeberg são opcionais e podem ser desativados com `MIRRORS_ENABLED=false`. Quando ativos, a sincronização protege referências e alterações concorrentes e tenta compensar falhas; reversões completas não são garantidas em falhas de rede ou permissão.
- O deploy pelo Dokploy é opcional e desativado por padrão. Quando habilitado, solicita o deploy da referência configurada no serviço, sem fixar automaticamente a tag da release.
- O Dependabot propõe atualizações de dependências e ferramentas para revisão. Os fluxos anteriores de atualização anual e publicação de imagem Docker foram removidos.

### Documentação e testes

- README e guias de instalação, Docker, contribuição e relatos foram atualizados para o novo fluxo.
- Foram adicionados testes automatizados para componentes do bot, monitoramento, persistência, anúncios, segurança HTTP e sincronização de mirrors e releases.
