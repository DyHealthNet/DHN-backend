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
        uses_autoreload = '--noreload' not in sys.argv
        logger.info("os.environ.get('RUN_MAIN') = %s", os.environ.get("RUN_MAIN"))

        # With the autoreloader active, ready() runs in an outer supervisor process (no
        # RUN_MAIN) that re-execs an inner worker process (RUN_MAIN=true) which actually
        # loads data - so the outer one should skip. But --noreload (which VS Code's Django
        # debug launch config injects automatically) never sets RUN_MAIN at all, since there's
        # no supervisor/worker split in that mode - the single process must load data itself.
        if is_runserver and uses_autoreload and os.environ.get("RUN_MAIN") != "true":
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
        # layers/group_data/group_meta are all keyed by the same node-group names; report
        # that once by name instead of once per (uninformative, always-present) dict.
        skip_keys = {'layers', 'group_data', 'group_meta'}
        for key in available_omics:
            if key in skip_keys:
                continue
            logger.info(f"Starting server with: {key}")

        node_groups = list(self.DATA_MANAGER.get_df_copy(['layers'])[0].keys())
        logger.info(f"Node groups: {', '.join(node_groups)}")
        logger.info(f"Startup time: {timeit.default_timer() - start}")
