# Carmel Treinamentos — Manual de Configuração

Este manual registra, na ordem em que foram feitos, os passos para colocar o portal de pé: instalar, ligar o Google Drive, ligar a HeyGen, publicar na internet e conectar o Claude. Cada passo diz como conferir se deu certo.

> **Regra de ouro:** nunca coloque senhas, chaves ou o conteúdo do arquivo da Service Account neste manual, em e-mails ou em chats.
>
> Os nomes de menus do Google, da HeyGen e do Claude mudam com o tempo. Onde isso importa, o texto diz "ou equivalente".

## Como tudo funciona

O portal transforma roteiros guardados no Google Drive em vídeos com avatar da HeyGen e os publica por setor para os colaboradores.

```
1. A equipe coloca o roteiro na pasta  <Setor>/Roteiros  do Drive
2. O portal importa o roteiro  →  o gestor revisa e aprova
3. O Claude gera o vídeo na HeyGen (cerca de 3 minutos)
4. O portal salva o MP4 em  <Setor>/Vídeos  no Drive e publica no catálogo
5. O colaborador assiste no catálogo (só os vídeos do próprio setor)
```

| Peça | Para quê |
|---|---|
| Portal (Django) | Catálogo, fila, revisão do roteiro e permissões por setor |
| Google Drive | Guarda roteiros e vídeos: uma pasta por setor, com as subpastas **Roteiros** e **Vídeos** |
| HeyGen (plano Creator) | Gera o vídeo com avatar. Usada pelo Claude, sem chave de API |
| Claude | Pede a geração à HeyGen e entrega o resultado ao portal |

---

## Passo 1 — Instalar o portal no computador

Use o **PowerShell**, dentro da pasta do projeto.

1. Crie o ambiente e instale as dependências:
   ```
   uv venv --python 3.12
   uv pip install -r requirements.txt
   ```
2. Crie o arquivo de configuração: `copy .env.example .env`.
3. Prepare o banco e os dados iniciais:
   ```
   .venv\Scripts\python.exe manage.py migrate
   .venv\Scripts\python.exe manage.py seed_carmel
   ```
   O `seed_carmel` cria os 6 setores (RH, Recepção, Governança, Alimentos & Bebidas, Lazer & Experiências, Manutenção) e 3 usuários de teste. Pode repetir sem problema.
4. Suba o portal:
   ```
   .venv\Scripts\python.exe manage.py runserver 8008
   ```
5. **Conferir:** abra `http://localhost:8008`. Deve aparecer a tela de login.

## Passo 2 — Usuários e perfis

| Perfil | O que pode |
|---|---|
| Colaborador | Assistir aos vídeos do próprio setor |
| Gestor | O de colaborador + revisar roteiros, sincronizar o Drive, anexar vídeos e reprocessar falhas, só no próprio setor |
| Administrador | Tudo, em todos os setores, e o painel Admin |

Criar um usuário real:
1. Entre em `http://localhost:8008/admin` como administrador.
2. **Usuários → Adicionar usuário**, informe nome e senha, e salve.
3. Na tela seguinte, em **Perfil de Acesso & Setor**, escolha o **Setor** e o **Nível de Acesso**. Marque "Membro da equipe" só para quem pode entrar no Admin.

Usuários de teste (`admin`, `gestor.rh`, `colab.governanca`): a senha padrão está no README. **Troque as senhas ou apague esses usuários antes de usar com pessoas reais.**

## Passo 3 — Google Drive

O portal acessa o Drive por uma **Service Account** (uma "conta robô"). Estrutura final:

```
Unidade Compartilhada
├── RH
│   ├── Roteiros   ← a equipe coloca os roteiros aqui
│   └── Vídeos     ← o portal grava os vídeos aqui
└── (uma pasta por setor, com a mesma estrutura)
```

**3.1 Ativar a API.** Em `console.cloud.google.com`, escolha o projeto da empresa. Em **APIs e serviços → Biblioteca**, busque **Google Drive API** e clique em **Ativar**.

**3.2 Criar a Service Account.** Em **IAM e administrador → Contas de serviço → Criar conta de serviço**, dê um nome e conclua (não precisa de papéis). Anote o e-mail dela (`nome@projeto.iam.gserviceaccount.com`).

