from __future__ import annotations

import argparse
import re
from io import StringIO
from pathlib import Path

import matplotlib
from matplotlib import colors as mcolors

matplotlib.use('Agg')

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


METRIC_ORDER = ('RI', 'ARI', 'NMI')
METHOD_PLOT_ORDER = ('louvain', 'leiden', 'recursive_leiden', 'agglomerative', 'infomap', 'hierarchical_infomap', 'hsbm')
HIERARCHICAL_FAMILIES = {'recursive_leiden', 'hierarchical_infomap', 'agglomerative', 'hsbm'}
METHOD_GROUP_LABELS = {
	'louvain': 'density / modularity-based',
	'leiden': 'density / modularity-based',
	'recursive_leiden': 'density / modularity-based',
	'agglomerative': 'density / modularity-based',
	'infomap': 'flow-based',
	'hierarchical_infomap': 'flow-based',
	'hsbm': 'probabilistic',
}
FLAT_LABEL_COLOR = '#d63384'
HIERARCHICAL_LABEL_COLOR = "#1FB6E8"


def _read_sectioned_csv(csv_path: Path) -> tuple[dict[str, str], pd.DataFrame]:
	lines = csv_path.read_text(encoding='utf-8').splitlines()
	if not lines:
		return {}, pd.DataFrame()

	try:
		blank_index = next(index for index, line in enumerate(lines) if not line.strip())
	except StopIteration:
		blank_index = -1

	metadata: dict[str, str] = {}
	data_frame = pd.DataFrame()

	if blank_index == -1:
		data_frame = pd.read_csv(StringIO('\n'.join(lines)))
		return metadata, data_frame

	metadata_block = '\n'.join(lines[:blank_index]).strip()
	if metadata_block:
		metadata_frame = pd.read_csv(StringIO(metadata_block))
		if not metadata_frame.empty and {'metric', 'value'}.issubset(metadata_frame.columns):
			for metric, value in metadata_frame[['metric', 'value']].fillna('').itertuples(index=False):
				metadata[str(metric)] = str(value)

	data_block = '\n'.join(lines[blank_index + 1:]).strip()
	if data_block:
		data_frame = pd.read_csv(StringIO(data_block))

	return metadata, data_frame


def _infer_pairwise_csv_path(benchmark_csv: Path) -> Path:
	match = re.search(r'benchmarking_cm_detection_(\d{8}_\d{6})\.csv$', benchmark_csv.name)
	if not match:
		raise ValueError(
			f'Could not infer the pairwise CSV name from {benchmark_csv.name}. '
			'Pass --pairwise-csv explicitly.'
		)

	inferred = benchmark_csv.with_name(f'benchmarking_cm_detection_pairwise_{match.group(1)}.csv')
	if not inferred.exists():
		raise FileNotFoundError(f'Pairwise CSV not found: {inferred}')

	return inferred


def _family_name(method_name: str) -> str:
	method_name = (method_name or '').strip().lower()
	if method_name.startswith('hsbm_level_'):
		return 'hsbm'
	if method_name.startswith('agglomerative_cut_'):
		return 'agglomerative'
	if method_name.startswith('recursive_leiden_level_'):
		return 'recursive_leiden'
	if method_name.startswith('hierarchical_infomap_level_'):
		return 'hierarchical_infomap'
	return method_name


def _display_name(method_name: str) -> str:
	family = _family_name(method_name)
	if family == method_name:
		return method_name
	return f'{family} (best modularity)'


def _plot_method_label(method_name: str) -> str:
	return _family_name(method_name)


def _group_label(method_name: str) -> str:
	family = _family_name(method_name)
	return METHOD_GROUP_LABELS.get(family, family)


def _method_plot_order(method_name: str) -> tuple[int, str]:
	family = _family_name(method_name)
	try:
		return METHOD_PLOT_ORDER.index(family), family
	except ValueError:
		return len(METHOD_PLOT_ORDER), family


def _select_best_method_rows(method_df: pd.DataFrame) -> pd.DataFrame:
	if method_df.empty:
		return method_df.copy()

	temp = method_df.copy()
	temp['family'] = temp['method'].map(_family_name)

	selected_rows = []
	for _, group in temp.groupby('family', sort=False):
		best_idx = group['modularity'].astype(float).idxmax()
		selected_rows.append(temp.loc[best_idx])

	return pd.DataFrame(selected_rows).reset_index(drop=True)


