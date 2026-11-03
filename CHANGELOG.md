# Histórico de alterações

## [1.4.0]

## O que há de novo?

Resumo das principais novidades, melhorias e mudanças desta versão da Kookie Chan.

## Novidades

### Bot

- A presença do bot alterna periodicamente entre atividades relacionadas ao Kookie, cookies e fantasmas.
- Durante uma queda confirmada, a presença exibe o tempo de indisponibilidade e é atualizada a cada minuto.
- O dashboard administrativo permite pausar e reativar separadamente o monitoramento de status e a coleta/publicação de anúncios.

### Banco de Dados

- A persistência foi migrada de MongoDB para Supabase, com esquema SQL, tabelas tipadas, RLS e fila persistente de anúncios.
- Verificações e estado de status são registrados atomicamente pela função `record_status_check`.
- Anúncios existentes no Supabase são preservados e marcados como enviados durante a atualização do esquema, evitando republicações.
- Para configurar uma instalação nova:
  - Crie um projeto Supabase, execute `database/sqls/schema.sql` e defina `SUPABASE_URL` e `SUPABASE_SECRET_KEY`.

## Adicionado

### Bot

- Adicionada fila persistente de anúncios, com retomada de itens pendentes após falhas.
- Adicionada recuperação de tentativas de envio incertas usando identificador da mensagem e consulta ao histórico do canal.
- Adicionada validação de URLs e resolução segura para reduzir acesso a endereços internos e outras origens inseguras.
- Adicionada supervisão do ciclo de vida e das exceções de tarefas em segundo plano.

### Comandos e interface

- Adicionada a configuração administrativa por `/configurações` para canais, URLs monitoradas, cargos de notificação e serviços.
- Adicionada limpeza opcional de mensagens antigas de status enviadas pelo bot:
  - Desativada por padrão e sem apagar o histórico persistido.
  - Quando ativada, verifica até 200 mensagens recentes, preserva a mensagem de status atual e executa no máximo a cada 15 minutos.
- O comando `/historico` permite consultar até 20 registros recentes de status ou anúncios, em páginas de um registro.
- Notificações por cargo podem ser configuradas para mudanças de status e novos anúncios.
- Ajuda, status, histórico e demais interfaces passam a usar Discord Components V2.

### CI/CD e releases

- Adicionado workflow de CI para validar código, testes, cobertura, segurança de dependências, Compose e build Docker.
- Releases:
  - Criadas por tags válidas no histórico da `main`, cuja versão deve corresponder ao cabeçalho deste changelog.
  - Notas combinam este changelog com notas automáticas do GitHub para PRs e comparação; releases já existentes não são sobrescritas.
- Adicionado workflow opcional de deploy via Dokploy, desativado por padrão; usa a referência configurada no serviço, sem selecionar automaticamente a tag recém-publicada.
- Adicionada configuração do Dependabot para propor atualizações de dependências, GitHub Actions e imagem base Docker.

## Modificado

### Monitoramento de status

- Quedas agora exigem falhas consecutivas para confirmação; o padrão é de duas falhas. A recuperação é reconhecida na primeira resposta bem-sucedida.
- Intervalo de verificação e quantidade de falhas para confirmação podem ser configurados no `.env`.
- O intervalo aceita de 15 a 3600 segundos e a confirmação de queda de 1 a 10 falhas; os padrões são 60 segundos e duas falhas.
- Lacunas longas entre verificações:
  - Não acumulam tempo online/offline nem provocam quedas presumidas.
  - Status desatualizados exibem aviso de estado desconhecido.
- As métricas de status seguem estas regras:
  - O contador de quedas considera somente transições confirmadas de online para offline.
  - O tempo concluído representa o último período encerrado, não uma soma histórica.
  - Ajustes manuais alteram a estimativa do período atual, sem criar verificações históricas, e persistem até uma transição de status.

### Anúncios