**3.3 Gerar a chave.** Abra a conta de serviço, aba **Chaves → Adicionar chave → Criar nova chave → JSON**. Mova o arquivo baixado para `data\service_account.json` e apague a cópia de Downloads. Se a empresa bloquear a criação de chaves, peça uma exceção ao administrador do Google Workspace.

**3.4 Criar a Unidade Compartilhada e dar acesso.** *Obrigatório:* a Service Account não tem espaço no "Meu Drive", e gravar vídeos lá falha. No Drive, crie uma Unidade Compartilhada, abra **Gerenciar membros** e adicione o e-mail da Service Account como **Gerente de conteúdo**. Adicione também as pessoas da equipe.

**3.5 Criar as pastas.** Dentro da Unidade Compartilhada, crie uma pasta por setor com as subpastas `Roteiros` e `Vídeos`. Se faltar alguma, o portal cria na primeira sincronização.

**3.6 Pegar o ID da pasta do setor.** Abra a **pasta do setor** (não a raiz da unidade) e copie o trecho final do endereço: `drive.google.com/drive/folders/<ID>`.
> Não use o ID da raiz da Unidade Compartilhada (costuma começar com `0A`): o portal criaria pastas duplicadas lá.

**3.7 Cadastrar o ID no portal.** No Admin, **Setores / Departamentos →** escolha o setor, cole o ID em **ID da Pasta do Setor no Google Drive** e salve. Repita para cada setor.

**3.8 Conferir.** Coloque um roteiro de teste (um Google Doc com uma ou duas frases) em `Roteiros`. No portal, entre como gestor e clique em **Sincronizar Drive**. O item deve aparecer na **Fila**.

O que a sincronização faz:
- **Roteiros:** importa cada arquivo (Google Docs, DOCX, PDF, TXT e MD). Se você editar o roteiro no Drive **antes de aprová-lo**, clique em **Sincronizar Drive** de novo: o portal lê o texto atualizado. Depois da aprovação, o texto aprovado vale e edições no Drive são ignoradas (para mudar, é preciso criar um novo documento).
- **Vídeos:** publica cada MP4 novo. Se o arquivo corresponde a um item que aguarda o vídeo, conclui esse item; senão, entra como item novo.

Observação: a Service Account só consegue mandar arquivos para a lixeira. Para apagar de vez, esvazie a lixeira da Unidade Compartilhada com uma conta de pessoa.

## Passo 4 — HeyGen

**4.1 Plano.** Foi usado o plano **Creator** (600 créditos por mês). Ele **não inclui geração por API**, por isso o portal não usa a API: o Claude gera os vídeos pelo conector (MCP) da HeyGen, que usa os créditos do plano.

**4.2 Conectar a HeyGen ao Claude Code (para testes no computador).**
1. Cadastre o servidor (uma vez por computador):
   ```
   claude mcp add --transport http -s user heygen https://mcp.heygen.com/mcp/v1/
   ```
   No Windows com a extensão do VS Code, o comando `claude` costuma não estar no PATH. Use o executável da extensão: `& "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-<versão>\resources\native-binary\claude.exe" mcp add ...` (veja a versão com `dir "$env:USERPROFILE\.vscode\extensions" | findstr claude-code`).
2. No painel do Claude Code, digite `/mcp`, escolha `heygen` e conclua o login no navegador com a conta HeyGen.
3. Recarregue a janela (`Ctrl+Shift+P` → **Developer: Reload Window**).
4. **Conferir:** `claude mcp get heygen` deve mostrar `Connected`.

**4.3 Escolher avatar e voz.**
- Padrão adotado: avatar `Abigail_standing_office_front` e voz Lucilene (`e808da2329754929803c8bd98dc36857`, português). Outras vozes em português: Afonso (`9ce5f601f9e04382bb26141d5a3f839d`), Thaís (`a8c7b58e38c44719b3ab36342f080e95`) e Murilo (`d703f08d1ef34302a36945aa3efc7b3f`).
- Para ver outras opções, peça ao Claude para listar avatares e vozes pela HeyGen.
- Onde registrar: o padrão geral vai em `DEFAULT_AVATAR_ID` e `DEFAULT_VOICE_ID` no `.env`. Para um setor ter os seus, preencha no Admin, em **Setores**, os campos **Avatar HeyGen Padrão** e **Voz HeyGen Padrão** (o do setor vale primeiro).

