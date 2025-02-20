#!/bin/bash

# Exit on error
set -e

# Run migrations
python manage.py makemigrations
python manage.py migrate

# print the value of CALCULATED_EDGES_PATH
echo "CALCULATED_EDGES_PATH: $CALCULATED_EDGES_PATH"

# check if the CALCULATED_EDGES_PATH is a file
if [ -f "$CALCULATED_EDGES_PATH" ]; then
    echo "Scores already calculated. Skipping."
else
    echo "Calculating scores..."
    # Run the script to calculate the edges
    python manage.py compute_association_scores
fi

# Initialize the database
python manage.py initialise_db

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
