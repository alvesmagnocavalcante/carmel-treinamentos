# Carmel Treinamentos — Guia de Configuração

Atualizado em 05/11/2026. Este guia registra, passo a passo, tudo o que foi configurado e testado para o portal funcionar de ponta a ponta, e como conferir se cada etapa deu certo.

**Regra de ouro:** não coloque senhas, chaves de API nem o conteúdo do JSON da Service Account neste arquivo, em e-mails ou em chats.

Os nomes de menus do Google Cloud, do Google Drive e da HeyGen podem mudar com o tempo. Onde isso importa, o texto diz "ou algo equivalente".

## Sumário

1. Visão geral
2. Antes de começar
3. Instalar o portal
4. Arquivo `.env`
5. Acessos e perfis
6. HeyGen (plano Creator + MCP)
7. Google Drive (Service Account e pastas)
8. Operação no dia a dia
9. Solução de problemas
10. Testes realizados
11. Pendências e riscos
12. Checklist de implantação

## 1. Visão geral

O portal transforma roteiros guardados no Google Drive em vídeos com avatar da HeyGen e os publica por setor para os colaboradores. Cada roteiro passa por revisão humana antes de gastar créditos da HeyGen.

| Peça | Função |
|---|---|
| Portal Django | Catálogo, fila, revisão do roteiro, permissões por setor. Banco SQLite em `data/db.sqlite3`. |
| Google Drive | Repositório central (conta unificada): uma pasta por setor, com as subpastas **Roteiros** e **Vídeos**. |
| HeyGen | Plano Creator, usado pelo conector **MCP**, sem chave de API. |
| Claude | Gera o vídeo pelo MCP e registra o resultado no portal (ou uma pessoa gera no site e anexa o MP4). |

Fluxo completo:

```
Responsável coloca o roteiro em  <Setor>/Roteiros  (Drive)  — ou o gestor envia pelo portal
        │
        ▼
Varredura importa o arquivo  →  status "Na Fila"
        │
        ▼
Sistema extrai o texto e limpa a formatação  →  "Aguardando Revisão do Roteiro"
        │
        ▼
Gestor revisa e aprova no portal (limite de 5.000 caracteres)
        │
        ▼
Item fica "Aguardando Vídeo"  (roteiro aprovado, avatar e voz definidos)
        │
        ▼
Claude gera o vídeo na HeyGen pelo MCP  (~3 min)  e salva o MP4 em  <Setor>/Vídeos  (Drive)
        │
        ▼
Gestor clica em "Sincronizar Drive"  →  o portal carrega o vídeo e liga ao roteiro
        │
        ▼
Item "Concluído"; colaborador assiste no catálogo (o portal lê o MP4 do Drive, só do próprio setor)
```

## 2. Antes de começar

Você precisa ter:

| Item | Para quê | Como conferir |
|---|---|---|
| Windows 10/11 com PowerShell | Rodar os comandos deste guia | Abra o menu Iniciar e digite `PowerShell` |
| Python 3.12 e `uv` | Executar o portal | `uv --version` e `uv python list` |
| VS Code com a extensão **Claude Code** | Usar o MCP da HeyGen e pedir a geração dos vídeos | Ícone do Claude no VS Code |
| Conta Google Workspace com permissão de criar **Unidade Compartilhada** | Guardar roteiros e vídeos | Menu "Unidades compartilhadas" no Google Drive |
| Acesso ao Google Cloud Console da empresa | Criar a Service Account | `https://console.cloud.google.com` |
| Conta HeyGen no plano **Creator** | Gerar os vídeos | Ver seção 6.1 |

Unidades Compartilhadas só existem em planos Google Workspace; em conta pessoal gratuita o menu não aparece.

## 3. Instalar o portal

Todos os comandos abaixo são para o **PowerShell**, dentro da pasta do projeto (`carmel-treinamentos`). Para abrir lá: no Explorador de Arquivos, entre na pasta, clique na barra de endereço, digite `powershell` e tecle Enter.

### 3.1 Ambiente Python e dependências

1. Crie o ambiente virtual (só na primeira vez):
   ```
   uv venv --python 3.12
   ```
   Resultado esperado: a pasta `.venv` aparece no projeto.
2. Instale as dependências:
   ```
   uv pip install -r requirements.txt
   ```
   Instala: Django, httpx, requests, pypdf, python-docx, python-dotenv, google-api-python-client e google-auth.
3. Para rodar comandos do projeto, use o Python do ambiente. Duas formas equivalentes:
   - Direto: `.venv\Scripts\python.exe manage.py <comando>`
   - Ou ative o ambiente uma vez por janela com `.venv\Scripts\Activate.ps1` e depois use `python manage.py <comando>`.

   Se o PowerShell recusar o `Activate.ps1` por política de execução, use a forma direta.

### 3.2 Arquivo `.env`

1. Copie o modelo: `copy .env.example .env`.
2. Preencha os valores conforme a seção 4.

