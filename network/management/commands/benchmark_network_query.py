import gc
import time
import logging
from django.core.management.base import BaseCommand
from network.queries import get_whole_network_new

logger = logging.getLogger('network')


class Command(BaseCommand):
    help = "Benchmark get_whole_network_new against the parametric and nonparametric edge tables."

    def add_arguments(self, parser):
        parser.add_argument('--thresh', type=float, default=None,
                            help='p-value threshold to filter edges (default: no filter)')
        parser.add_argument('--limit', type=int, default=None,
                            help='Maximum number of edges to return (default: no limit)')
        parser.add_argument('--runs', type=int, default=3,
                            help='Number of timed runs per stat_type (default: 3)')

    def handle(self, *args, **options):
        thresh = options['thresh']
        limit = options['limit']
        runs = options['runs']

        self.stdout.write(f"Benchmark parameters: thresh={thresh}, limit={limit}, runs={runs}\n")

        for stat_type in ('parametric', 'nonparametric'):
            self.stdout.write(f"\n--- {stat_type} ---")
            times = []
            edges_count = nodes_count = 0

            candidate_links = nodes = None
            for i in range(runs):
                # Drop the previous run's ~35M-object result and collect it *before*
                # starting the timer - otherwise deallocating it happens inside the next
                # assignment below, landing inside that run's measured window instead of
                # this one's, and inflating the reported time by 20-30s for no reason
                # related to the actual query cost.
                candidate_links = None
                nodes = None
                gc.collect()

                start = time.perf_counter()
                try:
                    candidate_links, nodes = get_whole_network_new(
                        stat_type=stat_type, thresh=thresh, limit=limit
                    )
                    elapsed = time.perf_counter() - start
                    edges_count = len(candidate_links)
                    nodes_count = len(nodes)
                    times.append(elapsed)
                    self.stdout.write(f"  run {i + 1}: {elapsed:.3f}s  ({edges_count} edges, {nodes_count} nodes)")
                except Exception as e:
                    self.stdout.write(f"  run {i + 1}: FAILED — {e}")
                    break

            if times:
                avg = sum(times) / len(times)
                best = min(times)
                self.stdout.write(f"  avg: {avg:.3f}s  best: {best:.3f}s")

        self.stdout.write("\nDone.")
