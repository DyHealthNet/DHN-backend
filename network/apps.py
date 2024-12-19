import json
import sys
import timeit

from django.apps import AppConfig

from network.score_calculation import separate_cat_cont
from network.utils.data_manager import DataManager
from network.utils.startup_utils import *
import environ

env = environ.Env()
environ.Env.read_env()


class NetworksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "network"

    def __init__(self, app_name, app_module):
        super().__init__(app_name, app_module)
        self.DATA_MANAGER = None

    def ready(self):
        # To avoid loading the files twice during server start
        if os.environ.get("RUN_MAIN") != "true":
            return  # Skip loading during autoreload

        if len(sys.argv) > 1 and sys.argv[1] != 'runserver':
            pass
        else:
            start = timeit.default_timer()
            self.DATA_MANAGER = DataManager()
            self.DATA_MANAGER.load_data()
            logger.info(f"Startup time: {timeit.default_timer() - start}")