### 3.3 Banco de dados e dados iniciais

1. Confira a instalação:
   ```
   .venv\Scripts\python.exe manage.py check
   ```
   Esperado: `System check identified no issues (0 silenced).`
2. Crie as tabelas:
   ```
   .venv\Scripts\python.exe manage.py migrate
   ```
   Esperado: uma lista de `Applying ... OK`, terminando na migração `treinamentos.0007_awaiting_video_status` (são sete migrações do app).
3. Crie setores e usuários de teste:
   ```
   .venv\Scripts\python.exe manage.py seed_carmel
   ```
   Esperado: `[OK] Seed concluído.` O comando é seguro para repetir; não sobrescreve o que já existe.
4. Antes de qualquer migração futura, faça uma cópia do banco: `copy data\db.sqlite3 data\db.sqlite3.bak-AAAA-MM-DD`. O `.gitignore` já ignora esses backups.

### 3.4 Subir o servidor

1. Rode: `.venv\Scripts\python.exe manage.py runserver 8008`.
2. Abra `http://localhost:8008` no navegador. Esperado: a tela de login.
3. Entre com um usuário de teste (seção 5) e confira que o catálogo abre.
4. A administração fica em `http://localhost:8008/admin`.
5. Para acessar de outro computador da rede, adicione o IP da máquina em `DJANGO_ALLOWED_HOSTS` no `.env` e rode `runserver 0.0.0.0:8008`.

### 3.5 Varredura automática do Drive

Em **outro** PowerShell, deixe rodando: `.venv\Scripts\python.exe manage.py sync_drive --watch`. Esperado: `Modo contínuo: varrendo a cada 5 minuto(s).` Para parar, use `Ctrl+C`.

### 3.6 Testes automáticos

`.venv\Scripts\python.exe manage.py test treinamentos` — esperado: `OK`. A última execução completa passou com 64 testes; leva cerca de 2 minutos.

### 3.7 Produção

Para uso real, e não só em teste:
- `DJANGO_DEBUG=false` e um `DJANGO_SECRET_KEY` próprio e longo (o sistema se recusa a subir sem ele com debug desligado).
- `DJANGO_ALLOWED_HOSTS` com o domínio, `DJANGO_CSRF_TRUSTED_ORIGINS` com o endereço `https://...`, e HTTPS.
- Um servidor de aplicação com vários processos (por exemplo gunicorn atrás de um proxy): o portal entrega os vídeos do Drive e o `runserver` aguenta pouco acesso simultâneo.
- Trocar as senhas de teste (seção 5).

## 4. Arquivo `.env`

| Variável | Para que serve | Valor / estado atual |
|---|---|---|
| `HEYGEN_MOCK_MODE` | `true` simula a HeyGen (só afeta o caminho antigo por API) | `true` |
| `HEYGEN_API_KEY` | Chave da API da HeyGen | Preenchida, mas **não é usada** no fluxo atual (a API recusa a geração; seção 6.2) |
| `HEYGEN_API_URL` | Endereço da API | `https://api.heygen.com` |
| `DEFAULT_AVATAR_ID` | Avatar padrão | `Abigail_standing_office_front` |
| `DEFAULT_VOICE_ID` | Voz padrão | `e808da2329754929803c8bd98dc36857` (Lucilene, português) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | Caminho do JSON da Service Account | `data/service_account.json` |
| `DRIVE_SYNC_INTERVAL_MINUTES` | Intervalo do `sync_drive --watch` | `5` |
| `HEYGEN_GENERATION_MODE` | `manual`: depois da aprovação o item fica "Aguardando Vídeo" e o vídeo é gerado fora do portal. `api`: o portal chama a API da HeyGen (exige saldo de API) | `manual` (padrão) |
| `MAX_VIDEO_MB` | Tamanho máximo do MP4 anexado em "Anexar vídeo" | `500` |
| `REQUIRE_SCRIPT_REVIEW` | `true`: o gestor aprova o roteiro antes de gerar o vídeo | `true` (padrão, ver `.env.example`) |
| `MAX_UPLOAD_MB` | Tamanho máximo de upload manual | `20` |
| `HEYGEN_POLL_INTERVAL_SECONDS` / `HEYGEN_POLL_TIMEOUT_MINUTES` | Consulta da API antiga | `20` / `30` |
| `LOG_LEVEL` | Nível dos logs do portal | `INFO` |
| `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Segurança do Django | Ver `.env.example` |

Regras importantes:
- Valores em **Admin → Configurações do Sistema** têm prioridade sobre o `.env`; valor vazio faz o sistema usar o `.env`.
- O `.env` e o `data/service_account.json` estão no `.gitignore`: não os copie para pastas compartilhadas nem anexe em e-mails.
- Depois de mudar o `.env`, reinicie o `runserver` e o `sync_drive --watch`.

## 5. Acessos e perfis

| Perfil | Pode |
|---|---|
| Colaborador | Assistir os vídeos do próprio setor. Sem setor definido, não vê nada. |
| Gestor | Tudo do colaborador + enviar documentos, sincronizar o Drive, revisar roteiros e reprocessar falhas, só do próprio setor. Sem setor definido, não envia. |
| Administrador | Todos os setores e o Django Admin. |

Setores cadastrados pelo seed: `rh`, `recepcao`, `governanca`, `alimentos_bebidas`, `experiencias`, `manutencao`.

### 5.1 Criar um usuário real

1. Entre em `http://localhost:8008/admin` com um administrador.
2. Vá em **Usuários → Adicionar usuário**, informe nome de usuário e senha, e salve.
3. Na tela seguinte, role até **Perfil de Acesso & Setor** e escolha o **Setor** e o **Nível de Acesso** (colaborador, gestor ou administrador). Marque "Membro da equipe" (`is_staff`) só para quem pode entrar no Admin.
4. Salve. Peça ao usuário para entrar em `http://localhost:8008` e conferir que vê só o setor dele.

