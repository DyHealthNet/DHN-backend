import logging
import os
import sys
import timeit

from django.apps import AppConfig

from network.utils.data_manager import DataManager

logger = logging.getLogger('network')


class NetworksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "network"

    def __init__(self, app_name, app_module):
        super().__init__(app_name, app_module)
        self.DATA_MANAGER = None

    def ready(self):
        is_runserver = len(sys.argv) > 1 and sys.argv[1] == 'runserver'

        if is_runserver and os.environ.get("RUN_MAIN") != "true":
            logger.info("Skipping loading data during autoreload in development")
            return

        start = timeit.default_timer()
        self.DATA_MANAGER = DataManager()
        self.DATA_MANAGER.load_data()
        if not self.DATA_MANAGER.is_loaded():
            logger.error("Failed to load data, exiting")
            sys.exit(1)

        all_keys = self.DATA_MANAGER.get_valid_keys()
        available_omics = [key for key in all_keys if self.DATA_MANAGER.is_available(key) and not key.startswith('all')]
        for key in available_omics:
            logger.info(f"Starting server with: {key}")
        logger.info(f"Startup time: {timeit.default_timer() - start}")
