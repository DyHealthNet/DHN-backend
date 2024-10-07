import os
import sys
from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError
from django.apps import apps
from network.utils import check_files_and_return

import environ
# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env()
environ.Env.read_env()

#logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def handle(self, *args, **options):
        # Store the results of each check
        results = {
            "files": False,
            "database": False,
            "tables": False
        }

        print("Start Health checks:")
        try:
            results["files"] = self.check_files()
        except Exception as e:
            print(f"❌  Files check failed: {e}")

        try:
            results["database"] = self.check_database()
        except Exception as e:
            print(f"❌  Database check failed: {e}")

        try:
            results["tables"] = self.check_tables()
        except Exception as e:
            print(f"❌  Tables check failed: {e}")

        # Exit with a non-zero code if any check failed
        if not all(results.values()):
            print("Health check failed.")
            sys.exit(1)
        else:
            print("Health check successfully passed.")

    def check_files(self):
        required_files = [
            env("PHENOTYPE_PATH"),
            env("PHENOTYPE_META_PATH")
        ]
        for file_path in required_files:
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"Required file not found: {file_path}")
            else:
                check_files_and_return(file_path, return_dataset=False)
        print("✅  All required files are present.")
        return True

    def check_database(self):
        db_conn = connections['default']
        try:
            db_conn.cursor()
        except OperationalError:
            raise OperationalError("Database connection failed.")
        print("✅  The database is successfully connected.")
        return True

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
        print("✅  All necessary database tables, views, and materialized views are present.")
        return True
