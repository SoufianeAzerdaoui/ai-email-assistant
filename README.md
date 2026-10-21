# Mailflow

Mailflow est un assistant de boîte mail qui centralise des messages Gmail dans une
interface web, les classe avec Gemini, propose des brouillons modifiables et envoie
une réponse uniquement après confirmation humaine.

Le navigateur communique avec Next.js, puis avec FastAPI. Il ne contacte jamais n8n
directement. FastAPI conserve les données métier dans PostgreSQL et pilote les
workflows n8n chargés de Gmail et de Gemini.

Le projet répond au [cahier des charges](<docs/[USTS] Exercice.pdf>). Le rapport
technique et les résultats mesurés sont disponibles dans
[docs/rapport_final.md](docs/rapport_final.md).

## Fonctionnalités

- authentification par mot de passe Argon2 et JWT révocable ;
- boîte de réception paginée avec recherche et filtres combinables ;
- conversations complètes dans l'ordre chronologique ;
- dashboard quotidien en heure `Europe/Paris`, résumé et cinq priorités justifiées ;
- synchronisation Gmail incrémentale toutes les dix minutes, pagination et import par
  lots de dix au maximum ;
- classification Gemini dans six catégories fermées, avec validation JSON, nouvelle
  tentative et fallback à vérifier ;
- rédaction manuelle ou génération asynchrone de brouillons IA avec les tons formel,
  neutre et court ;
- confirmation humaine avant toute demande d'envoi ;
- suivi des statuts `pending`, `sending`, `sent` et `failed`, avec reprise sûre ;
- déduplication des messages Gmail et idempotence des demandes d'envoi ;
- journalisation des erreurs n8n dans le backend.

## Architecture

```mermaid
flowchart LR
    U[Utilisateur] -->|HTTP local ou HTTPS| F[Next.js]
    F -->|REST et JWT côté serveur| A[FastAPI]
    A -->|SQLAlchemy 2| P[(PostgreSQL)]
    A -->|webhooks sécurisés| N[n8n 2.43.6]
    N -->|callbacks sécurisés| A
    N -->|OAuth2| G[Gmail API]
    N -->|classification et rédaction| M[Gemini 3.5 Flash]
```

| Élément | Technologie | Rôle |
|---|---|---|
| Interface | Next.js, TypeScript, Tailwind CSS | Dashboard, inbox, conversations et réponses |
| API | FastAPI, Pydantic | Contrats REST, sécurité, transactions et orchestration |
| Données métier | PostgreSQL 17, SQLAlchemy 2, Alembic | Utilisateurs, messages, brouillons, réponses et curseurs |
| Automatisation | n8n 2.43.6 | Synchronisation, Gemini, Gmail Send et erreurs |
| IA | Gemini 3.5 Flash, température 0.1 | Classification et génération de brouillons |

Les données internes de n8n sont persistées dans son volume Docker. Les données
Mailflow restent dans PostgreSQL.

L'interface responsive est implémentée avec les points de rupture Tailwind et des
composants adaptés au desktop et au mobile. Le lint et le build ont été utilisés pendant
le développement, mais aucun test automatisé par navigateur couvrant plusieurs tailles
d'écran n'est actuellement présent.

## Arborescence utile

```text
backend/                 API FastAPI, modèles, migrations et tests
frontend/                application Next.js
n8n/workflows/           exports des workflows
n8n/tests/               harnais n8n isolés
scripts/seed_demo.py     génération de 30 e-mails fictifs
docker-compose.yml       stack complète prévue
docker-compose.test.yml  PostgreSQL de test isolé
docs/rapport_final.md    rapport technique
```

## Prérequis

- Git ;
- Docker Engine avec Docker Compose v2 ;
- Node.js 22 et npm pour une exécution locale du frontend ;
- Python 3.12 pour une exécution locale du backend ;
- un compte Gmail de test et un projet OAuth2 Google pour les workflows Gmail ;
- un credential Google Gemini configuré manuellement dans n8n.

## Configuration

Depuis un clone vierge :

```bash
git clone https://github.com/SoufianeAzerdaoui/ai-email-assistant.git
cd ai-email-assistant
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

Remplacer toutes les valeurs `replace-with-...` ou `change-me`. Des valeurs aléatoires
peuvent être générées localement avec `openssl rand -hex 32`. Ne jamais les recopier
dans Git, un export n8n ou une capture d'écran.

### Variables à la racine

| Variable | Usage |
|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Base applicative PostgreSQL |
| `POSTGRES_PORT` | Port PostgreSQL publié sur `127.0.0.1` |
| `BACKEND_PORT`, `FRONTEND_PORT`, `N8N_PORT` | Ports locaux des services |
| `N8N_ENCRYPTION_KEY` | Chiffrement des credentials n8n ; doit rester stable |
| `GENERIC_TIMEZONE` | Fuseau n8n, normalement `Europe/Paris` |
| `EXECUTIONS_DATA_MAX_AGE` | Conservation n8n, 72 heures par défaut |
| `EXECUTIONS_DATA_PRUNE_MAX_COUNT` | Maximum de 500 exécutions par défaut |
| `N8N_BACKEND_URL` | URL FastAPI des anciens exports ; `http://backend:8000` en Compose complet |
| `MAILFLOW_USER_ID` | UUID non secret ; les exports actuels utilisent leur nœud de configuration |

