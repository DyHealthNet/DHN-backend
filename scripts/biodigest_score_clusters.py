#!/usr/bin/env python3
"""
Scores a community-detection clustering's biological coherence via biodigest's gene/disease-set
enrichment validation (DI/SS/DBI-based, against biodigest's random-background p-values).

Must be run with the `biodigest` conda env's interpreter, not DHN-backend's own -- biodigest pins
numpy==1.24.3/scipy==1.8.0, which conflict with napypi's numpy==1.26.*/scipy==1.11.0 pins used
elsewhere in this project (see environment_biodigest.yml). Invoked as a subprocess from
network.tasks.score_clustering_wrapper; kept free of any DHN-backend/Django import so it only ever
needs the biodigest env's own dependencies.
"""
import argparse
import json
import sys

import numpy as np
import pandas as pd
from biodigest.evaluation.config import SUPPORTED_GENE_IDS, SUPPORTED_DISEASE_IDS
from biodigest.evaluation.mappers.mapper import FileMapper
from biodigest.single_validation import single_validation


def _json_default(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Series):
        return obj.to_dict()
    raise TypeError(f'Not JSON serializable: {type(obj)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True,
                        help='Pickled DataFrame with columns ["id", "cluster"] (one row per scoreable node)')
    parser.add_argument('--tar-id', required=True, choices=SUPPORTED_GENE_IDS + SUPPORTED_DISEASE_IDS,
                        help='ID scheme of the "id" column values')
    parser.add_argument('--output', required=True, help='Path to write JSON results to')
    parser.add_argument('--distance', default='jaccard', choices=['jaccard', 'overlap'])
    parser.add_argument('--runs', type=int, default=1000, help='Number of random-background runs for p-values')
    args = parser.parse_args()

    tar = pd.read_pickle(args.input)
    if 'id' not in tar.columns or 'cluster' not in tar.columns:
        print('Input DataFrame must have "id" and "cluster" columns.', file=sys.stderr)
        sys.exit(1)

    result = single_validation(
        tar=tar[['id', 'cluster']], tar_id=args.tar_id, mode='clustering',
        distance=args.distance, mapper=FileMapper(), runs=args.runs, verbose=False,
    )

    with open(args.output, 'w') as f:
        json.dump(result, f, default=_json_default)


if __name__ == '__main__':
    main()