**4.4 O que esperar.** Cada vídeo leva cerca de 3 minutos e consome por volta de 0,7 crédito por segundo de vídeo (estimativa de testes com vídeos curtos de 3 a 6 segundos; confirme com um roteiro de 1 minuto antes de planejar o volume). O roteiro pode ter no máximo 5.000 caracteres. O link do MP4 da HeyGen expira em cerca de 7 dias, por isso o portal guarda uma cópia no Drive.

## Passo 5 — Banco de dados (Aiven, PostgreSQL)

Localmente o portal usa um arquivo SQLite (`data/db.sqlite3`). Em um servidor como a Render, esse arquivo se perde a cada deploy; por isso o banco fica no **Aiven** (PostgreSQL), que guarda usuários, roteiros e vídeos de forma permanente.

1. No Aiven, crie um serviço **PostgreSQL** (o plano gratuito serve para começar) e espere ficar **Running**.
2. Na página do serviço, copie a **Service URI**, no formato `postgres://avnadmin:SENHA@HOST:PORTA/defaultdb?sslmode=require`. Ela contém a senha: trate como segredo.
3. Em **Allowed IP addresses** (ou equivalente) do serviço, libere o acesso do seu computador e da Render. Se a lista aceitar `0.0.0.0/0`, qualquer origem conecta, e a proteção fica só na senha.
4. Coloque a URI na variável `DATABASE_URL`: no `.env` (para trabalhar no computador) e em **Environment** na Render. Sem `DATABASE_URL`, o portal volta a usar o SQLite local.
5. Crie as tabelas no banco novo e o primeiro administrador (PowerShell, na pasta do projeto, com `DATABASE_URL` no `.env`):
   ```
   .venv\Scripts\python.exe manage.py migrate
   .venv\Scripts\python.exe manage.py createsuperuser
   ```
   O `createsuperuser` pergunta nome de usuário, e-mail (pode deixar vazio) e senha.
6. **Conferir:** `.venv\Scripts\python.exe manage.py showmigrations treinamentos` mostra todas as migrações com `[X]`, e você consegue entrar no portal com o usuário criado.

Observações:
- O banco do Aiven começa **vazio**: os dados que estavam no SQLite local não vão junto (setores, usuários e itens). O `seed_carmel` recria os setores e os usuários de teste; as pastas do Drive de cada setor precisam ser cadastradas de novo no Admin (passo 3.7).
- O `seed_carmel` roda a cada início do serviço na Render e recria os usuários de teste (`admin`, `gestor.rh`, `colab.governanca`) com a senha padrão **se eles não existirem**. Com banco permanente, apague ou troque a senha desses usuários, senão contas conhecidas voltam a existir.
- Para voltar ao SQLite local, deixe `DATABASE_URL` vazio.

## Passo 6 — Publicar na internet (Render)

O portal foi publicado na Render com Docker (arquivo `Dockerfile` do projeto), no endereço `https://carmel-treinamentos.onrender.com`.

1. Na Render, crie um **Web Service** apontando para o repositório do projeto, com ambiente **Docker**. Cada `git push` faz um novo deploy.
2. Em **Environment**, defina as variáveis:

   | Variável | Valor |
   |---|---|
   | `DJANGO_SECRET_KEY` | Uma chave longa e secreta (obrigatória com debug desligado) |
   | `DJANGO_DEBUG` | `false` |
   | `DJANGO_ALLOWED_HOSTS` | O endereço do serviço (ex.: `carmel-treinamentos.onrender.com`) |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | O endereço com `https://` |
   | `DEFAULT_AVATAR_ID` e `DEFAULT_VOICE_ID` | Os do passo 4.3 |
   | `DATABASE_URL` | A Service URI do banco do Aiven (passo 5) |
   | `GOOGLE_SERVICE_ACCOUNT_FILE` | Caminho do arquivo da Service Account (veja o item 3) |
   | `MCP_TOKEN` | A chave do conector (passo 7) |

3. **Service Account na Render:** em **Secret Files**, crie o arquivo `service_account.json` com o conteúdo do JSON e use `GOOGLE_SERVICE_ACCOUNT_FILE=/etc/secrets/service_account.json`.
4. **Conferir:** abra o endereço do serviço e entre no portal.