### Variables du backend

| Variable | Usage |
|---|---|
| `DATABASE_URL` | PostgreSQL local ; Compose la remplace par son URL interne |
| `JWT_SECRET` | Signature des JWT, 32 caractères minimum |
| `JWT_EXPIRE_MINUTES` | Durée de validité des JWT |
| `WEBHOOK_SECRET` | Sens n8n vers FastAPI, credential **Mailflow - Vers FastAPI** |
| `N8N_WEBHOOK_SECRET` | Sens FastAPI vers n8n, credential **Mailflow - Entrée n8n** |
| `N8N_DRAFT_WEBHOOK_URL` | Webhook de génération, chemin `/webhook/` |
| `N8N_GMAIL_SEND_WEBHOOK_URL` | Webhook d'envoi, chemin `/webhook/` |
| `N8N_REQUEST_TIMEOUT_SECONDS` | Timeout FastAPI vers n8n |

Dans le Compose complet, `DATABASE_URL` et les deux URL n8n sont remplacées par les
adresses internes déclarées dans `docker-compose.yml`. `frontend/.env.local` sert au
mode local ; dans Compose, Next.js utilise `http://backend:8000`.

## Démarrage avec Docker Compose

```bash
docker compose config -q
docker compose up -d --build --wait
docker compose ps
```

Le backend applique automatiquement les migrations Alembic avant Uvicorn. Les services
sont publiés uniquement sur la boucle locale dans la configuration Compose prévue :

- Mailflow : <http://localhost:3000>
- FastAPI et OpenAPI : <http://localhost:8000/docs>
- n8n : <http://localhost:5678>
- PostgreSQL : `127.0.0.1:5432` par défaut

Lors du premier accès à n8n, créer le compte propriétaire local proposé par l'interface.
L'éditeur reste lié à `127.0.0.1` et ne doit pas être publié directement sur Internet.

> La configuration Compose est validée statiquement et les images frontend/backend ont
> été construites. Le démarrage simultané des quatre services depuis une installation
> vierge n'a pas encore fait l'objet d'un test de bout en bout. Il doit être suivi des
> contrôles de santé et d'un test fonctionnel.

> L'installation hybride utilisée pendant le développement est différente : FastAPI et
> Next.js sont lancés directement sur Ubuntu et, selon le dernier audit, écoutent encore
> sur toutes les interfaces. Ils peuvent donc être accessibles depuis le réseau local.
> Le pare-feu de l'hôte ou une liaison explicite à `127.0.0.1` reste nécessaire pour les
> limiter à la machine.

Créer le premier administrateur, sans route d'inscription publique :

```bash
docker compose exec backend python -m app.cli create-admin --email admin@example.test
```

Le mot de passe est saisi sans affichage et doit contenir au moins douze caractères.
L'UUID requis dans n8n est disponible dans `GET /auth/me` après connexion, ou dans
PostgreSQL pour l'administrateur de l'installation.

En architecture hybride, utiliser `http://host.docker.internal:8000` dans les nœuds
**Configuration Mailflow**. En Compose complet, utiliser `http://backend:8000`.

## Configuration de n8n

Importer manuellement, dans cet ordre :

1. `n8n/workflows/workflow_error_handler.json`
2. `n8n/workflows/ai_classification.json`
3. `n8n/workflows/ai_draft_generation.json`
4. `n8n/workflows/gmail_send.json`
5. `n8n/workflows/gmail_sync_batch_production.json`

Ne pas activer `gmail_sync.json`, `gmail_sync_batch_candidate.json` ni
`gemini_classification_benchmark.json` en production.

### Credentials à créer

| Nom conseillé | Type | Configuration |
|---|---|---|
| Gmail OAuth2 | Google OAuth2 | Compte Gmail de test, lecture puis envoi contrôlé |
| Gemini | Google Gemini | Clé configurée dans n8n, absente des exports |
| Mailflow - Entrée n8n | Header Auth | `X-Webhook-Secret` = `N8N_WEBHOOK_SECRET` |
| Mailflow - Vers FastAPI | Header Auth | `X-Webhook-Secret` = `WEBHOOK_SECRET` |

Après import :

1. affecter les credentials Gmail, Gemini et Header Auth aux nœuds concernés ;
2. renseigner `backend_url` et `mailflow_user_id` dans les nœuds de configuration ;
3. choisir **Mailflow - Gestion erreurs n8n** comme Error Workflow ;
4. vérifier `/webhook/`, jamais `/webhook-test/` ;
5. tester manuellement avec des données non personnelles ;
6. activer seulement les workflows validés, puis le planning Gmail Sync Batch.