### 5.2 Usuários de teste

O `seed_carmel` cria `admin`, `gestor.rh` e `colab.governanca`, com a senha padrão descrita no README. **Troque essas senhas antes de usar com pessoas reais** (Admin → Usuários → escolher o usuário → "Alterar senha"), ou apague os usuários de teste.

## 6. HeyGen (plano Creator + MCP)

### 6.1 Conta e plano

- Plano **Creator**, conta `heygen@carmelhoteis.com.br`, com 600 créditos premium por mês (renovam em 04/12/2026). Esses números vieram da ferramenta `get_current_user` do MCP, que mostra plano e créditos restantes; você também os vê em Configurações/Faturamento no site da HeyGen.
- O Creator permite resolução de até 1080p. Os testes usaram 720p em 16:9.

### 6.2 Por que não usamos a API

- A chave de API é válida (consultar vozes e avatares funciona), mas a geração de vídeo foi **recusada** com `402 insufficient_credit`: o saldo de API é separado do plano Creator.
- O endpoint que o código antigo usa (`POST /v2/video/generate`) foi marcado pela HeyGen como **legado**, com remoção prevista para 31/10/2026. Se um dia for contratado saldo de API, é preciso migrar o código para `POST /v3/videos` antes de usar.

### 6.3 Conectar o MCP da HeyGen ao Claude Code

O MCP da HeyGen autentica por login (OAuth) e consome os créditos do plano, sem API. O endereço oficial é `https://mcp.heygen.com/mcp/v1/`.

**Passo 1 — cadastrar o servidor (uma vez por computador).**
O comando é:
```
claude mcp add --transport http -s user heygen https://mcp.heygen.com/mcp/v1/
```
No Windows com a extensão do VS Code, o comando `claude` costuma **não** estar no PATH (erro "O termo 'claude' não é reconhecido"). Use o executável da extensão, trocando `<versão>` pela instalada:
```
& "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-<versão>\resources\native-binary\claude.exe" mcp add --transport http -s user heygen https://mcp.heygen.com/mcp/v1/
```
Para descobrir a versão: `dir "$env:USERPROFILE\.vscode\extensions" | findstr claude-code`. Esse caminho muda a cada atualização da extensão.

Alternativa pela interface: no painel do Claude Code, `/mcp` → **Add server** → nome `heygen`, tipo HTTP, URL acima.

Esperado: `Added HTTP MCP server heygen ... to user config`. O escopo `user` vale para todos os projetos do usuário; sem `-s user`, vale só para o projeto atual.

**Passo 2 — fazer o login.**
1. No painel do Claude Code, digite `/mcp`.
2. Escolha `heygen` (limpe a caixa de busca se a lista parecer vazia).
3. Conclua o login no navegador com a conta HeyGen do plano Creator.

**Passo 3 — recarregar.**
O Claude Code só lê os servidores quando a sessão começa. Rode **Developer: Reload Window** (`Ctrl+Shift+P`) ou abra uma conversa nova.

**Como conferir:** `claude mcp get heygen` (ou `mcp list`) deve mostrar `Connected` em vez de `Needs authentication`. Na conversa, peça ao Claude para consultar o usuário da HeyGen: ele deve responder com o plano (`creator`) e os créditos.

Para desfazer ou recomeçar: `claude mcp remove heygen -s user`. Se aparecer duplicado (um em escopo user e outro local), remova um deles.

### 6.4 Escolher avatar e voz

- **Avatar adotado:** `Abigail_standing_office_front` ("Abigail Office Front"), estilo escritório, feminino.
- **Voz adotada:** Lucilene, `e808da2329754929803c8bd98dc36857`, português.
- Outras vozes em português testadas na lista da HeyGen:

