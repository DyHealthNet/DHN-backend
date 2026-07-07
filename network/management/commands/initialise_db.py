from django.core.management.base import BaseCommand
import sys
import pandas as pd
import network.utils.db_utils as db_utils
import environ
import subprocess
import traceback
import logging

# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env()
environ.Env.read_env()

logger = logging.getLogger('network')


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--force', action='store_true', help='Force the initialization of the database')

    def handle(self, *args, **options):
        try:
            # check if the database is already initialized
            logger.debug(f"Total node rows: {db_utils.get_total_node_rows()}")
            if db_utils.get_total_node_rows() > 0 and not options['force']:
                logger.info("Database is already filled. Skipping the initialization.")
                return

            logger.info("Initializing the database. This will probably take multiple hours.")
            self.init_db()

        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            traceback.print_exc()
            sys.exit(1)

    def init_db(self):
        # do checks that all necessary files/columns are configured
        if not all([env('DATA_META_PATHS'), env('DATA_LABEL_COLUMNS'), env('DATA_TYPE_COLUMNS')]):
            raise ValueError(
                "Make sure that the following environment variables are set: DATA_META_PATHS, "
                "DATA_LABEL_COLUMNS, DATA_TYPE_COLUMNS")

        if not all([env('PARAMETRIC_EDGES_PATH', default=None), env('NONPARAMETRIC_EDGES_PATH', default=None)]):
            raise ValueError(
                "Make sure that both PARAMETRIC_EDGES_PATH and NONPARAMETRIC_EDGES_PATH are set")

        if not all([env('DATABASE_USER'), env('DATABASE_PASS'), env('DATABASE_NAME'), env('DB_HOST'),
                    env('DB_PORT')]):
            raise ValueError(
                "Make sure that the following environment variables are set: DATABSE_USER, DATABASE_PASSWORD, "
                "DATABASE_NAME, DATABASE_HOST")

        # install the dependencies
        subprocess.run(["pip", "install", "-r", "/app/database/requirements.txt"], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # execute a subprocess to create the database
        subprocess.run(["python", "-u", "/app/database/setup_db_new.py"], check=True)
