import os
import sys
import logging
from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError
from django.apps import apps

import environ
# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env()
environ.Env.read_env()

#logger = logging.getLogger(__name__)

class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            print("Start Health checks:")
            self.check_files()
            self.check_database()
            self.check_tables()
            print("Health check successfully passed.")
        except Exception as e:
            print(f"Health check failed: {e}")
            sys.exit(1)

    def check_files(self):
        required_files = [
            env("PHENOTYPE_PATH"),
            env("PHENOTYPE_META_PATH")
        ]
        for file_path in required_files:
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"Required file not found: {file_path}")
        print("All required files are present.")

    def check_database(self):
        db_conn = connections['default']
        try:
            db_conn.cursor()
        except OperationalError:
            raise OperationalError("Database connection failed.")
        print("Database connection successful.")

    def check_tables(self):
        db_conn = connections['default']
        with db_conn.cursor() as cursor:
            cursor.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public'
                UNION
                SELECT table_name FROM information_schema.views 
                WHERE table_schema = 'public'
                UNION
                SELECT matviewname AS table_name FROM pg_matviews 
                WHERE schemaname = 'public';
            """)
            existing_objects = [row[0] for row in cursor.fetchall()]
        models = apps.get_models()
        excluded_models = {
            'auth.Permission',
            'auth.Group',
            'auth.User',
            'contenttypes.ContentType',
            'sessions.Session',
        }

        missing_tables = [
            model._meta.db_table for model in models
            if model._meta.db_table not in existing_objects
            and f"{model._meta.app_label}.{model.__name__}" not in excluded_models
        ]

        if missing_tables:
            raise Exception(f"Missing database tables/views/materialized views: {', '.join(missing_tables)}")
        print("All necessary database tables, views, and materialized views are present.")