| Voz | ID |
|---|---|
| Lucilene (feminina, clara e confiável) | `e808da2329754929803c8bd98dc36857` |
| Afonso (masculino, caloroso) | `9ce5f601f9e04382bb26141d5a3f839d` |
| Thaís (feminina, enérgica) | `a8c7b58e38c44719b3ab36342f080e95` |
| Murilo (masculino, articulado) | `d703f08d1ef34302a36945aa3efc7b3f` |

- **Para escolher outro avatar ou voz:** peça ao Claude para listar (ferramentas `list_avatar_groups`, `list_avatar_looks` e `list_voices` do MCP; a conta tem mais de 1.200 avatares públicos e quase 3.000 vozes, 29 delas em português). Veja a pré-visualização de cada avatar antes de decidir.
- **Onde registrar a escolha:** o padrão geral fica em `DEFAULT_AVATAR_ID` e `DEFAULT_VOICE_ID` no `.env`. Para um setor ter avatar e voz próprios, preencha **Admin → Setores → Avatar HeyGen Padrão / Voz HeyGen Padrão**. Convenção adotada: ao gerar, usa-se o do setor e, se estiver vazio, o do `.env`.
- Os IDs de avatar do MCP hoje são códigos hexadecimais; o ID antigo da Abigail (`Abigail_standing_office_front`) continuou sendo aceito nos testes.

### 6.5 Gerar e registrar um vídeo (passo a passo)

Com `HEYGEN_GENERATION_MODE=manual` (padrão), depois que o gestor aprova o roteiro o item fica **Aguardando Vídeo** na fila. O vídeo é gerado fora do portal e depois registrado nele. Há dois caminhos.

**Caminho A — pelo Claude, com o MCP (o fluxo pretendido).** Numa sessão do Claude Code com o MCP conectado. A pessoa só pede "gere os vídeos aprovados"; o Claude faz os passos 1 a 5, e o gestor termina com o passo 6.

1. Veja o que está esperando:
   ```
   .venv\Scripts\python.exe manage.py list_awaiting_videos
   ```
   Mostra, para cada item, o número, o setor, o título, o avatar, a voz e o roteiro aprovado.
2. O Claude chama `create_video_from_avatar` com o avatar e a voz do setor (ou os do `.env`), o roteiro **sem alterações**, o título, formato 16:9 e resolução 720p (ou 1080p, se quiser).
3. A HeyGen devolve um `video_id` com status `waiting`. O Claude acompanha com `get_video` a cada 30 a 60 segundos. A renderização leva em média **2 min 40 s a 2 min 50 s** para vídeos curtos.
4. Quando o status for `completed`, o Claude salva o MP4 na pasta **Videos** do setor no Drive, com o link, a duração e o ID da HeyGen devolvidos:
   ```
   .venv\Scripts\python.exe manage.py upload_generated_video N --url "<link do mp4>" --heygen-id <video_id> --duration <segundos>
   ```
   O arquivo vai para o Drive com o número do item gravado nele. O item continua **Aguardando Vídeo** (a mensagem avisa que o vídeo já está no Drive).
5. O Claude confere no Drive que o arquivo chegou à pasta Videos do setor.
6. **O gestor clica em "Sincronizar Drive"** no portal (ou roda `manage.py sync_drive`). O portal carrega o vídeo, liga ao item pelo número gravado no arquivo, marca **Concluído** e o publica no catálogo, tocando a cópia do Drive.

Opcional: para a fila mostrar "HeyGen Renderizando" enquanto o vídeo é feito, registre o início com `manage.py register_video N --heygen-id <video_id>`.

**Caminho B — gerar no site da HeyGen e anexar o MP4.** Para quem não usa o Claude:

1. Na fila, o gestor clica em **Anexar vídeo** no item "Aguardando vídeo".
2. A tela mostra o roteiro aprovado (com botão **Copiar roteiro**) e o avatar e a voz a usar.
3. No site da HeyGen, gere o vídeo com esse roteiro, avatar e voz, e baixe o MP4.
4. Volte à tela, escolha o MP4 (até `MAX_VIDEO_MB`, 500 MB por padrão) e clique em **Anexar e publicar**. O arquivo é guardado em `<Setor>/Videos` no Drive e o vídeo passa a tocar no catálogo.
   - Se o setor não tiver pasta do Drive cadastrada, ou a Service Account não estiver configurada, aparece o erro "Não foi possível salvar no Drive" e o item continua aguardando.
   - O vídeo anexado não tem duração nem miniatura; o cartão no catálogo usa uma imagem padrão.

Não gere o mesmo item duas vezes para "verificar": a consulta é sempre por `get_video`, nunca por uma nova criação. Se a consulta falhar com erro de rede (`ECONNRESET`), repita só a consulta.

**Modo API.** Com `HEYGEN_GENERATION_MODE=api`, o portal chama a API da HeyGen sozinho depois da aprovação, sem a etapa "Aguardando Vídeo". Só use se contratar saldo de API (seção 6.2).