Le workflow Batch traite les détails séquentiellement, attend 2,5 secondes entre les
opérations concernées, importe au plus dix messages par requête et ne valide le curseur
qu'après le succès de tous les lots. Le mode TEST est limité à cinquante messages mais
écrit les messages importés ; il n'avance jamais le curseur.

## Utilisation

1. ouvrir <http://localhost:3000> et se connecter ;
2. consulter le dashboard ou choisir une date ;
3. filtrer et rechercher la boîte de réception ;
4. ouvrir un fil ;
5. rédiger une réponse ou demander un brouillon IA ;
6. modifier le brouillon et choisir son ton ;
7. confirmer explicitement l'envoi ;
8. attendre le statut backend : en cours, envoyé ou échec.

Un résultat Gmail ambigu reste en attente de réconciliation. Il ne doit jamais être
renvoyé automatiquement.

## Données de démonstration

Le script idempotent crée trente messages fictifs dans plusieurs fils pour un utilisateur
existant :

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
PYTHONPATH=backend backend/.venv/bin/python scripts/seed_demo.py \
  --user-email admin@example.test
```

Avec la stack déjà démarrée, il est aussi possible de monter le script en lecture seule
dans un conteneur éphémère :

```bash
docker compose run --rm --no-deps \
  -v "$PWD/scripts:/scripts:ro" \
  backend python /scripts/seed_demo.py --user-email admin@example.test
```

Le conteneur backend permanent ne copie pas `scripts/` dans son image.

## Tests automatisés

### Backend avec PostgreSQL isolé

```bash
docker compose -f docker-compose.test.yml up -d --wait
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt

export TEST_DATABASE_URL='postgresql+psycopg://mailflow_test:mailflow_test_only@127.0.0.1:55432/mailflow_test'
export DATABASE_URL="$TEST_DATABASE_URL"
PYTHONPATH=backend backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v

docker compose -f docker-compose.test.yml down
```

Le projet de test utilise le port 55432 et un volume distinct. Vérifier
`TEST_DATABASE_URL` avant chaque exécution : la suite ne doit jamais cibler la base réelle.

Résultats confirmés :

- 151 tests backend réussis lors de la dernière suite complète ;
- 55 tests ciblés réussis lors de la validation des exports et de la sécurité.

Les 55 tests recouvrent une partie de la suite et ne s'ajoutent pas aux 151.

### Frontend

```bash
cd frontend
npm ci
npm run lint
npm run build
```

### Configuration

```bash
docker compose config -q
python3 -m json.tool n8n/workflows/gmail_sync_batch_production.json >/dev/null
git diff --check
```

## Mesures de performance

Trois essais ont traité chacun **30 messages fictifs**, avec Gmail simulé et de vrais
appels HTTP sur le parcours **n8n → FastAPI → PostgreSQL** isolé :

| Essai | Durée |
|---:|---:|
| 1 | 2,407 s |
| 2 | 2,500 s |
| 3 | 2,405 s |
| **Médiane** | **2,407 s** |

Cette mesure ne représente pas une synchronisation Gmail réelle. Elle exclut notamment
la latence Gmail, OAuth2, les quotas réseau et les appels Gemini.

## GitHub

- dépôt existant : `https://github.com/SoufianeAzerdaoui/ai-email-assistant` ;
- J'ai utilisé des branches et des Pull Requests pour
organiser le développement et intégrer les modifications.

- Les collaborateurs ajoutés au dépôt sont :
  - lilgar77
  - Holo795

## Sécurité

- Argon2, JWT expirables et révocation au logout ;
- cookie Next.js `HttpOnly`, `SameSite=Lax`, `Secure` en production ;
- isolation et contraintes SQL par utilisateur ;
- webhooks `X-Webhook-Secret` avec secrets distincts selon le sens ;
- credentials n8n chiffrés et n8n épinglé à 2.43.6 ;
- ports des services Docker liés à `127.0.0.1` dans le Compose prévu ;
- réseau PostgreSQL `internal` défini dans le Compose prévu ;
- purge n8n, rétention 72 heures, maximum 500 exécutions ;
- succès et exécutions manuelles non conservés systématiquement ;
- rotation Docker à trois fichiers de 10 Mo ;
- sauvegardes PostgreSQL et n8n vérifiées ;
- `.env`, credentials et secrets exclus de Git.

##  Limites connues

- la synchronisation Gmail est périodique (10 minutes)
  et ne permet pas une réception instantanée ;
- les quotas Gmail et Gemini peuvent ralentir
  ou interrompre temporairement certains traitements ;
- la récupération séquentielle des messages limite
  le débit sur les boîtes Gmail volumineuses.