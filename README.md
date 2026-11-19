# 🌿 Carmel Treinamentos (Django + HeyGen + Google Drive)

Plataforma interna para transformar documentos de treinamento (PDF, DOCX, TXT) em **vídeos apresentados por avatares digitais da HeyGen**, com acesso controlado por setor e perfil.

O **Google Drive** é o repositório central (uma conta unificada), com uma pasta por setor e três subpastas:

```
<Setor>/
  Roteiros/   ← roteiros que alimentam a geração (a equipe coloca aqui)
  Imagens/    ← imagens de fundo das cenas (png, jpg ou webp), citadas pelo nome no roteiro
  Vídeos/     ← vídeos gerados (o sistema salva aqui automaticamente)
```

Roteiros colocados na subpasta **Roteiros** passam por:

1. **Leitura** — extração do texto (`pypdf` / `python-docx`). O texto do documento **é** o roteiro: o responsável entrega o documento já escrito para ser falado, e o avatar narra exatamente o que está escrito. Marcações de lista, markdown e numeração no início das linhas ("1.", "3.2", "a)") são removidas e o limite é de 5.000 caracteres (acima disso não é possível aprovar: reduza o texto).
   **Imagens no vídeo (opcional).** Uma linha sozinha `[IMAGEM: piscina.png]` no roteiro abre uma **cena** que mostra essa imagem em tela cheia, com a voz narrando o texto (arquivo da subpasta **Imagens** do setor). **Nas cenas com imagem o avatar não aparece**; nas cenas sem imagem, sim. Tudo até a próxima marcação é o texto falado daquela cena. O texto antes da primeira marcação é a cena 1, sem imagem. A marcação **não é narrada** e não conta para o limite de 5.000 caracteres. Sem nenhuma marcação, nada muda: é uma cena só, com o fundo de sempre.

   ```
   Bem-vindo ao nosso resort.          ← cena 1, sem imagem

   [IMAGEM: piscina.png]
   Esta é a piscina principal...       ← cena 2, fundo piscina.png

   [IMAGEM: restaurante.jpg]
   Agora, o restaurante...             ← cena 3, fundo restaurante.jpg
   ```

   O nome do arquivo não diferencia maiúsculas nem acentos. Aceita png, jpg e webp, até `MAX_IMAGE_MB` (10 MB por padrão).

   **Imagem animada (opcional).** `[IMAGEM: piscina.png | animar]` (ou `| animar: aproximação lenta da câmera`) faz a HeyGen animar a imagem com IA, com a voz por cima e sem o avatar. Cada cena animada **gasta crédito extra** e leva alguns minutos; o máximo por vídeo é `MAX_ANIMATED_SCENES` (4). O padrão é só um movimento lento de câmera, em clipes curtos, para a IA inventar menos; ainda assim ela pode alterar a imagem (principalmente com mãos, comida e pessoas), então anime só o que precisa e confira o vídeo. Detalhes em [docs/CONFIGURACAO.md](docs/CONFIGURACAO.md).
2. **Revisão** — o gestor lê o roteiro na tela *Fila → Revisar roteiro*, que mostra **uma caixa por cena** (texto e imagem), corrige se necessário e aprova. Imagem citada que não existe na pasta Imagens, que passa do tamanho ou que não é png/jpg/webp aparece em vermelho e **bloqueia a aprovação** até ser corrigida (ou tirada da cena). Depois de colocar uma imagem no Drive, clique em **Sincronizar Drive**. Só então o vídeo é pedido à HeyGen (evita gastar crédito com texto errado). Desative com `REQUIRE_SCRIPT_REVIEW=false` para envio automático.
3. **Vídeo** — o item fica **Aguardando Vídeo**. O Claude gera o vídeo na HeyGen pelo MCP e o portal o salva na subpasta **Vídeos** do setor no Drive; ao clicar em **Sincronizar Drive**, o portal também carrega vídeos colocados ali, liga ao roteiro certo e os publica no catálogo. Também é possível gerar no site da HeyGen e anexar o MP4 pela tela *Anexar vídeo*. Para o Claude operar isso pela web, o portal expõe um **conector MCP** (`/mcp/<chave>/`, ligado por `MCP_TOKEN`) com quatro ferramentas.
4. **Drive** — o MP4 pronto é copiado para a subpasta **Vídeos** do setor (o ID do arquivo fica registrado no vídeo, no Admin). Se o Drive falhar, o vídeo continua disponível no portal.
5. **Portal** — o vídeo aparece no catálogo do setor e **toca a cópia guardada no Drive** (o portal busca o arquivo com a Service Account e o entrega ao colaborador logado, respeitando o acesso por setor e permitindo avançar/voltar). Enquanto não houver cópia no Drive, toca pelo link da HeyGen, que é temporário; o sistema registra quem assistiu e quem concluiu (assistiu até o fim).

