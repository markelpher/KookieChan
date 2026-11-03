# Guia para agentes de código

Estas instruções se aplicam a todo o repositório. Leia também `README.md` antes de mudanças que afetem comportamento ou implantação. Se uma instrução local em um subdiretório for adicionada no futuro, siga-a junto com este guia.

## Objetivo e idioma

- Kookie Chan é um bot comunitário do Discord, em Python, que monitora a disponibilidade do Kookie e publica anúncios.
- Responda ao usuário em português, salvo pedido explícito por outro idioma. Mantenha documentação e mensagens novas em português, respeitando o idioma existente no trecho editado.
- Prefira soluções pequenas, explícitas e adequadas ao porte do projeto. Não adicione dependências, abstrações ou ferramentas sem uma necessidade demonstrável.
- Preserve alterações preexistentes no workspace. Antes de editar, confira o estado e o contexto dos arquivos; não descarte trabalho do usuário, não faça reset e não reverta arquivos fora do escopo solicitado.
- Todo arquivo Python novo deve começar com uma docstring de módulo em `"""`, em português, explicando brevemente sua finalidade. Mantenha a docstring na primeira linha; não use docstrings em classes ou funções. Comentários explicativos no restante do código devem usar `#`.

## Arquitetura

- `src/main.py` e `src/__main__.py`: inicialização, ciclo de vida do bot e carregamento das cogs. A execução normal é `python -m src`.
- `src/cogs/`: comandos e tarefas do Discord. Evite concentrar regra de negócio, persistência ou parsing nas cogs.
- `src/database/database.py`: cliente REST assíncrono do Supabase e persistência do estado de status.
- `src/database/announcement_repository.py`: repositório e operações da fila de anúncios.
- `src/monitoring/`: configurações e regras de cálculo/estado do monitoramento.
- `src/announcements/`: parsing HTML (`parser.py`), coordenação (`service.py`), entrega e recuperação (`delivery.py`) e publicação Discord (`discord.py`).
- `src/core/`: utilitários HTTP compartilhados e supervisão de tarefas em segundo plano.
- `src/ui/components.py`: componentes compartilhados; a interface principal usa Discord Components V2.
- `database/sqls/schema.sql`: esquema e permissões do Supabase. O README explica o uso em instalações novas e existentes.
- `tests/`: testes `unittest`, incluindo testes assíncronos, servidor HTTP local e diretórios temporários.

Mantenha os limites entre esses módulos. Não duplique acesso HTTP, persistência ou lógica de domínio quando já houver um serviço/repositório apropriado.

## Regras de comportamento importantes

### Discord e tarefas assíncronas

- Preserve a compatibilidade com `discord.py` 2.7.1 ou superior e Python 3.14.
- Mensagens que usam Components V2 não devem misturar esses componentes com embeds/conteúdo tradicional na mesma mensagem. Reutilize `PanelContent`, `panel` e helpers existentes.
- Faça validação de permissões tanto na entrada do comando quanto ao processar interações posteriores (botões, selects e modais). A configuração oficial é global e destinada a um único servidor; alterações administrativas devem falhar fechadas fora desse cenário.
- Tarefas de fundo devem ter ciclo de vida e exceções supervisionados. Use `src/core/background.py` para criar/cancelar tarefas e respeite o `owner` da cog; não crie tarefas "soltas" com `asyncio.create_task` ou `bot.loop.create_task` sem justificativa e tratamento de ciclo de vida.
- Não bloqueie o event loop com I/O síncrono. Use APIs assíncronas e feche sessões/conexões durante o encerramento.

### Monitoramento de status

- Preserve as regras em `src/monitoring/` e documentadas no README: falhas consecutivas confirmam queda; recuperação é imediata; lacunas longas não inferem indisponibilidade nem acumulam tempo desconhecido.
- Uma verificação e a atualização do estado persistido são atômicas pela RPC `record_status_check`; não separe essas gravações em operações independentes.
- O serviço deve serializar verificações e ajustes manuais e só avançar o estado em memória após persistência bem-sucedida.
- Métricas `total_online` e `total_offline` representam o último período concluído daquele estado, não somas históricas. Não altere essa semântica sem atualizar testes e documentação.
- O ajuste manual altera a estimativa do período atual, não cria verificações históricas. O contador de quedas conta apenas transições confirmadas de online para offline.

### Anúncios e persistência