### 6.6 Custos, tempos e limites

- Custo medido (créditos do plano Creator, 720p, tempo de renderização de cerca de 3 minutos em todos):

| Vídeo | Duração | Créditos |
|---|---|---|
| Primeiro teste | 3,84 s | 3 |
| Fluxo completo com Google Doc | 5,8 s | 4 |
| "Teste2" (fluxo pretendido via MCP) | 3,21 s | 3 |

  São só três pontos, todos de vídeos muito curtos. Eles sugerem algo perto de 0,7 crédito por segundo, ou seja, 600 créditos dariam em torno de 13 minutos de vídeo por mês, mas isso é uma estimativa; confirme com um roteiro de 1 minuto ou mais antes de planejar o volume.
- Roteiro: no máximo **5.000 caracteres**.
- O link do MP4 que a HeyGen devolve **expira em cerca de 7 dias**. Por isso o sistema guarda uma cópia no Drive e toca o vídeo por lá.

### 6.7 Integração Google Drive dentro da HeyGen

A conexão do Drive nas integrações do site da HeyGen serve para importar arquivos para dentro dela. É independente do portal e não participa deste fluxo.

## 7. Google Drive (Service Account e pastas)

### 7.1 Visão do que será criado

```
Conta Google Workspace
└── Unidade Compartilhada "Drive"
    ├── RH
    │   ├── Roteiros     ← a equipe coloca os roteiros aqui
    │   └── Videos       ← o sistema grava os vídeos aqui
    ├── Recepção          (mesma estrutura)
    └── ... um por setor
```

E uma **Service Account** (uma "conta robô") que o portal usa para ler e gravar nessas pastas.

### 7.2 Google Cloud: projeto e API

1. Entre em `https://console.cloud.google.com` com a conta corporativa.
2. No seletor de projetos (topo), escolha o projeto existente (`carmel-projetos`) ou crie um novo.
3. Abra **APIs e serviços → Biblioteca**, busque **Google Drive API** e clique em **Ativar**.

Esperado: a página da API mostra "API ativada".

### 7.3 Criar a Service Account

1. Abra **IAM e administrador → Contas de serviço** (ou algo equivalente).
2. Clique em **Criar conta de serviço**, dê um nome (a atual é `heygen`) e conclua. Não é preciso atribuir papéis do projeto: o acesso aos arquivos vem do compartilhamento no Drive (seção 7.5).
3. Anote o e-mail dela, no formato `nome@projeto.iam.gserviceaccount.com` (o atual é `heygen@carmel-projetos.iam.gserviceaccount.com`).

### 7.4 Gerar a chave JSON

1. Abra a Service Account e vá na aba **Chaves**.
2. Clique em **Adicionar chave → Criar nova chave → JSON**. O navegador baixa um arquivo `.json`.
3. Mova o arquivo para `data\service_account.json` dentro do projeto.
4. Apague a cópia da pasta Downloads. Nunca envie esse arquivo por e-mail ou chat.

Se a organização bloquear a criação de chaves por política de segurança, peça ao administrador do Google Workspace para liberar uma exceção para esse projeto.

**Como conferir:** `dir data\service_account.json` mostra o arquivo, e o portal o reconhece (ver 7.9).

### 7.5 Criar a Unidade Compartilhada e dar acesso à Service Account

**Esta etapa é obrigatória.** Uma Service Account não tem espaço próprio no "Meu Drive", e gravar vídeos lá falha com `storageQuotaExceeded`. Só em Unidade Compartilhada funciona.

1. No Google Drive, abra **Unidades compartilhadas → Nova** e crie a unidade (a atual se chama "Drive").
2. Dentro dela, abra **Gerenciar membros** (ou equivalente) e adicione o **e-mail da Service Account** com o papel **Gerente de conteúdo** (Content manager).
3. Adicione também as pessoas da equipe que vão colocar roteiros e ver os vídeos, com o papel que fizer sentido para o time.

### 7.6 Criar a estrutura de pastas

1. Dentro da Unidade Compartilhada, crie **uma pasta por setor**, com o nome do setor (por exemplo, `RH`).
2. Dentro de cada pasta de setor, crie duas subpastas: `Roteiros` e `Videos` (ou `Vídeos`; o sistema aceita as duas, sem diferenciar acento ou maiúsculas).
3. Se você pular este passo, o sistema cria as subpastas que faltarem na primeira varredura.

### 7.7 Pegar o ID da pasta do setor

1. No Drive, abra a **pasta do setor** (por exemplo, `RH`), não a raiz da unidade.
2. Veja o endereço no navegador: `https://drive.google.com/drive/folders/<ID>`.
3. Copie só a parte `<ID>`.

**Cuidado:** o ID da raiz da Unidade Compartilhada costuma começar com `0A`. Se você usar o ID da raiz, o sistema procura Roteiros e Videos na raiz, não encontra e **cria um par novo de pastas lá**. Já aconteceu nos testes; use sempre o ID da pasta do setor.

