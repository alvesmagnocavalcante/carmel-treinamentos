# 🌿 Carmel Treinamentos (Django + HeyGen + Google Drive)

Plataforma interna para transformar documentos de treinamento (PDF, DOCX, TXT) em **vídeos apresentados por avatares digitais da HeyGen**, com acesso controlado por setor e perfil.

O **Google Drive** é o repositório central (uma conta unificada), com uma pasta por setor e duas subpastas:

```
<Setor>/
  Roteiros/   ← roteiros que alimentam a geração (a equipe coloca aqui)
  Vídeos/     ← vídeos gerados (o sistema salva aqui automaticamente)
```

Roteiros colocados em **Roteiros** (ou enviados manualmente pelo portal) passam por:

1. **Leitura** — extração do texto (`pypdf` / `python-docx`). O texto do documento **é** o roteiro: o responsável entrega o documento já escrito para ser falado, e o avatar narra exatamente o que está escrito. Marcações de lista, markdown e numeração no início das linhas ("1.", "3.2", "a)") são removidas e o limite é de 5.000 caracteres (acima disso não é possível aprovar: reduza o texto).
2. **Revisão** — o gestor lê o roteiro na tela *Fila → Revisar roteiro*, corrige se necessário e aprova. Só então o vídeo é pedido à HeyGen (evita gastar crédito com texto errado). Desative com `REQUIRE_SCRIPT_REVIEW=false` para envio automático.
3. **Vídeo** — no modo `manual` (padrão, plano Creator sem API), o item fica **Aguardando Vídeo**. O Claude gera o vídeo na HeyGen pelo MCP e o salva na subpasta **Vídeos** do setor no Drive (`manage.py upload_generated_video`). Ao clicar em **Sincronizar Drive**, o portal carrega o vídeo, liga ao roteiro certo e o publica no catálogo. Também é possível gerar no site da HeyGen e anexar o MP4 pela tela *Anexar vídeo*. No modo `api` (`HEYGEN_GENERATION_MODE=api`), o portal chama a API da HeyGen sozinho. Para o Claude operar isso pela web, o portal expõe um **conector MCP** (`/mcp/<chave>/`, ligado por `MCP_TOKEN`) com quatro ferramentas — ver `docs/CONFIGURACAO.md`, seção 13.
4. **Drive** — o MP4 pronto é copiado para a subpasta **Vídeos** do setor (o ID do arquivo fica registrado no vídeo, no Admin). Se o Drive falhar, o vídeo continua disponível no portal e o `poll_heygen` tenta salvar de novo.
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

> Passo a passo completo de configuração (HeyGen, Google Drive, Service Account, testes realizados e pendências): [docs/CONFIGURACAO.md](docs/CONFIGURACAO.md).

---

## 👥 Perfis (RBAC)

| Usuário | Senha | Perfil | Pode |
| :--- | :--- | :--- | :--- |
| `admin` | `carmel2026` | Administrador geral | Ver e gerenciar todos os setores, Django Admin, chaves de API. |
| `gestor.rh` | `carmel2026` | Gestor (RH) | Ver/enviar documentos **somente do RH**, sincronizar o Drive do RH, reprocessar falhas. |
| `colab.governanca` | `carmel2026` | Colaborador (Governança) | Assistir **somente** os treinamentos da Governança. |

Regras:
- Colaborador sem setor definido não vê nenhum treinamento.
- Gestor sem setor definido não pode enviar documentos.
- O perfil e o setor de cada usuário são definidos em **Admin → Usuários → Perfil de Acesso & Setor**.

> ⚠️ Troque as senhas de teste antes de usar com pessoas reais.

---

## ⚙️ Configuração

Tudo fica no `.env` (veja `.env.example`). Os pontos principais:

| Variável | Para quê |
| :--- | :--- |
| `HEYGEN_API_KEY` | Chave da HeyGen. |
| `MCP_TOKEN` | Chave do conector MCP do portal para o Claude. Vazio = desligado. |
| `HEYGEN_GENERATION_MODE` | `manual` (padrão): o vídeo é gerado fora do portal e registrado/anexado. `api`: o portal chama a API da HeyGen. |
| `REQUIRE_SCRIPT_REVIEW` | `true` (padrão): o gestor aprova o roteiro antes de gerar o vídeo. `false`: envio automático. |
| `DEFAULT_AVATAR_ID` / `DEFAULT_VOICE_ID` | Avatar e voz padrão. Cada setor pode ter os seus em **Admin → Setores**. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | JSON da Service Account. Ela precisa de permissão de **Editor/Gerente de conteúdo** nas pastas dos setores (lê Roteiros e grava em Vídeos). |
| `DJANGO_DEBUG` / `DJANGO_SECRET_KEY` / `DJANGO_ALLOWED_HOSTS` | Segurança do Django. |

Valores em **Admin → Configurações do Sistema** têm prioridade sobre o `.env`; deixar o valor vazio faz o sistema usar o `.env`.

### Pastas por setor
- **Google Drive:** cadastre o ID da **pasta do setor** em **Admin → Setores → ID da Pasta do Setor no Google Drive**. As subpastas `Roteiros` e `Vídeos` são criadas automaticamente se não existirem (o nome tolera maiúsculas e acento). Google Docs nativos são exportados como `.docx`.
- **Importante — Service Account e armazenamento:** uma Service Account **não tem cota de armazenamento** no "Meu Drive"; gravar vídeos ali falha com `storageQuotaExceeded`. Use uma **Unidade Compartilhada** (Shared Drive) da conta unificada, adicionando o e-mail da Service Account como membro com permissão de gerenciar conteúdo.

---

## 🛠️ Comandos

```powershell
uv run python manage.py sync_drive            # varre as pastas uma vez e processa os novos documentos
uv run python manage.py sync_drive --watch    # varredura contínua a cada DRIVE_SYNC_INTERVAL_MINUTES
uv run python manage.py poll_heygen           # atualiza vídeos que ficaram "Renderizando" (ex.: após reiniciar o servidor)
uv run python manage.py seed_carmel           # (idempotente) recria setores/usuários de teste que estiverem faltando
uv run python manage.py test treinamentos     # testes automatizados
```

---

## 📁 Estrutura

```
carmel_project/        settings e URLs do Django
treinamentos/
  models.py            Department, UserProfile, TrainingVideo, VideoProgress, SystemSetting
  views.py             catálogo, fila, upload, sync, reprocessar, login/logout
  context_processors   perfil e permissões disponíveis em todos os templates
  services/
    pipeline.py        orquestra leitura/roteiro → HeyGen (em thread de background)
    drive_service.py   Google Drive + pastas locais
    heygen_service.py  API HeyGen (+ modo simulação)
    document_parser.py PDF, DOCX, TXT + limpeza do roteiro
    storage.py         nomes de arquivo seguros
templates/             portal (Tailwind) e tema do Django Admin
data/                  banco SQLite, documentos baixados, pastas locais de teste
```

### Limitações conhecidas
- O pipeline roda em threads do próprio processo Django. Serve para uso interno; para volume maior, troque por uma fila (Celery/RQ).
- Se o servidor reiniciar durante uma renderização, rode `poll_heygen` (ou clique em **Reprocessar** se o job ficou em "Na Fila").