Limitações do ambiente de **teste** na Render: sem `DATABASE_URL`, o banco (SQLite) volta ao início a cada deploy; a instância gratuita dorme e a primeira resposta leva cerca de 1 minuto, o modo de depuração pode estar ligado e os usuários de teste são recriados com a senha padrão a cada início. Para uso real, resolva esses pontos (instância sempre ligada, debug desligado e senhas trocadas).

## Passo 7 — Conectar o Claude ao portal (conector MCP)

O portal tem um conector que deixa o Claude (no site claude.ai, conta Teams) listar os roteiros aprovados e entregar os vídeos prontos, sem acesso ao servidor nem ao banco.

**6.1 Ligar o conector.**
1. Gere uma chave: `.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Defina `MCP_TOKEN` com essa chave (no `.env` local ou em **Environment** na Render, sem espaços nem aspas) e faça o deploy. Sem `MCP_TOKEN`, o conector fica desligado.
3. O endereço do conector é: `https://carmel-treinamentos.onrender.com/mcp/<chave>/` (termina em `/`).
4. **Conferir:** abra esse endereço no navegador. **405** significa que está certo; **404** significa que a chave do endereço não é igual ao `MCP_TOKEN`.

**6.2 Cadastrar no Claude.** Um dono ou administrador do Teams abre as configurações de **Conectores** em claude.ai e escolhe **Adicionar conector personalizado**: nome "Carmel Treinamentos", URL com a chave (sem preencher OAuth). Adicione também a HeyGen: `https://mcp.heygen.com/mcp/v1/`, entrando com a conta HeyGen.

**6.3 Criar um Projeto no Claude** com estas instruções, para qualquer pessoa só precisar pedir "gere os vídeos aprovados":

```
Você produz os vídeos de treinamento da Carmel Hotéis. Use os conectores "Carmel Treinamentos" e "HeyGen".

Quando eu pedir para gerar os vídeos:
1. Chame list_awaiting_videos. Se não houver itens, diga isso e pare.
2. Para cada item, um de cada vez, chame create_video_from_avatar da HeyGen com:
   - script: o campo "roteiro", EXATAMENTE como veio, sem reescrever, resumir ou corrigir;
   - avatarId e voiceId: os campos "avatar_id" e "voice_id" do item;
   - aspectRatio 16:9 e resolução 720p.
3. Chame mark_video_rendering com o video_id da HeyGen.
4. Acompanhe com get_video da HeyGen a cada 30 a 60 segundos até "completed". Nunca recrie o vídeo para verificar o andamento.
5. Quando estiver "completed", chame save_generated_video com o video_url, o ID da HeyGen e a duração (duration).
6. Ao final, informe por item: título, duração e se foi publicado. Se alguma etapa falhar, diga qual e não tente de novo sem me avisar.

Nunca gere o mesmo item duas vezes e nunca altere o texto do roteiro.
```

**6.4 As quatro ferramentas do conector**

| Ferramenta | O que faz |
|---|---|
| `list_awaiting_videos` | Lista os roteiros aprovados, com texto exato, avatar e voz |
| `mark_video_rendering` | Marca o item como "Renderizando" |
| `save_generated_video` | O portal baixa o MP4, salva no Drive do setor e publica |
| `get_video_status` | Consulta o status de um item |

**6.5 Segurança.** A chave no endereço é um segredo: ela aparece nos registros de acesso do servidor. Se vazar, troque o `MCP_TOKEN` e atualize o conector. Só são baixados links https de `heygen.ai` e `heygen.com`. Login por OAuth e limite de chamadas ainda não foram implementados.

## Uso no dia a dia

1. **Roteiro:** a equipe coloca o documento em `<Setor>/Roteiros` no Drive. O gestor clica em **Sincronizar Drive**.
2. **Revisão:** na **Fila**, o gestor abre **Revisar roteiro**, corrige o texto se precisar e aprova. O item passa para "Aguardando Vídeo".
3. **Vídeo:** alguém abre o Projeto no Claude e escreve "gere os vídeos aprovados". O Claude gera os vídeos e o portal os publica.
   - *Sem o Claude:* na Fila, **Anexar vídeo** mostra o roteiro, o avatar e a voz; gere no site da HeyGen e anexe o MP4.
