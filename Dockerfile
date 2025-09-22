# ---- Runtime image ----
FROM python:3.12-slim AS runtime

# Éviter les fichiers .pyc et activer l’output non-bufferisé
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# (Optionnel) Installer quelques utilitaires système légers
# et en même temps mettre à jour le système.
# Ajoutez des libs ici si votre bot en a besoin (ex: libpq5, curl, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Répertoire de travail
WORKDIR /app

# Copier uniquement les requirements d'abord pour bénéficier du cache
COPY requirements.txt /app/requirements.txt

# Installer les dépendances (sans cache)
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY src/ /app/src

# Créer un utilisateur non-root
RUN useradd -m -u 10001 appuser
USER appuser

# Commande de démarrage
# Utilise l’exécution en tant que module pour résoudre proprement les imports
CMD ["python", "-m", "src.run"]
