from django.core.management.base import BaseCommand
from django.core.cache import cache
import sys
import environ
import traceback
import logging

# Build paths inside the project like this: BASE_DIR / 'subdir'.
env = environ.Env()
environ.Env.read_env()

logger = logging.getLogger('network')


class Command(BaseCommand):
    def handle(self, *args, **options):
        try:
            logger.info("Clearing cache")
            self._clear_all()

        except Exception as e:
            logger.error(f"Clearing cache failed: {e}")
            traceback.print_exc()
            sys.exit(1)

    @staticmethod
    def _clear_all():
        cache.clear()
        logger.info("Cache cleared")