- Preserve a separação parser → repositório → serviço → entrega → publicação Discord.
- Itens pendentes só devem ser marcados enviados após confirmação do envio. Preserve a recuperação de envios incertos e não introduza republicações silenciosas se o histórico do canal estiver indisponível.
- A entrega entre Supabase e Discord não é uma transação exatamente-uma-vez; comunique essa limitação e mantenha o mecanismo de recuperação existente.
- O parser não deve fabricar anúncios quando faltarem seletores/dados. Diferencie página vazia de erro HTTP ou HTML inesperado.
- Ao mudar o esquema SQL, considere instalações existentes, idempotência, transações, RLS, privilégios de `service_role`, índices e concorrência. Não remova dados nem amplie permissões sem necessidade. Atualize testes/documentação de implantação.

### HTTP, SSRF e segredos

- URLs informadas por administradores são entrada não confiável. Reutilize `src/core/http.py` e as validações existentes; não contorne a resolução segura, a checagem de IPs literais ou os limites de timeout.
- Não registre tokens, chaves, credenciais, URL com dados sensíveis ou corpos de resposta remotos. Erros voltados ao usuário devem ser genéricos; logs podem informar contexto não sensível e o tipo da exceção.
- Não leia nem exponha `.env` ou segredos. `.env.example` deve conter apenas valores ilustrativos.
- O Supabase usa secret key exclusivamente no servidor; nunca introduza chave no código cliente, frontend, logs ou documentação pública.

## Dependências, configuração e implantação

- `requirements.in` contém dependências diretas de produção; `requirements.txt` fixa transitivas e hashes para produção.
- `requirements-dev.in` inclui produção e ferramentas de desenvolvimento; `requirements-dev.txt` é o lock usado em desenvolvimento/CI. Ao alterar dependências, regenere os locks com `uv pip compile <arquivo>.in --universal --python-version 3.14 --generate-hashes --upgrade -o <arquivo>.txt`.
- O Docker de produção instala somente `requirements.txt` e copia o código da aplicação. Mantenha ferramentas de desenvolvimento fora da imagem.
- `docker/docker-compose.yml` usa o `.env` local sem incorporá-lo à imagem. Preserve o usuário não-root e as opções de segurança do container.
- `.gitignore` e `.dockerignore` têm objetivos diferentes: o primeiro controla Git; o segundo reduz o contexto de build e impede envio de segredos/arquivos desnecessários. Ao adicionar artefatos ou arquivos necessários ao build, revise ambos sem excluir arquivos necessários à imagem.
- O projeto não usa `uv.lock`; não adicione esse lock sem decisão explícita de migrar o fluxo de dependências.

## Processo de alteração

1. Identifique os arquivos e os testes relacionados antes de editar; preserve mudanças não relacionadas.
2. Faça mudanças coesas e limitadas ao pedido. Evite refatorações amplas incidentais.
3. Para correções de bugs, acrescente um teste que reproduza o caso sempre que razoável. Para comportamento alterado, atualize a documentação correspondente.
4. Não enfraqueça testes, verificações de segurança, tipagem ou limites de cobertura para fazer uma alteração passar.
5. Não atualize locks, versões de ações ou imagem-base como efeito colateral; faça isso somente quando fizer parte do objetivo.
6. Ao final, resuma o que mudou e informe com precisão as verificações executadas e qualquer limitação.

## Verificações

Use Python 3.14. Após mudanças de código, execute as verificações pertinentes; para uma alteração ampla, execute a sequência equivalente ao CI:

```sh
python -m compileall -q src tests
pre-commit run --all-files
pyright
pip-audit -r requirements.txt
coverage run -m unittest discover -s tests -v
coverage report
```

O Ruff é executado pelo hook de pre-commit, com as regras configuradas em `pyproject.toml`. O Pyright verifica somente os caminhos listados ali; ao ampliar esse escopo, corrija os avisos antes de incluí-lo. Para validar a imagem/Compose, use os comandos do workflow `.github/workflows/ci.yml` quando Docker estiver disponível. Se uma verificação não puder ser executada, informe isso em vez de declarar sucesso.

## GitHub Actions e releases

- Mantenha permissões mínimas, validação antes de publicação e proteção contra corrida/reversão destrutiva.
- Não altere fluxos de release ou Dokploy sem conferir o README; são integrações externas com segredos e comportamento operacional sensível.
