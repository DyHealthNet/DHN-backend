#!/bin/bash

# Exit on error
set -e

# Run migrations
python manage.py makemigrations
python manage.py migrate

# Create a superuser if it doesn’t exist
python manage.py shell <<EOF
from django.contrib.auth import get_user_model
import os

User = get_user_model()
if not User.objects.filter(username=os.getenv("ADMIN_USER")).exists():
    User.objects.create_superuser(
        username=os.getenv("ADMIN_USER"),
        password=os.getenv("ADMIN_PASS")
    )
EOF

# Execute the CMD from the Dockerfile
exec "$@"