### 7.8 Cadastrar o ID no portal

1. Entre no Admin: `http://localhost:8008/admin`.
2. Abra **Setores / Departamentos** e escolha o setor.
3. Cole o ID em **ID da Pasta do Setor no Google Drive** e salve.
4. Repita para cada setor.

### 7.9 Conferir a configuração

Com o servidor parado ou em outro terminal, abra o shell do Django:
```
.venv\Scripts\python.exe manage.py shell
```
e cole, linha a linha:
```python
from treinamentos.models import Department
from treinamentos.services.drive_service import GoogleDriveService as G
c = G.get_drive_client()                      # None = arquivo da Service Account não encontrado
d = Department.objects.get(code="rh")
print(c.files().get(fileId=d.drive_folder_id, fields="name,driveId", supportsAllDrives=True).execute())
```
Esperado: um dicionário com o nome da pasta (`RH`) e um `driveId`. Se o `driveId` não aparecer, a pasta não está em uma Unidade Compartilhada. Para sair do shell: `exit()`.

### 7.10 Primeira varredura

1. Coloque um roteiro de teste (por exemplo, um Google Doc com uma ou duas frases) na subpasta **Roteiros** do setor.
2. No portal, entre como gestor ou admin e clique em **Sincronizar Drive** (ou rode `manage.py sync_drive` uma vez).
3. Esperado: `1 novo(s) roteiro(s) encontrado(s)` e o item aparece na **Fila** como "Na Fila", depois "Aguardando Revisão".

Regras da sincronização (botão **Sincronizar Drive** ou `sync_drive`), que lê as duas subpastas de cada setor:
- **Roteiros:** importa cada arquivo **uma vez**. Editar um roteiro já importado não gera outro vídeo. Aceita Google Docs (exportado como .docx), DOCX, PDF, TXT e MD; outros formatos são ignorados.
- **Vídeos:** publica no catálogo cada **MP4 novo**.
  - Se o arquivo corresponde a um item que está **aguardando o vídeo**, esse item é concluído. A ligação é feita pelo número do item gravado no próprio arquivo (é o que o comando `upload_generated_video` faz) ou, na falta dele, pelo **nome do arquivo igual ao título** do item (ex.: `Manual de Integração.mp4`).
  - Se não corresponde a nenhum item, o vídeo é **importado como um item novo** do catálogo, com o nome do arquivo como título.
  - Arquivos que não são MP4 são ignorados, e um MP4 já publicado não é importado de novo.
- Depois de sincronizar, o botão leva ao **catálogo** se houve vídeos publicados, ou à **fila** se houve roteiros novos.

### 7.11 Reprodução pelo portal

O portal entrega o MP4 ao colaborador por `/video/<id>/arquivo/`: busca o arquivo no Drive com a Service Account, exige login, respeita o setor e aceita avançar e voltar no vídeo. Se o Drive falhar, usa o link da HeyGen enquanto ele valer.

### 7.12 Lixeira do Drive

A Service Account só consegue mandar arquivos para a **lixeira**, não apagar de vez. Para limpar de verdade, esvazie a lixeira da Unidade Compartilhada com uma conta de pessoa.

## 8. Operação no dia a dia

1. O responsável coloca o roteiro em `<Setor>/Roteiros` (ou o gestor usa **Enviar documento** no portal).
2. A varredura importa o arquivo e ele aparece na **Fila** como "Na Fila".
3. O sistema extrai o texto e remove markdown, marcadores e numeração no início das linhas ("1.", "3.2", "a)"). O item passa a **Aguardando Revisão**.
4. O gestor abre **Fila → Revisar roteiro**, ajusta o texto (contador de até 5.000 caracteres) e clica em **Aprovar e gerar vídeo**. Acima de 5.000 caracteres a aprovação é bloqueada.
5. Aprovado o roteiro, o item fica **Aguardando Vídeo**.
6. O Claude gera o vídeo pelo MCP e salva o MP4 em `<Setor>/Videos` no Drive (seção 6.5).
7. O gestor clica em **Sincronizar Drive**: o portal carrega o vídeo, liga ao item e o marca **Concluído**.
8. O colaborador assiste no catálogo; ao terminar o vídeo, a conclusão é registrada.

Comandos úteis (use o prefixo `.venv\Scripts\python.exe`):

