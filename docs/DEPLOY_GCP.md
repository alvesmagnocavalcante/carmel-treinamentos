# Deploy no Google Cloud Run

Pré-requisitos: projeto GCP com faturamento ativo e o `gcloud` instalado (`gcloud auth login`).
Troque `SEU_PROJETO` pelo ID do projeto. Região recomendada: `southamerica-east1` (São Paulo).

## 1. Habilitar as APIs

```
gcloud config set project SEU_PROJETO
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

## 2. Criar os segredos

Gere uma chave do Django e guarde os segredos (nunca no repositório):

```
python -c "import secrets; print(secrets.token_urlsafe(64))" | gcloud secrets create django-secret-key --data-file=-
gcloud secrets create database-url --data-file=-        # cole a DATABASE_URL e finalize com Ctrl+Z (Windows) / Ctrl+D
gcloud secrets create mcp-token --data-file=-           # opcional: só se usar o conector MCP
gcloud secrets create google-sa --data-file=CAMINHO\service_account.json
```

A senha na `DATABASE_URL` precisa estar codificada (`@` vira `%40`, `!` vira `%21`).
Dê acesso aos segredos à conta de serviço do Cloud Run (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`) com o papel
`roles/secretmanager.secretAccessor`.

## 3. Publicar

Na raiz do projeto (usa o `Dockerfile`):

```
gcloud run deploy carmel-treinamentos ^
  --source . ^
  --region southamerica-east1 ^
  --allow-unauthenticated ^
  --no-cpu-throttling ^
  --min-instances 1 --max-instances 1 ^
  --memory 512Mi ^
  --port 10000 ^
  --set-env-vars DJANGO_DEBUG=false,GOOGLE_SERVICE_ACCOUNT_FILE=/secrets/sa/service_account.json ^
  --set-secrets DJANGO_SECRET_KEY=django-secret-key:latest,DATABASE_URL=database-url:latest,MCP_TOKEN=mcp-token:latest,/secrets/sa/service_account.json=google-sa:latest
```

(No PowerShell, troque `^` por o acento grave `` ` ``; no bash, por `\`.)

O deploy imprime a URL do serviço. Com ela, libere o host e a origem do CSRF:

```
gcloud run services update carmel-treinamentos --region southamerica-east1 ^
  --update-env-vars DJANGO_ALLOWED_HOSTS=HOST_DO_SERVICO,DJANGO_CSRF_TRUSTED_ORIGINS=https://HOST_DO_SERVICO
```

`HOST_DO_SERVICO` é a URL sem `https://` (ex.: `carmel-treinamentos-123.southamerica-east1.run.app`).

## 4. Primeiro acesso

O container aplica as migrações e cria os setores ao iniciar. Ele **não** cria usuários
(só se `SEED_DEMO_USERS=true`, o que não deve ser usado em produção).
Crie o administrador uma vez, apontando para o mesmo banco:

```
python manage.py createsuperuser
```

(rode localmente com a `DATABASE_URL` de produção no `.env`).

## 5. Domínio próprio (opcional)

Em "Gerenciar URLs personalizados" do Cloud Run, mapeie `treinamentos.carmelhoteis.com.br`
e crie o registro DNS pedido (CNAME) em "Gerenciar DNS" na KingHost. Depois inclua o domínio
em `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS`.

## Observações

- `--no-cpu-throttling` + 1 instância: necessários porque o pipeline de vídeo roda em threads.
- O disco do container é temporário; o banco e o Drive guardam o que importa.
- O PostgreSQL da KingHost não tem SSL e pode restringir por IP. Se a conexão falhar, libere o acesso
  no painel do banco ou migre para o Cloud SQL (PostgreSQL 15+).