def _benchmark_title(metadata: dict[str, str]) -> str:
	parts = [
		f"threshold={metadata.get('threshold', '')}",
		f"limit={metadata.get('limit', '')}",
		f"per_node_limit={metadata.get('per_node_limit', '')}",
		f"nodes={metadata.get('selected_node_count', '')}",
		f"edges={metadata.get('selected_edge_count', '')}",
		f"density={metadata.get('network_density', '')}",
	]
	return 'Benchmark summary | ' + ' | '.join(parts)


def _annotate_heatmap(ax: plt.Axes, matrix: pd.DataFrame) -> None:
	for row_index, row_label in enumerate(matrix.index):
		for col_index, col_label in enumerate(matrix.columns):
			value = matrix.loc[row_label, col_label]
			ax.text(
				col_index,
				row_index,
				f'{float(value):.3f}',
				ha='center',
				va='center',
				fontsize=8,
				color='white' if value < 0.55 else 'black',
			)


def plot_pairwise_heatmap(pairwise_csv: Path, output_path: Path, title: str, dpi: int = 200) -> Path:
	_, pairwise_df = _read_sectioned_csv(pairwise_csv)
	if pairwise_df.empty:
		raise ValueError(f'No pairwise comparison rows found in {pairwise_csv}')

	if 'comparison' not in pairwise_df.columns:
		raise ValueError(f'The pairwise CSV does not contain a comparison column: {pairwise_csv}')

	method_columns = [column for column in pairwise_df.columns if column != 'comparison']
	metric_matrices: list[tuple[str, pd.DataFrame]] = []
	for metric in METRIC_ORDER:
		metric_rows = pairwise_df[pairwise_df['comparison'].astype(str).str.startswith(f'{metric} ')]
		if metric_rows.empty:
			continue

		row_labels = metric_rows['comparison'].astype(str).str[len(metric) + 1:]
		matrix = metric_rows.loc[:, method_columns].copy()
		matrix.index = row_labels
		matrix = matrix.astype(float)
		metric_matrices.append((metric, matrix))

	if not metric_matrices:
		raise ValueError(f'Could not extract RI/ARI/NMI matrices from {pairwise_csv}')

	figure, axes = plt.subplots(
		nrows=1,
		ncols=len(metric_matrices),
		figsize=(5.5 * len(metric_matrices), 5.0),
		constrained_layout=True,
	)
	if len(metric_matrices) == 1:
		axes = [axes]

	# Use a simple two-color gradient so similarity is easier to interpret.
	norm = mcolors.Normalize(vmin=0.0, vmax=1.0)
	cmap = mcolors.LinearSegmentedColormap.from_list('similarity_two_tone', ['#f7fbff', '#084081'])

	for axis, (metric_name, matrix) in zip(axes, metric_matrices):
		image = axis.imshow(matrix.values, norm=norm, cmap=cmap, aspect='auto')
		axis.set_title(metric_name)
		axis.set_xticks(range(len(matrix.columns)))
		axis.set_xticklabels(matrix.columns, rotation=45, ha='right')
		axis.set_yticks(range(len(matrix.index)))
		axis.set_yticklabels(matrix.index)
		axis.tick_params(axis='both', labelsize=8)
		_annotate_heatmap(axis, matrix)
		figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04, ticks=[0.0, 0.5, 0.8, 0.9, 1.0])

	figure.suptitle(title, fontsize=12)
	figure.savefig(output_path, dpi=dpi, bbox_inches='tight')
	plt.close(figure)
	return output_path