---

## 🚀 Como executar

```powershell
copy .env.example .env          # e preencha as chaves
uv pip install -r requirements.txt
uv run python manage.py migrate
uv run python manage.py seed_carmel   # setores, e usuários de teste
uv run python manage.py runserver 8008
```

- Portal: **http://localhost:8008**
- Administração: **http://localhost:8008/admin**

> Para acessar por outro computador da rede, adicione o IP da máquina em `DJANGO_ALLOWED_HOSTS` e rode `runserver 0.0.0.0:8008`.

> Passo a passo completo de configuração (instalação, Google Drive, HeyGen, Render e conector do Claude): [docs/CONFIGURACAO.md](docs/CONFIGURACAO.md).

---

## 👥 Perfis (RBAC)

| Usuário | Senha | Perfil | Pode |
| :--- | :--- | :--- | :--- |
| `admin` | `carmel2026` | Administrador geral | Ver e gerenciar todos os setores e o Django Admin. |
| `gestor.rh` | `carmel2026` | Gestor (RH) | Ver e gerenciar **somente o RH**: sincronizar o Drive, revisar roteiros, anexar vídeos e reprocessar falhas. |
| `colab.governanca` | `carmel2026` | Colaborador (Governança) | Assistir **somente** os treinamentos da Governança. |

**Primeiro acesso (cadastro pela própria pessoa).** Na tela de login, *Primeiro acesso? Criar cadastro*. **Passo 1:** a pessoa informa o **CPF e a data de nascimento** e o portal confere na **Humand** (só consulta, nunca altera nada lá; o nascimento garante que só o próprio colaborador veja os dados). Precisa existir, estar ativo e a data conferir. **Passo 2:** o portal mostra só o essencial vindo da Humand (nome, função quando houver, setor e resort); a pessoa confere e **cria uma senha**. O acesso é liberado na hora, como Colaborador, e **o login passa a ser o CPF** (com ou sem pontos). Setor e resort: nomes iguais aos do portal (sem diferenciar acento) ligam sozinhos; os diferentes (ex.: *CM* → Magna/CM) ficam em **Admin → Correspondências Humand**. Setor não reconhecido: a pessoa entra sem setor e o administrador completa. O CPF não é guardado em separado, só uma impressão digital dele (impede duas contas para a mesma pessoa). Após 5 tentativas erradas (por IP ou CPF) há bloqueio de 15 minutos. Variáveis: `HUMAND_API_KEY` (sem ela o cadastro fica desligado), `HUMAND_BASE_URL`, `SIGNUP_ENABLED`, `SIGNUP_MAX_ATTEMPTS`, `SIGNUP_LOCK_MINUTES`.

Regras:
- Colaborador sem setor definido não vê nenhum treinamento.
- Gestor sem setor definido não gerencia nada.
- O perfil e o setor de cada usuário são definidos em **Admin → Usuários → Perfil de Acesso & Setor**.

> ⚠️ Troque as senhas de teste antes de usar com pessoas reais.

---

## ⚙️ Configuração

Tudo fica no `.env` (veja `.env.example`). Os pontos principais:

| Variável | Para quê |
| :--- | :--- |
| `MCP_TOKEN` | Chave do conector MCP do portal para o Claude. Vazio = desligado. |
| `MAX_IMAGE_MB` | Tamanho máximo de cada imagem da pasta Imagens (padrão 10). Acima disso a imagem não é usada. |
| `IMAGE_URL_TTL_MINUTES` | Validade, em minutos, do link temporário que o portal dá à HeyGen para baixar a imagem de uma cena (padrão 120). |
| `MAX_ANIMATED_SCENES` | Máximo de cenas com imagem animada por IA em um vídeo (padrão 4). Cada uma gasta crédito extra da HeyGen. |
| `PORTAL_BASE_URL` | Endereço público do portal (`https://...`) usado nesses links. Vazio = usa o endereço da própria requisição do conector. |
| `REQUIRE_SCRIPT_REVIEW` | `true` (padrão): o gestor aprova o roteiro antes de gerar o vídeo. `false`: envio automático. |
| `DEFAULT_AVATAR_ID` / `DEFAULT_VOICE_ID` | Avatar e voz padrão. Cada setor pode ter os seus em **Admin → Setores**. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | JSON da Service Account. Ela precisa de permissão de **Editor/Gerente de conteúdo** nas pastas dos setores (lê Roteiros e grava em Vídeos). |
| `DJANGO_DEBUG` / `DJANGO_SECRET_KEY` / `DJANGO_ALLOWED_HOSTS` | Segurança do Django. |

### Pastas por setor
- **Google Drive:** cadastre o ID da **pasta do setor** em **Admin → Setores → ID da Pasta do Setor no Google Drive**. As subpastas `Roteiros`, `Imagens` e `Vídeos` são criadas automaticamente se não existirem (o nome tolera maiúsculas e acento). Google Docs nativos são exportados como `.docx`.
- **Importante — Service Account e armazenamento:** uma Service Account **não tem cota de armazenamento** no "Meu Drive"; gravar vídeos ali falha com `storageQuotaExceeded`. Use uma **Unidade Compartilhada** (Shared Drive) da conta unificada, adicionando o e-mail da Service Account como membro com permissão de gerenciar conteúdo.

---

## 🛠️ Comandos

```powershell
uv run python manage.py sync_drive            # varre as pastas uma vez e processa os novos documentos
uv run python manage.py sync_drive --watch    # varredura contínua a cada DRIVE_SYNC_INTERVAL_MINUTES
uv run python manage.py seed_carmel           # (idempotente) recria setores/usuários de teste que estiverem faltando
uv run python manage.py test treinamentos     # testes automatizados
```

---

## 📁 Estrutura

```
carmel_project/        settings e URLs do Django
treinamentos/
  models.py            Department, UserProfile, TrainingVideo, VideoProgress, SystemSetting
  views.py             catálogo, fila, revisão do roteiro, anexo de vídeo, player, sync, login
  mcp_server.py        conector MCP do portal (ferramentas usadas pelo Claude)
  admin.py             Django Admin (listas e formulários)
  admin_site.py        painel inicial e menu do Admin
  context_processors   perfil e permissões disponíveis em todos os templates
  services/
    pipeline.py        leitura do documento, roteiro e registro do vídeo
    drive_service.py   Google Drive (roteiros, vídeos, reprodução)
    document_parser.py PDF, DOCX, TXT + limpeza do roteiro
    storage.py         nomes de arquivo seguros
  management/commands/ sync_drive, seed_carmel
  tests/               testes por assunto (acesso, pipeline, drive, streaming, mcp)
templates/             portal e tema do Django Admin
static/                CSS, JavaScript, fontes e imagens da marca (css/, js/, fonts/, img/)
docs/CONFIGURACAO.md   manual de configuração passo a passo
data/                  banco SQLite, documentos baixados e Service Account (fora do Git)
```

### Limitações conhecidas
- O pipeline roda em threads do próprio processo Django. Serve para uso interno; para volume maior, troque por uma fila (Celery/RQ).
- Se o servidor reiniciar durante a leitura de um documento, clique em **Reprocessar** se o item ficou em "Na Fila".
