# Backend PostgreSQL

Depuis la racine du dépôt :

```bash
export POSTGRES_PASSWORD='change-me'
docker compose up -d --wait postgres
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
export DATABASE_URL='postgresql+psycopg://email_assistant:change-me@localhost:5432/email_assistant'
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

Remplacer `change-me` par le même mot de passe dans les deux variables. Les
caractères réservés du mot de passe doivent être encodés dans l’URL.
`DATABASE_URL` est obligatoire pour accéder à la base et pour Alembic. Copiez
`.env.example` vers `backend/.env` : l’application charge ce fichier au démarrage.
Les schémas `postgresql://` et `postgresql+psycopg://` utilisent psycopg 3.

La route `GET /health` reste indépendante de la base. Les tables sont créées
uniquement par Alembic. `get_db` fournit une session FastAPI ; chaque écriture
doit appeler explicitement `commit()`.

## Modèle et contraintes

- Un utilisateur possède ses fils, e-mails, réponses et exécutions de synchronisation.
- Les e-mails appartiennent à un fil ; brouillons et réponses référencent un e-mail.
  Une réponse peut référencer un brouillon du même e-mail.
- Les identifiants Gmail des fils et messages sont uniques par utilisateur.
- Une réponse est unique par `(user_id, idempotency_key)`, ainsi que par identifiant
  Gmail une fois envoyé. La même clé doit être conservée lors d’une nouvelle tentative.
- Les exécutions de synchronisation et notifications d’erreur ont aussi une clé
  d’idempotence par utilisateur.
- `SyncState` conserve un curseur et la dernière exécution réussie, avec une seule
  ligne par utilisateur. Le futur service de synchronisation devra mettre cet état
  à jour uniquement après une synchronisation réussie, dans la même transaction.
- Les clés étrangères composites empêchent les associations entre utilisateurs.
  Les suppressions de parents référencés sont refusées pour préserver l’historique.
- Les contraintes évitent les doublons en base ; le protocole d’envoi Gmail et ses
  reprises devront réutiliser la même réponse pour empêcher un double envoi externe.

## Migrations

```bash
backend/.venv/bin/alembic -c backend/alembic.ini check
backend/.venv/bin/alembic -c backend/alembic.ini revision --autogenerate -m 'description'
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
# Sur une base de test uniquement : supprime toutes les tables applicatives.
backend/.venv/bin/alembic -c backend/alembic.ini downgrade base
```

Les tests d’intégration utilisent une base PostgreSQL de test déjà migrée ; chaque
test annule ses écritures et ne modifie pas le schéma :

```bash
export TEST_DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/test_database'
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
```

## Authentification

Définissez dans `backend/.env` un `JWT_SECRET` aléatoire d’au moins 32 caractères
et la durée `JWT_EXPIRE_MINUTES`. Après la migration, créez le premier compte sans
exposer de route d’inscription :

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.cli create-admin --email admin@example.com
```

Le mot de passe, saisi sans affichage, doit contenir au moins 12 caractères. Il est
stocké avec Argon2. `POST /auth/login` renvoie un JWT Bearer, `GET /auth/me` vérifie
le compte courant et `POST /auth/logout` révoque tous les JWT émis pour ce compte.
La dépendance `app.auth.get_current_user` protège les futures routes FastAPI.