| Comando | O que faz |
|---|---|
| `manage.py sync_drive` | Varre uma vez as pastas Roteiros (importa roteiros) e Vídeos (publica vídeos) |
| `manage.py sync_drive --watch` | Varre continuamente a cada `DRIVE_SYNC_INTERVAL_MINUTES` |
| `manage.py upload_generated_video N --url LINK --heygen-id ID --duration S` | Salva na pasta Vídeos do Drive um vídeo já gerado; ele só entra no catálogo na próxima sincronização |
| `manage.py list_awaiting_videos` | Lista os roteiros aprovados que aguardam o vídeo, com avatar, voz e roteiro |
| `manage.py register_video N --heygen-id ID [--url LINK --duration S]` | Alternativa direta, sem passar pelo Drive: só com `--heygen-id` marca "Renderizando"; com `--url` conclui e publica na hora |
| `manage.py poll_heygen` | Atualiza vídeos em renderização e repete cópias ao Drive que falharam |
| `manage.py seed_carmel` | Recria setores e usuários de teste que faltarem |
| `manage.py test treinamentos` | Roda os testes automáticos |

## 9. Solução de problemas

Estes são os problemas que realmente apareceram durante a configuração.

| Sintoma | Causa | O que fazer |
|---|---|---|
| `O termo 'claude' não é reconhecido` no PowerShell | O Claude Code da extensão não está no PATH | Use o executável da extensão (seção 6.3) |
| MCP não aparece em `/mcp` (`No matching servers`) | A sessão começou antes do cadastro, ou há filtro na busca | Recarregue o VS Code, limpe a busca de `/mcp` |
| MCP aparece como `Needs authentication` | Falta o login no navegador | `/mcp` → `heygen` → concluir o login |
| `402 insufficient_credit` na API da HeyGen | O saldo de API é separado do plano Creator | Gere pelo MCP (seção 6) |
| A lista de avatares da API demora ou dá `ReadTimeout` | São 1.249 avatares; a resposta leva ~35 s | Aumente o tempo limite para pelo menos 60 s |
| `ECONNRESET` ao consultar o vídeo no MCP | Queda pontual de conexão | Repita **só a consulta** (`get_video`), nunca a criação |
| `storageQuotaExceeded` ao enviar o vídeo | A pasta está no "Meu Drive" | Use uma Unidade Compartilhada com a Service Account como membro |
| Apareceram pastas Roteiros/Videos novas na raiz da unidade | O ID cadastrado no setor é o da raiz | Cadastre o ID da pasta do setor (seção 7.7) |
| `404`/`File not found` ao ler uma pasta | ID errado ou a Service Account não é membro | Confira o ID e o acesso (seção 7.5) |
| A varredura não importa nada | Arquivo fora de **Roteiros**, formato não aceito, ou já importado antes | Confira a pasta, o formato e a fila |
| Aviso de "Roteiro com N caracteres; o limite é 5000" | Roteiro grande demais | Reduza o texto ou divida em partes |
| O vídeo não abre depois de alguns dias | O link da HeyGen expirou e não há cópia no Drive | Rode `poll_heygen` ou gere de novo; confirme que o setor tem pasta no Drive |
| `PermissionError` ao limpar um arquivo temporário (Windows) | Bug do envio, **já corrigido** | Atualize o código; envio agora fecha o arquivo |
| Item parado em "Aguardando vídeo" | O vídeo ainda não foi gerado, ou foi salvo no Drive mas ninguém sincronizou | `list_awaiting_videos`; gere (seção 6.5); clique em **Sincronizar Drive** |
| Sincronizei e o vídeo não apareceu | O arquivo não está na pasta **Vídeos** do setor, não é MP4, ou o ID da pasta do setor está errado | Confira a pasta no Drive, o formato e o ID cadastrado (seção 7.7) |
| O vídeo entrou como item novo em vez de concluir o item que esperava | O arquivo não tem o número do item e o nome é diferente do título | Renomeie o arquivo igual ao título do item, ou gere pelo comando `upload_generated_video` |
| "Não foi possível salvar no Drive" ao anexar o vídeo | Setor sem pasta cadastrada, Service Account ausente, ou sem acesso | Confira as seções 7.5 a 7.9; o item continua aguardando e você pode tentar de novo |
| `register_video` recusa o item | O vídeo já está concluído ou não está aguardando | Veja o status na fila; só aceita "Aguardando Vídeo" ou "HeyGen Renderizando" |
| `DisallowedHost` ao acessar o portal | O endereço não está em `DJANGO_ALLOWED_HOSTS` | Adicione no `.env` e reinicie |

## 10. Testes realizados

| Data | Teste | Resultado |
|---|---|---|
| 04/11/2026 | API da HeyGen: listar vozes e avatares | OK (chave válida) |
| 04/11/2026 | API da HeyGen: gerar vídeo | Recusado, `402 insufficient_credit` |
| 05/11/2026 | MCP da HeyGen: vídeo de teste (3,84 s) | Concluído em ~2 min 43 s, 3 créditos |
| 05/11/2026 | Drive: autenticação e pasta em Unidade Compartilhada | OK |
| 05/11/2026 | Drive: roteiro de teste em Roteiros e varredura | 1 item novo, sem duplicar na 2ª varredura |
| 05/11/2026 | Drive: envio do MP4 para Videos e leitura pelo portal | OK, com e sem Range (206 e 200); sem login redireciona (302) |
| 05/11/2026 | Fluxo completo com um Google Doc | Doc de 87 caracteres → revisão → vídeo de 5,8 s → `Teste.mp4` em RH/Videos → catálogo |
| 05/11/2026 | Fluxo pretendido com o Drive real: `upload_generated_video` salva o MP4 em Videos → clique em Sincronizar → o portal liga ao item, conclui e publica | Item concluído com a duração, vídeo no catálogo, reprodução 206; segunda sincronização sem duplicar |
| 05/11/2026 | Estado "Aguardando Vídeo": anexo de MP4 pela tela do portal, com o Drive real | Tela mostrou o roteiro; MP4 salvo em RH/Videos com o mesmo tamanho; reprodução pelo portal 206; arquivos de teste removidos |