def plot_modularity_conductance(method_csv: Path, output_path: Path, title: str, dpi: int = 200) -> Path:
	_, method_df = _read_sectioned_csv(method_csv)
	if method_df.empty:
		raise ValueError(f'No benchmark rows found in {method_csv}')

	required_columns = {'method', 'modularity', 'conductance'}
	if not required_columns.issubset(method_df.columns):
		raise ValueError(f'Missing required columns in benchmark CSV: {required_columns}')

	best_rows = _select_best_method_rows(method_df)
	if best_rows.empty:
		raise ValueError(f'No rows found for plotting in {method_csv}')

	best_rows = best_rows.copy()
	best_rows['_plot_order'] = best_rows['method'].map(lambda method: _method_plot_order(str(method))[:1][0])
	best_rows['_plot_family'] = best_rows['method'].map(lambda method: _family_name(str(method)))
	best_rows = best_rows.sort_values(['_plot_order', '_plot_family'], kind='stable').reset_index(drop=True)

	labels = [
		_plot_method_label(str(row['method']))
		for _, row in best_rows.iterrows()
	]
	modularity = best_rows['modularity'].astype(float).tolist()
	conductance = best_rows['conductance'].astype(float).tolist()
	families = [
		_family_name(str(row['method']))
		for _, row in best_rows.iterrows()
	]
	is_hierarchical = [fam in HIERARCHICAL_FAMILIES for fam in families]

	x_positions = np.arange(len(labels))
	width = 0.36

	figure, axis = plt.subplots(figsize=(max(10, len(labels) * 1.25), 6.4), constrained_layout=False)
	bars_modularity = axis.bar(x_positions - width / 2, modularity, width, label='Modularity', color='#2a9d8f')
	bars_conductance = axis.bar(x_positions + width / 2, conductance, width, label='Conductance', color='#e76f51')

	axis.set_xticks(x_positions)
	axis.set_xticklabels(labels, rotation=30, ha='right')
	for label_obj, hierarchical in zip(axis.get_xticklabels(), is_hierarchical):
		label_obj.set_color(HIERARCHICAL_LABEL_COLOR if hierarchical else FLAT_LABEL_COLOR)
	axis.set_ylabel('Score')
	axis.set_ylim(0.0, 1.05)
	axis.set_title(title)
	axis.grid(axis='y', alpha=0.25)
	axis.legend(loc='upper right')

	for bar_group in (bars_modularity, bars_conductance):
		for bar in bar_group:
			height = bar.get_height()
			axis.text(
				bar.get_x() + bar.get_width() / 2,
				height + 0.015,
				f'{height:.3f}',
				ha='center',
				va='bottom',
				fontsize=8,
			)

	# Draw grouping brackets below the labels for each contiguous method-type segment.
	group_labels = [_group_label(str(row['method'])) for _, row in best_rows.iterrows()]
	ranges = []
	if group_labels:
		start = 0
		cur = group_labels[0]
		for i, group_label in enumerate(group_labels[1:], start=1):
			if group_label != cur:
				ranges.append((cur, start, i - 1))
				start = i
				cur = group_label
		ranges.append((cur, start, len(group_labels) - 1))

	bracket_y = -0.22
	label_y = -0.34
	for group_label, s, e in ranges:
		x0 = x_positions[s] - width * 0.95
		x1 = x_positions[e] + width * 0.95
		axis.plot([x0, x1], [bracket_y, bracket_y], transform=axis.get_xaxis_transform(), color='black', linewidth=1, clip_on=False)
		axis.plot([x0, x0], [bracket_y - 0.03, bracket_y + 0.03], transform=axis.get_xaxis_transform(), color='black', linewidth=1, clip_on=False)
		axis.plot([x1, x1], [bracket_y - 0.03, bracket_y + 0.03], transform=axis.get_xaxis_transform(), color='black', linewidth=1, clip_on=False)
		axis.text(
			(x0 + x1) / 2,
			label_y,
			group_label,
			transform=axis.get_xaxis_transform(),
			ha='center',
			va='top',
			fontsize=8,
			fontstyle='italic',
			clip_on=False,
		)

	figure.subplots_adjust(bottom=0.34)

	figure.savefig(output_path, dpi=dpi, bbox_inches='tight')
	plt.close(figure)
	return output_path


