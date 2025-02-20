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
            logger.debug(f"Total cohort rows: {db_utils.get_total_cohort_rows()}")
            if db_utils.get_total_cohort_rows() > 0 and not options['force']:
                logger.info("Database is already filled. Skipping the initialization.")
                return

            logger.info("Initializing the database. This will probably take multiple hours.")
            self.init_db()

        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            traceback.print_exc()
            sys.exit(1)

    def init_db(self):
        # do checks that all necessary files are present
        if not all([env("PHENOTYPE_PATH"), env('PROTEIN_PATH'), env('CALCULATED_EDGES_PATH'), env('METABOLITE_PATH'),
                    env('DATA_DIR')]):
            raise ValueError(
                "Make sure that the following files or directories are present: PHENOTYPE_PATH, PROTEIN_PATH, "
                "CALCULATED_EDGES_PATH, METABOLITE_PATH, DATA_PATH")

        if not all([env('DATABASE_USER'), env('DATABASE_PASS'), env('DATABASE_NAME'), env('DB_HOST'),
                    env('DB_PORT')]):
            raise ValueError(
                "Make sure that the following environment variables are set: DATABSE_USER, DATABASE_PASSWORD, "
                "DATABASE_NAME, DATABASE_HOST")

        if not env('OBSERVATION_SOURCE'):
            raise ValueError("Make sure that OBSERVATION_SOURCE is set in the environment variables")

        # install the dependencies
        subprocess.run(["pip", "install", "-r", "/app/database/requirements.txt"], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # execute a subprocess to create the database
        # execute python -u database/setup_db.py
        subprocess.run(["python", "-u", "/app/database/setup_db.py"], check=True)