Bug encontrado e corrigido durante o teste do Drive: no Windows, o arquivo temporário do vídeo ficava aberto e a limpeza falhava logo após o envio. O envio agora fecha o arquivo.

Não foi avaliada, por nós, a qualidade visual dos vídeos de teste (voz em português e sincronia da boca).

## 11. Pendências e riscos

- **A geração do vídeo ainda não é totalmente automática.** O portal já espera pelo vídeo ("Aguardando Vídeo") e recebe o resultado (`register_video` ou "Anexar vídeo"), mas quem aciona a HeyGen é uma pessoa ou o Claude em uma sessão com o MCP, que só roda quando alguém pede. O portal não consegue chamar o MCP sozinho. Depois que o vídeo está no Drive, a publicação no catálogo é automática na sincronização. Automatizar o site da HeyGen com robô de navegador não é recomendado: provável violação dos termos de uso, risco de suspensão da conta e fragilidade a cada mudança no site.
- **Cinco setores sem pasta no Drive.** Só o RH está cadastrado; Recepção, Governança, Alimentos & Bebidas, Experiências e Manutenção precisam da pasta e do ID (seções 7.6 a 7.8).
- **Itens de teste ainda existentes:** o vídeo "Teste" está publicado no catálogo do RH, e há `Roteiros/Teste` e `Videos/Teste.mp4` no Drive. Para remover, apague no Admin **e** no Drive; se apagar só no banco, a próxima varredura importa o roteiro de novo.
- **Lixeira do Drive:** há dois `TESTE_Carmel_Video.mp4` lá; esvazie manualmente (seção 7.12).
- **Custo em créditos** medido só com vídeos de 3 a 6 segundos; falta um roteiro de 1 minuto ou mais para confirmar a proporção.
- **Vídeos soltos na pasta Vídeos viram itens do catálogo.** Qualquer MP4 novo que alguém coloque em `<Setor>/Vídeos` é publicado na próxima sincronização, mesmo sem roteiro. Se isso não for desejado, é preciso restringir a pasta no Drive ou mudar o comportamento.
- **Chave de API da HeyGen** está no `.env` sem uso no fluxo atual; avalie remover ou trocar.
- **`HEYGEN_MOCK_MODE=true`** continua no `.env`; só afeta o caminho antigo por API.
- **Produção:** `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY`, HTTPS, servidor com vários processos e senhas de teste trocadas.

## 12. Checklist de implantação

Marque conforme concluir.

**Portal**
- [ ] `.venv` criado e dependências instaladas
- [ ] `.env` preenchido (seção 4)
- [ ] `manage.py check` sem erros e `migrate` aplicado
- [ ] `seed_carmel` rodado e senhas de teste trocadas
- [ ] Usuários reais criados com setor e nível de acesso (seção 5.1)

**HeyGen**
- [ ] Conta no plano Creator e créditos conferidos
- [ ] MCP cadastrado, login feito e `Connected` (seção 6.3)
- [ ] Avatar e voz escolhidos e registrados no `.env` ou no setor
- [ ] Um vídeo curto de teste gerado e assistido (voz e boca conferidas)

**Google Drive**
- [ ] Google Drive API ativada no projeto
- [ ] Service Account criada e chave JSON em `data/service_account.json`
- [ ] Unidade Compartilhada criada, com a Service Account como Gerente de conteúdo
- [ ] Pasta de cada setor criada, com `Roteiros` e `Videos`
- [ ] ID da **pasta do setor** (não da raiz) cadastrado no Admin para cada setor
- [ ] Verificação da seção 7.9 sem erros
- [ ] Primeira varredura com um roteiro de teste, item na fila

**Fluxo de ponta a ponta**
- [ ] Roteiro revisado e aprovado no portal
- [ ] Item aparece como "Aguardando Vídeo" depois da aprovação
- [ ] Vídeo gerado (MCP ou site) e registrado (`register_video`) ou anexado, e o item fica Concluído
- [ ] MP4 apareceu em `<Setor>/Videos` no Drive
- [ ] Colaborador do setor assiste no catálogo; colaborador de outro setor não vê
- [ ] Itens de teste removidos do portal e do Drive
