# Contribuindo com o projeto

Contribuições em código, testes, documentação, revisão e sugestões são bem-vindas. Ao participar, siga o [Código de Conduta](Code_Of_Conduct.md).

## Reportar problemas e sugerir melhorias

Antes de abrir uma issue, procure relatos semelhantes. Use os roteiros de [relato de bugs](Bug_Report.md) e [sugestão de funcionalidades](Feature_Request.md) para reunir as informações necessárias. Nunca inclua tokens, chaves, arquivos `.env` ou informações privadas em uma issue pública.

## Preparar o ambiente

O projeto usa Python 3.14 no Docker e no CI. Faça um fork, clone seu repositório e entre na pasta do projeto. Em seguida, crie um ambiente virtual e instale as dependências:

```sh
python -m venv .venv
```

Ative o ambiente com `.venv\Scripts\Activate.ps1` no PowerShell ou `source .venv/bin/activate` em Linux/macOS. Depois execute:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
ruff check .
pyright
pip-audit -r requirements.txt
coverage run -m unittest discover -s tests -v
coverage report
```

Os testes não precisam de credenciais do Discord ou Supabase: usam HTTP simulado e repositórios Git locais, exigindo o executável Git. Para executar o bot de verdade, configure um projeto de teste e o `.env` conforme o [README](../README.md). Não use credenciais de produção em testes ou exemplos. Os testes simulados não substituem a verificação em Discord, Supabase, Codeberg e GitLab reais.

## Atualizar dependências

Edite `requirements.in` para alterar dependências diretas. Com o [uv](https://docs.astral.sh/uv/) instalado, regenere as versões transitivas e hashes para Python 3.14:

```sh
uv pip compile requirements.in --universal --python-version 3.14 --generate-hashes --upgrade -o requirements.txt
```

Ferramentas usadas apenas no desenvolvimento ficam em `requirements-dev.in`; regenere o lock correspondente com:

```sh
uv pip compile requirements-dev.in --universal --python-version 3.14 --generate-hashes --upgrade -o requirements-dev.txt
```

As configurações compartilhadas de Ruff, Pyright e Coverage.py ficam no `pyproject.toml`. O CI executa Ruff via pre-commit, Pyright, `pip-audit` e Coverage.py. O Pyright verifica o banco de dados, o monitoramento e os módulos parser/serviço de anúncios; amplie o escopo gradualmente ao corrigir avisos no restante da aplicação. A cobertura considera apenas `src` e exige pelo menos 70%; busque aumentá-la com testes úteis, sem testar detalhes internos sem valor ou excluir código relevante da medição.

Para executar o Ruff automaticamente nos arquivos preparados para commit, instale o hook uma vez por clone:

```sh
pre-commit install
pre-commit run --all-files
```

Revise o diff, instale `requirements-dev.txt` em ambiente limpo e execute os testes e o build Docker. O Docker de produção instala somente `requirements.txt`. O Dependabot pode propor alterações nos arquivos de dependências; confirme que a lista gerada continua coerente e regenere-a quando necessário. Fixar versões e hashes não fixa a imagem base Docker nem garante que um pacote nunca precise de compilação em outra plataforma.

## Chaves SSH dos mirrors

Mirrors são opcionais: para desativá-los, defina a variável de repositório do GitHub Actions `MIRRORS_ENABLED=false`. Sem essa variável, continuam ativos por padrão. Os secrets abaixo e os tokens de release `GITLAB_PROJECT_ID`, `GITLAB_ACCESS_TOKEN` e `CODEBERG_TOKEN` só são necessários quando ativos; a release GitHub e o deploy opcional podem funcionar sem mirrors.

Além da chave privada `MIRROR_SSH_PRIVATE_KEY`, configure o secret `MIRROR_SSH_KNOWN_HOSTS` no GitHub com as entradas públicas de `codeberg.org` e `gitlab.com` em formato OpenSSH `known_hosts` (`host tipo chave`, uma por linha). Obtenha as chaves e **confira suas impressões digitais por fontes independentes**: [Codeberg](https://docs.codeberg.org/security/ssh-fingerprint/) e [GitLab.com](https://docs.gitlab.com/user/gitlab_com/#ssh-host-keys-fingerprints). Uma saída de `ssh-keyscan` isolada não comprova a identidade do servidor; compare-a com os fingerprints oficiais antes de usá-la. Atualize o secret quando as chaves oficiais mudarem. Sem entradas válidas, o espelhamento e as etapas dependentes falharão em vez de confiar automaticamente no servidor.

## Enviar uma alteração

1. Crie uma branch a partir da versão atual do projeto: `git switch -c minha-alteracao`.
2. Faça alterações relacionadas ao objetivo da contribuição e acrescente ou atualize os testes relevantes.
3. Execute os testes e atualize a documentação quando mudar a configuração ou o comportamento.
4. Revise seu diff, faça o commit e envie a branch para seu fork.
5. Abra um pull request usando o [roteiro de PR](Pull_Request.md). Explique o que mudou, como foi testado e eventuais limitações.

O CI executa os testes e valida o build Docker em pushes para qualquer branch, tags e pull requests, sem publicar a imagem. Quando ativos, os mirrors recebem branches após o CI e tags antes da criação da release; exclusões e eventos manuais de release usam um fluxo separado. Tags que apontem para o histórico da `main` seguem para criação da release mesmo com mirrors desativados. Sucesso no CI não substitui testes manuais de integração com Discord e Supabase quando a alteração depender desses serviços.

Para preparar uma release, substitua a versão anterior em `CHANGELOG.md` por um cabeçalho `## [1.2.3]`, categorias `###` e itens `- ` com as mudanças revisadas. Faça commit na `main` e envie a tag correspondente (`1.2.3` ou `v1.2.3`). O workflow lê o arquivo do commit da tag, valida a versão e acrescenta separadamente as notas automáticas do GitHub; não infere nem reescreve o changelog. O conteúdo anterior permanece nas releases publicadas. Releases existentes não são alteradas; erros de validação ou da API de notas impedem a criação de uma nova release.

O Dependabot propõe atualizações semanais para dependências Python, GitHub Actions e imagem base Docker. Revise as alterações e os resultados do CI antes de integrá-las; quando necessário, valide também os serviços externos manualmente.

## Pontos importantes

- Verificações de status, tempos acumulados e lacunas sem monitoramento têm regras descritas no [README](../README.md). Inclua testes para mudanças nessa lógica.
- O esquema em `database/sqls/schema.sql` é destinado a instalações novas; alterações nele devem considerar permissões, RLS e integridade dos dados.
- As mensagens principais usam Components V2. Confirme que mudanças na interface não misturam componentes V2 com conteúdo ou embeds na mesma mensagem.
- O scraping depende da estrutura da página monitorada; documente mudanças de seletores e como foram verificadas.
- Anúncios separam parser, repositório, coordenação, fila e publicação Discord em `src/announcements/parser.py`, `src/database/announcements.py`, `src/announcements/service.py`, `src/announcements/delivery.py` e `src/announcements/discord.py`, respectivamente. Preserve a recuperação de envios incertos ao alterar a fila.
