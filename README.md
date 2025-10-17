# Vagrolant Discord Bot

Bot Discord modulaire, prêt pour la production, basé sur `discord.py` et PostgreSQL. Il propose un système complet de salons vocaux dynamiques (voice hubs), une gestion avancée des rôles automatiques et plusieurs commandes d’administration, le tout empaqueté dans un environnement Docker reproductible.

## Sommaire
- [Fonctionnalités clés](#fonctionnalités-clés)
- [Architecture](#architecture)
- [Prérequis](#prérequis)
- [Mise en route rapide (Docker Compose)](#mise-en-route-rapide-docker-compose)
- [Développement local sans Docker](#développement-local-sans-docker)
- [Variables d’environnement](#variables-denvironnement)
- [Commandes slash disponibles](#commandes-slash-disponibles)
- [Voice hubs : vue d’ensemble](#voice-hubs--vue-densemble)
- [Flux de développement](#flux-de-développement)
- [Dépannage](#dépannage)

## Fonctionnalités clés
- **Voice hubs dynamiques** : création/suppression automatique de salons vocaux, panneau de contrôle interactif (modes Ouvert/Fermé/Privé/Conférence, whitelist/blacklist, purge, transfert de propriété, suppression).
- **Autoroles persistants** : création de groupes de rôles, vues persistantes et synchronisation des membres.
- **Synchronisation utilisateurs** : commandes pour inventorier et synchroniser les membres d’un serveur dans PostgreSQL.
- **Explorateur de base (`/dbbrowse`)** : consultation rapide des enregistrements depuis Discord.
- **Stack dockerisée** : Docker + `docker-compose` pour orchestrer bot et base, migrations automatiques et logs consolidés.
- **Configuration centralisée** : variables d’environnement via `.env`, intents Discord configurables, logging dédupliqué.

## Architecture
```
.
├── Dockerfile
├── docker-compose.yml
├── requirements.txt          # Dépendances globales (build Docker)
├── .env.example              # Exemple de configuration
├── src/
│   ├── run.py                # Point d’entrée (initialise logging + bot)
│   ├── core/
│   │   ├── bot.py            # Client Discord personnalisé (setup, sync, événements)
│   │   ├── config.py         # Chargement de la configuration et des intents
│   │   ├── db.py             # Connexion asyncpg et migrations de base
│   │   ├── logging_config.py # Logging unifié + filtrage des doublons
│   │   ├── permissions.py    # Décorateurs/contrôles de permissions
│   │   └── voice_hubs/       # Logiciel de hub vocal (manager, modèles)
│   ├── commands/             # Slash commands (autorole, hub, dbbrowse, etc.)
│   ├── db/                   # Schémas/méthodes SQL par feature
│   ├── events/               # Abonnements aux événements Discord
│   └── views/                # Embeds et composants UI (panneau voice hubs, autorole…)
└── tools/                    # Utilitaires additionnels / scaffolding
```

## Prérequis
- Docker et Docker Compose (v2) pour l’environnement recommandé.
- (Optionnel) Python 3.12 si vous souhaitez exécuter le bot hors conteneur.
- Un bot Discord (token) et, pour les voice hubs, les permissions administrateur sur le serveur cible.

## Mise en route rapide (Docker Compose)
1. **Cloner le dépôt et configurer l’environnement**
	```bash
	cp .env.example .env
	# Éditez .env pour définir BOT_TOKEN et, si besoin, la configuration Postgres/Twitch
	```

2. **Lancer la stack**
	```bash
	docker compose up -d --build
	```
	- Le service `db` (Postgres) est provisionné puis contrôlé via un healthcheck.
	- Le service `bot` attend que la base soit prête, applique les migrations et synchronise les slash commands.

3. **Suivre les logs**
	```bash
	docker compose logs -f bot
	```
	Vous devriez voir la connexion au Gateway Discord puis l’initialisation des voice hubs.

Le volume nommé `db_data` persiste les données PostgreSQL. Le dossier `src/` est monté en lecture seule dans le conteneur pour un cycle de développement rapide (modifications sur l’hôte, redémarrage léger du conteneur).

## Développement local sans Docker
1. Créez un environnement virtuel et installez les dépendances :
	```bash
	python -m venv .venv
	source .venv/bin/activate
	pip install -r requirements.txt
	```
2. Configurez `.env` avec au minimum `BOT_TOKEN` (et `DATABASE_URL` si vous utilisez Postgres localement).
3. Lancez le bot :
	```bash
	python src/run.py
	```

> ⚠️  Les modules nécessitant Postgres (autorole, voice hubs, dbbrowse…) supposent que `DATABASE_URL` est défini et accessible.

## Variables d’environnement
| Variable | Obligatoire | Description | Valeur par défaut |
|----------|-------------|-------------|-------------------|
| `BOT_TOKEN` | ✅ | Token du bot Discord | — |
| `DATABASE_URL` | ✅ (en production) | DSN Postgres utilisé par `asyncpg` | `postgresql://postgres:postgres@db:5432/postgres` dans Docker |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_HOST` / `POSTGRES_PORT` | ✅ (Docker) | Paramètres injectés dans la base Postgres et pour générer `DATABASE_URL` | Voir `.env.example` |
| `ENABLE_PRESENCES` | ❌ | Active l’intent `presences` si `true` | `false` |
| `LOG_LEVEL` | ❌ | Niveau de log global (`INFO`, `DEBUG`, …) | `INFO` |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` / `TWITCH_REDIRECT_URI` | ❌ | Paramètres Twitch si vous activez les modules liés (optionnels) | — |

## Commandes slash disponibles
| Commande | Description succincte | Accès |
|----------|----------------------|-------|
| `/ping` | Latence et statut du bot | Admin |
| `/list_users` | Liste paginée des utilisateurs présents en base | Admin |
| `/sync_users` | Synchronise les membres du serveur vers PostgreSQL | Admin |
| `/dbbrowse …` | Consultation/filtrage des données persistées | Admin |
| `/autorole …` | Gestion complète des groupes d’autoroles (création, assignation, suppression) | Basé sur permissions |
| `/hub list/create/delete/config/panel` | Administration des voice hubs et récupération du panneau de contrôle personnel | Admin ou propriétaire |

Les commandes sont chargées dynamiquement depuis `src/commands/__init__.py`. Pour en ajouter :
1. Créez un nouveau fichier dans `src/commands/`.
2. Implémentez une fonction `register(bot)` qui attache vos commandes à `bot.tree`.
3. Ajoutez l’import dans `commands/__init__.py` si nécessaire.

## Voice hubs : vue d’ensemble
- Les salons marqués comme hubs (via `/hub create`) servent de points d’entrée.
- Lorsqu’un membre rejoint le hub, un salon dynamique est créé et contrôlé par ce membre.
- Le panneau de contrôle (message + boutons) permet notamment :
  - Changer le mode (Ouvert/Fermé/Privé/Conférence).
  - Gérer whitelist/blacklist (ajout/retrait via sélecteurs Discord).
  - Purger les membres qui ne respectent plus les règles d’accès.
  - Supprimer le salon ou transférer la propriété à un membre présent.
- Si l’envoi du panneau dans le salon vocal échoue, le bot tente un envoi en DM.
- Les salons vides sont supprimés automatiquement ; un job de nettoyage au démarrage retire les salons orphelins côté Discord et base.

## Flux de développement
- **Lancement dev** : `docker compose up --build` (montage `src/` en lecture seule). Un `docker compose restart bot` suffit après une modification.
- **Logs** : `docker compose logs -f bot`.
- **Inspection DB** : `docker compose exec db psql -U $POSTGRES_USER $POSTGRES_DB`.
- **Compilation rapide** : dans le conteneur, vous pouvez exécuter `python -m compileall src`. Notez que le montage en lecture seule empêche la création des fichiers `.pyc`; c’est normal en mode dev Docker.

## Dépannage
- **BOT_TOKEN manquant** : le bot s’arrête immédiatement avec un message explicite.
- **Permissions insuffisantes** : assurez-vous que le bot possède les permissions `Manage Channels`, `Move Members`, `Manage Roles` selon les fonctionnalités activées.
- **Voice hubs inactifs après redémarrage** : vérifiez les logs `Cleanup orphelins`. Ils indiquent les hubs supprimés côté Discord et les salles désynchronisées.
- **Twitch non configuré** : les variables Twitch sont optionnelles. Laissez-les vides si vous n’utilisez pas l’intégration.

Pour toute contribution, n’hésitez pas à ouvrir une issue ou proposer une PR en décrivant la fonctionnalité visée. Bon build !