- O processamento foi separado entre leitura da página, persistência, coordenação, entrega e publicação no Discord.
- Itens só são marcados como enviados após confirmação da mensagem.
- Tentativas de envio incertas:
  - São conferidas pelo identificador da mensagem e pelo histórico do canal.
  - Sem acesso ao histórico necessário, o anúncio permanece pendente.
  - A entrega exatamente uma vez não pode ser garantida em todas as falhas entre Discord e Supabase.
- Ao publicar um anúncio novo, o bot substitui a fixação anterior sem apagar as mensagens antigas.
- A página de anúncios é consultada a cada 10 minutos; anúncios pendentes continuam sendo processados mesmo quando uma consulta falha.
- Datas dos anúncios são exibidas como datas civis, sem conversão para o fuso de cada usuário; verificações de status usam timestamps do Discord.

### Bot e configuração

- As configurações do dashboard são globais e destinadas a um único servidor; alterações administrativas são bloqueadas quando o bot está em mais de um servidor.
- Ao pausar serviços:
  - Ciclos já iniciados podem terminar, mas os próximos não começam.
  - Anúncios pendentes são mantidos para quando a publicação for reativada.
- Permissões administrativas são revalidadas em botões, seleções e formulários, além da verificação na entrada do comando.
- Falhas de persistência não avançam o estado de monitoramento em memória; verificações e ajustes manuais são serializados.

### Estrutura e implantação

- Código reorganizado sob `src/`, com módulos separados para cogs, monitoramento, anúncios, banco de dados, utilitários e componentes compartilhados.
- A inicialização Python passou a ser feita com `python -m src`.
- Dependências de produção e desenvolvimento passaram a usar arquivos de entrada e locks separados, com versões e hashes fixados.
- Python 3.14 passou a ser usado no CI e na imagem Docker.
- Docker:
  - A imagem executa como usuário não root e instala somente dependências de produção.
  - O Compose mantém o `.env` fora da imagem e habilita `no-new-privileges`.

## Corrigido

### Bot

- Anúncios:
  - Páginas vazias, erros HTTP e HTML inesperado não geram anúncios fictícios.
  - Itens só são marcados como enviados após confirmação da mensagem no Discord.
  - Falhas de envio são retomadas em ciclos seguintes, mesmo quando a consulta da página falha.
- Lacunas longas não geram quedas presumidas ou acúmulo de tempo desconhecido.
- Recursos assíncronos são fechados durante o encerramento do bot e exceções de tarefas de fundo são supervisionadas.

### Segurança

- URLs configuradas passam por validação e resolução segura, com limites de tempo para as requisições HTTP.
- O esquema Supabase aplica RLS e concede à `service_role` os privilégios necessários; a secret key é usada exclusivamente no servidor.

## Removido

### GitHub Actions (Workflows)

- Removidos os workflows antigos de atualização anual, publicação de imagem Docker e sincronização de mirrors (Gitlab / Codeberg).
- O build executado pelo CI não publica imagens no Docker Hub.

### Bot e configuração

- Removida a persistência MongoDB e os módulos antigos de banco, comandos e inicialização localizados na raiz do projeto.
- Removida a configuração de canais, cargos e URLs pelos antigos IDs e URLs no `.env`; esses valores agora são definidos em `/configurações`.

## Manutenção

### Dependências

- Separadas as dependências diretas de produção e desenvolvimento, com locks contendo versões resolvidas e hashes.
- Adicionados testes automatizados para comandos, interface, permissões, configuração, presença, monitoramento, persistência, anúncios, segurança HTTP e releases.
- README e guias de instalação, Docker, contribuição e relatos atualizados para o novo fluxo.

### GitHub Actions (Workflows)

- O workflow valida a release antes da publicação e preserva releases já existentes.

### Deploy via Dokploy

- O deploy usa a referência configurada no serviço; a tag da release não é selecionada automaticamente.
- O workflow não reverte a release em caso de falha de deploy. Uma resposta de sucesso confirma apenas que a solicitação foi aceita.

### Docker

- Compose e Dockerfile atualizados para a nova estrutura da aplicação, mantendo o banco de dados no Supabase.
