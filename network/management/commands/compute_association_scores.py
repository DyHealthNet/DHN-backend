import time

from django.core.management.base import BaseCommand
import sys
from network.utils.data_manager import combine_data
from modina.context_net_inference import compute_context_scores
import environ
import traceback
import logging

# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env(
    NUMBER_OF_WORKERS=(int, 16)
)
environ.Env.read_env()

logger = logging.getLogger("network")


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            logger.info("Starting association score testing.")
            #self.check_score_files()
            self.compute_association_scores()
            logger.info(f'Finished association score testing successfully. '
                        f'The results were saved in {env("CALCULATED_EDGES_PATH")}')
        except Exception as e:
            # print stack trace
            traceback.print_exc()
            logger.error(f"Association score testing failed: {e}")
            sys.exit(1)

    @staticmethod
    def compute_association_scores():
        start = time.perf_counter()

        network_data, network_meta_data = combine_data(env)
        logger.info(f"Loaded and combined input data in {time.perf_counter() - start:.2f}s.")

        logger.debug(f"Using {env('NUMBER_OF_WORKERS')} workers for the calculation.")

        edges_dir = env("CALCULATED_EDGES_PATH")
        correction = env("MULTIPLE_TESTING")
        if correction not in ('bh', 'by'):
            raise ValueError(f"MULTIPLE_TESTING must be 'bh' or 'by', got {correction!r}.")

        parametric_start = time.perf_counter()
        compute_context_scores(context_data=network_data, meta_file=network_meta_data, test_type="parametric",
                        correction=correction, num_workers=env.int("NUMBER_OF_WORKERS"),
            path=edges_dir, nan_value=env.int("NAN_VALUE"),
            name=env("OBSERVATION_SOURCE")+"_"+"parametric")
        logger.info(f"Computed parametric association scores in {time.perf_counter() - parametric_start:.2f}s.")

        nonparametric_start = time.perf_counter()
        compute_context_scores(context_data=network_data, meta_file=network_meta_data, test_type="nonparametric",
                        correction=correction, num_workers=env.int("NUMBER_OF_WORKERS"),
            path=edges_dir, nan_value=env.int("NAN_VALUE"),
            name=env("OBSERVATION_SOURCE")+"_"+"nonparametric")
        logger.info(f"Computed nonparametric association scores in {time.perf_counter() - nonparametric_start:.2f}s.")

        logger.info(f"Finished compute_association_scores in {time.perf_counter() - start:.2f}s total.")