def plot_runtime_per_method(method_csv: Path, output_path: Path, title: str, dpi: int = 200) -> Path:
	_, method_df = _read_sectioned_csv(method_csv)
	if method_df.empty:
		raise ValueError(f'No benchmark rows found in {method_csv}')

	required_columns = {'method', 'runtime_seconds'}
	if not required_columns.issubset(method_df.columns):
		raise ValueError(f'Missing required columns in benchmark CSV: {required_columns}')

	best_rows = _select_best_method_rows(method_df)
	if best_rows.empty:
		raise ValueError(f'No rows found for plotting in {method_csv}')

	labels = [
		_plot_method_label(str(row['method']))
		for _, row in best_rows.iterrows()
	]
	order_keys = [
		_method_plot_order(str(row['method']))[0]
		for _, row in best_rows.iterrows()
	]
	best_rows = best_rows.assign(_plot_order=order_keys).sort_values(['_plot_order'], kind='stable').reset_index(drop=True)
	labels = [
		_plot_method_label(str(row['method']))
		for _, row in best_rows.iterrows()
	]
	runtimes = best_rows['runtime_seconds'].astype(float).tolist()
	x_positions = np.arange(len(labels))

	figure, axis = plt.subplots(figsize=(max(10, len(labels) * 1.2), 5.5), constrained_layout=True)
	bars = axis.bar(x_positions, runtimes, color='#457b9d')
	axis.set_xticks(x_positions)
	axis.set_xticklabels(labels, rotation=30, ha='right')
	axis.set_ylabel('Runtime (seconds)')
	axis.set_title(title)
	axis.grid(axis='y', alpha=0.25)

	for bar in bars:
		height = bar.get_height()
		axis.text(
			bar.get_x() + bar.get_width() / 2,
			height + max(0.01, height * 0.02),
			f'{height:.3f}',
			ha='center',
			va='bottom',
			fontsize=8,
		)

	figure.savefig(output_path, dpi=dpi, bbox_inches='tight')
	plt.close(figure)
	return output_path


def generate_plots(benchmark_csv: Path, pairwise_csv: Path | None = None, output_dir: Path | None = None, dpi: int = 200) -> tuple[Path, Path, Path]:
	benchmark_csv = benchmark_csv.resolve()
	timestamp_match = re.search(r'(\d{8}_\d{6})', benchmark_csv.name)
	timestamp = timestamp_match.group(1) if timestamp_match else 'unknown'
	default_output_dir = benchmark_csv.parent / 'plots' / timestamp
	output_dir = (output_dir or default_output_dir).resolve()
	output_dir.mkdir(parents=True, exist_ok=True)

	metadata, _ = _read_sectioned_csv(benchmark_csv)
	if pairwise_csv is None:
		pairwise_csv = _infer_pairwise_csv_path(benchmark_csv)
	else:
		pairwise_csv = pairwise_csv.resolve()

	heatmap_path = output_dir / f'benchmarking_cm_detection_pairwise_heatmap_{timestamp}.png'
	metrics_path = output_dir / f'benchmarking_cm_detection_metrics_{timestamp}.png'
	runtime_path = output_dir / f'benchmarking_cm_detection_runtime_{timestamp}.png'

	title = _benchmark_title(metadata)
	plot_pairwise_heatmap(pairwise_csv, heatmap_path, title=title, dpi=dpi)
	plot_modularity_conductance(benchmark_csv, metrics_path, title=title, dpi=dpi)
	plot_runtime_per_method(benchmark_csv, runtime_path, title=title, dpi=dpi)

	return heatmap_path, metrics_path, runtime_path


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description='Plot benchmark community-detection results as a pairwise heatmap, modularity/conductance chart, and runtime chart.'
	)
	parser.add_argument('--benchmark-csv', required=True, type=Path, help='Path to benchmarking_cm_detection_*.csv')
	parser.add_argument('--pairwise-csv', type=Path, help='Path to benchmarking_cm_detection_pairwise_*.csv')
	parser.add_argument('--output-dir', type=Path, help='Directory for the generated plots. Defaults to the benchmark CSV folder.')
	parser.add_argument('--dpi', type=int, default=200, help='Output DPI for the saved figures.')
	return parser


def main() -> None:
	parser = build_parser()
	args = parser.parse_args()

	heatmap_path, metrics_path, runtime_path = generate_plots(
		benchmark_csv=args.benchmark_csv,
		pairwise_csv=args.pairwise_csv,
		output_dir=args.output_dir,
		dpi=args.dpi,
	)

	print(f'Pairwise heatmap written to: {heatmap_path}')
	print(f'Modularity/conductance plot written to: {metrics_path}')
	print(f'Runtime plot written to: {runtime_path}')


if __name__ == '__main__':
	main()
