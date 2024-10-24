import os
import sys
import logging
from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError
from django.apps import apps
from network.utils import check_files_and_return
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env()
environ.Env.read_env()

logger = logging.getLogger('network')


class Command(BaseCommand):
    def handle(self, *args, **options):
        # Store the results of each check
        results = {
            "files": False,
            "columns": False,
            "database": False,
            "tables": False
        }

        logger.info("Start Health checks:")
        try:
            results["files"] = self.check_files()
        except Exception as e:
            logger.error(f"❌  Files check failed: {e}")

        try:
            results["columns"] = self.check_columns()
        except Exception as e:
            logger.error(f"❌  Columns check failed: {e}")

        try:
            results["database"] = self.check_database()
        except Exception as e:
            logger.error(f"❌  Database check failed: {e}")

        try:
            results["tables"] = self.check_tables()
        except Exception as e:
            logger.error(f"❌  Tables check failed: {e}")

        # Exit with a non-zero code if any check failed
        if not all(results.values()):
            logger.error("Health check failed.")
            sys.exit(1)
        else:
            logger.info("Health check successfully passed.")

    @staticmethod
    def check_files():
        required_files = [
            env("PHENOTYPE_PATH"),
            env("PHENOTYPE_META_PATH")
        ]
        for file_path in required_files:
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"Required file not found: {file_path}")
            else:
                check_files_and_return(file_path, return_dataset=False)
        logger.info("✅  All required files are present.")
        return True

    @staticmethod
    def check_columns():
        # read only the first line of the file and check if the PATIENT_ID_COLUMN is present
        files = [
            env('PHENOTYPE_PATH'),
            env('PROTEIN_PATH'),
            env('METABOLITE_PATH')
        ]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue
            with open(file_path, 'r') as file:
                columns = file.readline().strip()
            if env("PATIENT_ID_COLUMN") not in columns:
                raise Exception(f"Column {env('PATIENT_ID_COLUMN')} not found in {file_path}")
        logger.info("✅  Patient ID column is present everywhere.")
        return True

    @staticmethod
    def check_database():
        db_conn = connections['default']
        try:
            db_conn.cursor()
        except OperationalError:
            raise OperationalError("Database connection failed.")
        logger.info("✅  The database is successfully connected.")
        return True

    @staticmethod
    def check_tables():
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
        logger.info("✅  All necessary database tables, views, and materialized views are present.")
        return True
