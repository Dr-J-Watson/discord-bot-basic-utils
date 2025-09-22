# Bot Discord + Postgres (Docker)

## Fonctionnalités
- Bot Discord (slash commands) avec `discord.py`
- Commande `/ping`
- Connexion optionnelle à PostgreSQL via `asyncpg`
- Configuration via variables d'environnement
- Déploiement Docker + `docker-compose`

## Arborescence
```
.
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── src/
│   ├── run.py                # Point d'entrée du bot
│   ├── core/                 # Modules centraux (config, bot, db, logging, permissions)
│   ├── commands/             # Commandes slash (ping, list_users, sync_users, autorole...)
│   ├── db/                   # Accès et schémas base de données
│   ├── events/               # Gestion des événements Discord
│   ├── views/                # UI Discord (embeds, vues, boutons)
│   └── requirements.txt      # Dépendances Python pour src
```

## Configuration
Copiez `.env.example` vers `.env` et renseignez votre token Discord.

```
cp .env.example .env
# Éditez .env pour mettre BOT_TOKEN
```

Variables importantes:
- `BOT_TOKEN`: Token de l'application/bot Discord
- `DATABASE_URL`: (optionnel) DSN Postgres. Par défaut défini pour le service `db`.

## Lancer en développement (sans Docker)
Python 3.12 recommandé.

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # ajouter votre BOT_TOKEN
python -m src.bot
```

## Lancer avec Docker
Build + lancement:
```
docker compose up --build
```
Le bot redémarre sauf arrêt manuel. Le volume `db_data` persiste les données Postgres.

## Ajout de commandes
## Modules principaux

- **core/** : Logique centrale du bot
	- `bot.py` : Client Discord, gestion des commandes et événements, initialisation DB
	- `config.py` : Chargement de la configuration et des intents
	- `db.py` : Helpers pour PostgreSQL (pool, schéma, upsert)
	- `logging_config.py` : Setup du logging, déduplication des logs
	- `permissions.py` : Décorateurs et utilitaires pour les permissions Discord
	- `voice_hubs/` : Gestion des salons vocaux dynamiques
- **commands/** : Commandes slash
	- Un fichier par commande ou groupe de commandes (ex: `ping.py`, `autorole.py`)
- **db/** : Schémas et helpers pour chaque fonctionnalité (autorole, welcome, etc.)
- **events/** : Gestion des événements Discord (ex: arrivée de membres)
- **views/** : UI Discord (embeds, vues, boutons, pagination)
### Commandes slash disponibles

- `/ping` : Affiche la latence du bot (admin seulement)
- `/list_users` : Liste paginée des utilisateurs en base
- `/sync_users` : Synchronise les membres du serveur dans la base (admin)
- `/autorole` : Gestion avancée des groupes d'autoroles (créer, ajouter, retirer, lister, etc.)

Pour ajouter une commande, créez un fichier dans `src/commands/` et enregistrez-la via la fonction `register(bot)`.

## Accès base de données
### Schéma principal

Le bot utilise PostgreSQL pour stocker les membres Discord et les données des fonctionnalités (autorole, welcome, etc.).

Table principale :
```sql
CREATE TABLE IF NOT EXISTS discord_user (
	id BIGINT PRIMARY KEY,
	display_name TEXT NOT NULL,
	username TEXT NOT NULL,
	updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_discord_user_updated_at ON discord_user(updated_at DESC);
```

Helpers disponibles dans `core/db.py` :
- `get_pool(dsn)` : Initialise le pool asyncpg
- `ensure_schema(pool)` : Crée le schéma si absent
- `upsert_user(pool, ...)` : Ajoute ou met à jour un utilisateur
- `bulk_upsert_users(pool, ...)` : Upsert en masse
Utilisez `await bot.db_pool.fetch(...)` ou créez des helpers. Le pool est initialisé si `DATABASE_URL` est présent.

## Production
- Fixer une version précise de l'image Python si nécessaire.
- Utiliser un secret manager pour le token.
- Ajouter gestion de migrations (ex: Alembic ou simple scripts SQL).

## Prochaines idées
- Gestion des cogs
- Logging structuré (JSON)
- Sentry / OpenTelemetry
- Tests automatisés

## Licence
Projet de base libre d'adaptation.