4. **Catálogo:** os colaboradores assistem aos vídeos do próprio setor. O portal registra quem assistiu e quem terminou o vídeo.

Comandos úteis (PowerShell, na pasta do projeto):

| Comando | O que faz |
|---|---|
| `.venv\Scripts\python.exe manage.py sync_drive` | Sincroniza o Drive uma vez |
| `.venv\Scripts\python.exe manage.py sync_drive --watch` | Sincroniza continuamente (a cada 5 minutos) |
| `.venv\Scripts\python.exe manage.py seed_carmel` | Recria setores e usuários de teste que faltarem |
| `.venv\Scripts\python.exe manage.py test treinamentos` | Roda os testes automáticos (leva cerca de 2 minutos) |

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `DisallowedHost` ao abrir o portal | O endereço não está em `DJANGO_ALLOWED_HOSTS` | Adicione o endereço e reinicie |
| A sincronização não importa nada | Arquivo fora de **Roteiros**, formato não aceito ou já importado | Confira a pasta e o formato |
| "Não foi possível salvar no Drive" | Setor sem pasta cadastrada ou Service Account ausente | Refaça o passo 3 |
| Pastas duplicadas na raiz da Unidade Compartilhada | Foi cadastrado o ID da raiz, não o da pasta do setor | Use o ID da pasta do setor (3.6) |
| Roteiro recusado por tamanho | Mais de 5.000 caracteres | Reduza o texto ou divida em partes |
| Item parado em "Aguardando vídeo" ou "Renderizando" | O vídeo ainda não foi gerado ou salvo (no servidor sem Drive, o salvamento falha) | Gere o vídeo; confira o Drive no servidor; use **Anexar vídeo** se preciso |
| O vídeo não abre depois de alguns dias | Sem cópia no Drive, o link da HeyGen expirou | Gere de novo, com o Drive configurado |
| Claude mostra "Não foi possível alcançar" o conector | Chave diferente do `MCP_TOKEN`, deploy antigo ou instância dormindo | Teste o endereço no navegador (deve dar 405) e acorde a instância |
| O botão "Sincronizar Drive" mostra erro de resposta | O servidor devolveu uma página de erro | Tente de novo; veja os **Logs** do serviço na Render |

## Pendências e riscos

- **Geração ainda depende de alguém pedir:** o Claude na web só trabalha quando uma pessoa abre a conversa; não roda sozinho.
- **Só o RH tem pasta cadastrada:** faltam os outros cinco setores (passos 3.5 a 3.7).
- **Ambiente de produção:** ver as limitações do passo 6 (instância ligada, debug desligado, senhas trocadas).
- **Chave do conector no endereço:** o ideal para produção é OAuth e limite de chamadas.
- **Não testado:** o ciclo completo (gerar na HeyGen e salvar no Drive) a partir do Claude na web, com o Drive configurado na Render.
- **Qualidade dos vídeos:** não foi avaliada a voz em português nem a sincronia da boca nos vídeos de teste.

## Checklist de implantação

- [ ] Portal instalado e abrindo (passo 1)
- [ ] Senhas de teste trocadas e usuários reais criados (passo 2)
- [ ] Service Account criada, chave em `data\service_account.json` e acesso dado na Unidade Compartilhada (3.1 a 3.4)
- [ ] Pasta de cada setor com `Roteiros` e `Vídeos`, e o ID cadastrado no Admin (3.5 a 3.7)
- [ ] Roteiro de teste sincronizado e visível na Fila (3.8)
- [ ] HeyGen conectada ao Claude e avatar e voz definidos (passo 4)
- [ ] Banco no Aiven criado, `DATABASE_URL` definida, migrações aplicadas e administrador criado (passo 5)
- [ ] Portal publicado com as variáveis e a Service Account (passo 6)
- [ ] `MCP_TOKEN` definido, endereço do conector dando 405 e conectores cadastrados no Claude (passo 7)
- [ ] Teste de ponta a ponta: roteiro aprovado, vídeo gerado, MP4 em `<Setor>/Vídeos`, vídeo no catálogo
- [ ] Um colaborador do setor assiste ao vídeo, e um de outro setor não o vê
