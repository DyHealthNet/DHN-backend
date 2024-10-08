import sys

import pandas as pd
import re
import numpy as np
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from rest_framework import generics
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from network.queries import *
from network.models import CohortVariant
from network.color_utils import *
import json
import seaborn as sns
from network.utils import check_files_and_return
import os
import environ

env = environ.Env()
environ.Env.read_env()

types = ["protein", "metabolite", "phenotype", "variant"]  # "disorders", "genes"


def join_dataframes(df1, df2=None, df3=None):
    # Start with the first DataFrame
    result = df1
    # Merge with the second DataFrame if it exists
    if df2 is not None:
        result = pd.merge(result, df2, left_index=True, right_index=True, how='inner')
    # Merge with the third DataFrame if it exists
    if df3 is not None:
        result = pd.merge(result, df3, left_index=True, right_index=True, how='inner')
    return result


# Don't try to load data if healthcheck is requested
if len(sys.argv) > 1 and sys.argv[1] == 'healthcheck':
    pass
else:
    phenotypes_filtered = check_files_and_return(env("PHENOTYPE_PATH"),
                                                 id_column=env("PATIENT_ID_COLUMN"),
                                                 return_dataset=True)
    pheno_meta_filtered = check_files_and_return(env("PHENOTYPE_META_PATH"),
                                                 id_column=env("PHENOTYPE_LABEL_COLUMN"),
                                                 column_list=[env("PHENOTYPE_TYPE_COLUMN"),
                                                              env("PHENOTYPE_DESCRIPTION_COLUMN")])

    proteins = check_files_and_return(env("PROTEIN_PATH"),
                                      id_column=env("PATIENT_ID_COLUMN"),
                                      return_dataset=True)

    proteins_meta = check_files_and_return(env("PROTEIN_META_PATH"),
                                           id_column=env("PROTEIN_LABEL_COLUMN"),
                                           column_list=[env("PROTEIN_DESCRIPTION_COLUMN")],
                                           return_dataset=True)

    metabolites = check_files_and_return(env("METABOLITE_PATH"),
                                         id_column=env("PATIENT_ID_COLUMN"),
                                         return_dataset=True)

    all_data = join_dataframes(phenotypes_filtered, proteins, metabolites)
    # If file exists open the file and load the JSON data
    # Get the mapping of values (e.g. 0:female, 1:male) for a nicer representation
    var_label_map_dict = None
    if os.path.isfile(env("VAR_LABEL_MAPPING")):
        with open(env("VAR_LABEL_MAPPING"), 'r') as file:
            var_label_map_dict = json.load(file)


# Function to extract the variable Id from the user-friendly input
# (id is either in brackets at the end or simply the input)
def extract_var_id(var):
    # This is necessary because '/ Metabolite' & '/ Protein' is artificially added to the identifiers of
    # metabolites or proteins to be more user-friendly and for an easier search
    var = var.replace(' / Metabolite', '')
    # var = var.replace(' / Protein', '') # -> not needed because id gets extracted from brackets at the end anyways
    return re.sub(r'^.*\(|\)$', '', var) if re.search(r'\(.*?\)', var) else var


# Strip xref string of db -> Not used currently
def strip_db_name(nodes_refs):
    def strip_string(s):
        return s.split('.', 1)[-1] if '.' in s else s

    if not nodes_refs:
        return ""
    # Split the input string by "|", process each part, and join them back together
    parts = nodes_refs.split('|')
    stripped_parts = [strip_string(part) for part in parts]
    return '|'.join(stripped_parts)


# Function to convert the numerical values of (most) phenotypical variables into more representative labels
# (e.g. 0:female, 1:male)
def var_label_mapping(var_id, label):
    # When no var label mapping provided return original labels
    if var_label_map_dict is None:
        return label
    if var_id not in var_label_map_dict:
        return label
    curr_var_label_dict = var_label_map_dict[var_id]
    # convert list of labels or one label using the var label mapping dictionary
    # -> when the label is not contained in the dict (e.g. for proteins, metabolites and some phenotypes)
    # the original label is returned
    if isinstance(label, list):
        return [curr_var_label_dict.get(str(la), str(la)) for la in label]
    else:
        return curr_var_label_dict.get(str(label), str(label))


def plot_variables(request):
    x = request.GET.get("x")
    y = request.GET.get("y")
    c = request.GET.get("c")

    if x is None or x == "" or y is None or y == "":
        raise ValueError('Variable x and y must be declared.')
    # equal variables will not return meaningful results and can throw an error later
    if x == y:
        raise ValueError('Variable x and y must be different')
    return x, y, c


@extend_schema_view(
    get=extend_schema(
        summary="Returns the top network edges and corresponding nodes that are connected to a query node q",
        description="""Returns for a query node q the top l (limit, default = 10) network edges and corresponding nodes 
            for each type meaning protein, metabolite, phenotype (e.g. for limit 10 -> 30 edges) in JSON format. 
            To efficiently query the correct tables the type of input node as a variable t is required. 
            (Referring to function orm_queries/network_query.)
            e.g. input: q="x0rd09",t="phenotype",limit = 10
            """,
        parameters=[
            OpenApiParameter(
                name='q',
                description='query id/ node id',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='t',
                description='query type/ node type',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='l',
                description='limit (concerning node retrieval)',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetNetworkView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars and test valid input
        query_id = request.GET.get("q")
        node_type = request.GET.get("t")
        limit = request.GET.get("l")

        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        if node_type is None or node_type not in types:
            return HttpResponseBadRequest(
                'Query type t must be declared and either protein, metabolite, phenotype and variant', status=405)
        if limit is None or limit == "":
            limit = 10
        else:
            try:
                limit = int(limit)
            except ValueError:
                return HttpResponseBadRequest(
                    f'Limit l must be a valid integer, not {limit}', status=405)

        if limit > 50:
            return HttpResponseBadRequest(
                f'Limit l takes a maximal value of 50, not {limit}', status=405)
        # retrieve chris nodes & edges + external edges using queries/network_queries function
        edges, nodes, externals = network_query(query_id, node_type, limit)
        # reformat Edges and Nodes and return as json
        result_edges = {}
        for table, results in edges.items():
            result_edges[table] = list(results)
        result_nodes = {}
        for results in nodes:
            # strip xrefs of db names -> currently not used
            # results["xrefs"] = strip_db_name(results["xrefs"])
            # group by source_table
            if results['source_table'] in result_nodes:
                result_nodes[results['source_table']].append(results)
            else:
                result_nodes[results['source_table']] = [results]

        combined_query = {
            'Nodes': result_nodes,
            'Edges': result_edges,
            'External Edges': list(externals)
        }
        return JsonResponse(combined_query, safe=False, status=200)


# TODO make this compatible for external nodes as input (use and set parameter cohort_node=False in external_query())
@extend_schema_view(
    get=extend_schema(
        summary="Returns all external edges and their nodes for a query node q",
        description="""Returns all external edges and their nodes for a query node q in JSON format. Maps external edges
            where the partner node exists as a chris node back otherwise returns external node.
            e.g. input: q="x0rd09"
            """,
        parameters=[
            OpenApiParameter(
                name='q',
                description='query id/ node id',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetAllExternalsView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request var and test valid input
        query_id = request.GET.get("q")
        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        # retrieve external edges and their chris nodes (if available) or external nodes using queries/external_query
        # function
        externals, cohort_nodes, external_nodes = external_query(query_id)
        # reformat CHRIS and External Nodes and return as json
        nodes = {}
        for results in cohort_nodes:
            for result in results:
                # Strip db name from xrefs (everything until first dot) if xrefs a key of the node -> currently not used
                # if "xrefs" in result:
                #    result["xrefs"] = strip_db_name(result["xrefs"])
                # group by source_table
                if result['source_table'] in nodes:
                    nodes[result['source_table']].append(result)
                else:
                    nodes[result['source_table']] = [result]
        external_nodes = {}
        for results in external_nodes:
            for result in results:
                if "xrefs" in result:
                    # Strip db name from xrefs (everything until first dot) if xrefs a key of the node ->
                    # currently not used
                    # result["xrefs"] = strip_db_name("|".join(result["xrefs"]))
                    result["xrefs"] = "|".join(result["xrefs"])
                # group by source_table
                if result['source_table'] in external_nodes:
                    external_nodes[result['source_table']].append(result)
                else:
                    external_nodes[result['source_table']] = [result]
        combined_query = {
            'External Edges': list(externals),
            'Chris Nodes': nodes,
            'External Nodes': external_nodes
        }
        return JsonResponse(combined_query, safe=False, status=200)


@extend_schema_view(
    get=extend_schema(
        summary="Returns node id/name recommendations depending on the input request typed by the user",
        description="""Returns a dictionary of node ids in JSON format containing a display name, description, and 
        source_table (/node_type) (as dictionary) depending on the input request typed by the user which is sent via
         (sub)string s. (Referring to function orm_queries/typeahead_query)
            """,
        parameters=[
            OpenApiParameter(
                name='s',
                description='typed query string',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class TypeaheadView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request var and test valid input
        s = request.GET.get("s")
        if s is None or s == "":
            return HttpResponseBadRequest('Query string s must be declared and non empty.', status=405)
        # retrieve recommendations using the queries/typeahead_query function
        res = typeahead_query(s)
        # reformat and return as json
        res_filtered = res.values('id', 'description', 'display_name', 'source_table')
        dict_from_queryset = {item['id']: {'display_name': item['display_name'], 'description': item['description'],
                                           'source_table': item['source_table']} for item in res_filtered}
        return JsonResponse(dict_from_queryset, safe=True)


@extend_schema_view(
    get=extend_schema(
        summary="Returns all possible phenotype variables (+ protein & metabolite variables if provided) grouped by "
                "their type",
        description='Returns all possible phenotype variables grouped by their type in JSON format. '
                    'e.g. {"nonbinaryCategorical":["Happiness on Scale 1 to 10 (happiness_scale_id)"],'
                    '"binaryCategorical":["Disease XY (diseaseXY_id)"], '
                    '"countinous":["BMI (BMI_id)","Height in cm (Height_id)"]}'
    )
)
class GetVariablesView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        def make_group(cols):
            ctype = cols['type']
            cnumcat = cols['num_cat']
            if ctype == 'integer' or ctype == 'float' or ctype == 'time':
                return 'continuous'
            elif cnumcat == 2:
                return 'binaryCategorical'
            else:
                return 'nonbinaryCategorical'

        # Get all variables with their type and a suitable identifier and put them in the same format
        # get Phenotype variables
        # get subtable of meta data for the variables that are actually in the simulated phenotypes dataset
        phenotypes_values = pd.DataFrame(pheno_meta_filtered[[(i in phenotypes_filtered.columns)
                                                              for i in pheno_meta_filtered.index]]
                                         [[env("PHENOTYPE_TYPE_COLUMN"), env("PHENOTYPE_DESCRIPTION_COLUMN")]].copy())
        # calculate the number of categories to differentiate the binary and nonbinary categorical type
        phenotypes_values.loc[:, 'num_cat'] = pd.Series(phenotypes_filtered.nunique())
        # annotate each variable with one of the types 'continuous', 'binaryCategorical' and 'nonbinaryCategorical'
        # based on the type variable in the data and the calculated number of categories
        phenotypes_values.loc[:, 'group'] = phenotypes_values.loc[:, [env("PHENOTYPE_TYPE_COLUMN"), 'num_cat']].apply(
            make_group, axis=1)
        # create identifier annotation which combines the user friendly description with the chris id in brackets
        # (if description is NaN only return the index)
        phenotypes_values.loc[:, 'identifier'] = np.where(
            phenotypes_values[env("PHENOTYPE_DESCRIPTION_COLUMN")].isna(),
            phenotypes_values.index,
            phenotypes_values.loc[:, env("PHENOTYPE_DESCRIPTION_COLUMN")] + ' (' + phenotypes_values.index + ')')
        del phenotypes_values[env("PHENOTYPE_DESCRIPTION_COLUMN")]
        del phenotypes_values['num_cat']
        del phenotypes_values[env("PHENOTYPE_TYPE_COLUMN")]
        # get Protein variables
        protein_values = None
        if not isinstance(proteins, type(None)):
            protein_values = pd.DataFrame(proteins_meta[
                                              [(i in proteins.columns) for i in
                                               proteins_meta.index]][env("PROTEIN_DESCRIPTION_COLUMN")].copy())
            # Create 'identifier' column based on conditions
            # (if description is NaN only return the index)
            protein_values['identifier'] = np.where(
                protein_values[env("PROTEIN_DESCRIPTION_COLUMN")].isna(),
                protein_values.index,
                protein_values[env("PROTEIN_DESCRIPTION_COLUMN")] + ' / Protein' + ' (' + protein_values.index + ')'
            )
            del protein_values[env("PROTEIN_DESCRIPTION_COLUMN")]
            protein_values.loc[:, 'group'] = 'continuous'

        # get Metabolite variables
        metabolite_values = None
        if not isinstance(metabolites, type(None)):
            metabolite_values = pd.DataFrame(index=metabolites.columns,
                                             data={'identifier': metabolites.columns + ' / Metabolite'})
            metabolite_values.loc[:, 'group'] = 'continuous'

        # combine all data
        existing_values = [x for x in [phenotypes_values, protein_values, metabolite_values] if
                           not isinstance(x, type(None))]
        combined_vals = pd.concat(existing_values, axis=0)
        # create output dict whit type as key and identifier as value and return it
        values_dict = combined_vals.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
        return JsonResponse(values_dict, safe=True)


@extend_schema_view(
    get=extend_schema(
        summary="Returns data statistics to be plotted in the Overview Table",
        description='Returns data statistics (of phenotype, metabolite and protein data) to be plotted in the Overview '
                    'Table in JSON format.'
                    'e.g. '
    )
)
class GetTableView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # build result dict in right format
        req_data_dict = {'Participants': len(all_data), 'Phenotypes': len(phenotypes_filtered.columns),
                         'Proteins': len(proteins.columns) if proteins is not None else 0,
                         'Metabolites': len(metabolites.columns) if metabolites is not None else 0,
                         'Genetic Variants': CohortVariant.objects.count()}
        # Get Phenotype mera file to count the different data types (currently not used in frontend table)
        df = pd.DataFrame(pheno_meta_filtered[env("PHENOTYPE_TYPE_COLUMN")][
                              [(i in phenotypes_filtered.columns) for i in
                               pheno_meta_filtered.index]].copy()).value_counts()
        req_data_dict['Phenotype-Boolean'] = int(df['boolean']) if 'boolean' in df.index else 0
        req_data_dict['Phenotype-Categorical'] = int(df['categorical']) if 'categorical' in df.index else 0
        req_data_dict['Phenotype-Float'] = int(df['float']) if 'float' in df.index else 0
        req_data_dict['Phenotype-Integer'] = int(df['integer']) if 'integer' in df.index else 0
        req_data_dict['Phenotype-Time'] = int(df['time']) if 'time' in df.index else 0
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=extend_schema(
        summary="Returns averaged data for the given variables x and y grouped by c (optional) to produce a Line Plot",
        description="""Returns averaged data for the given variables x (e.g. time) and y (e.g. dosage) in JSON format 
            to produce a Line Plot. The optional parameter c (e.g. sex) allows for comparisons between different groups 
            such as males and females.
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetDataView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars
        try:
            x, y, c = plot_variables(request)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id) or (in case of metabolites) simply the request var)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)

        if x_idx not in all_data.columns or y_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)

        if pd.api.types.is_string_dtype(all_data[y_idx]):
            return HttpResponseBadRequest(
                'y Variable is not numerical and can not be visualized in this plot.', status=405)

        df = pd.DataFrame(all_data[[x_idx, y_idx]])
        temp = []
        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the request var which is built
            # from description + (var_id) (in case of phenotypes and proteins))
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in all_data.columns:
                return HttpResponseBadRequest('Variable c, if declared, must be a valid variable of the data',
                                              status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Add var c column to subset df
            df[c_idx] = all_data[c_idx]
            # Make group by x and c var, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            # privacy restriction: only return groups with 5 or more values =! NaN
            aggregated_df_mean = (df.groupby([x_idx, c_idx]).filter(lambda x:
                                                                    x[y_idx].notna().sum() >= 5).groupby(
                [x_idx, c_idx])[y_idx].mean().reset_index().
                                  sort_values(x_idx, ascending=True))
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            colormap_local = COLOR_PALETTE
            num_colors = len(all_data[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(COLOR_PALETTE, num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in aggregated_df_mean.groupby(c_idx):
                temp.append({
                    "label": var_label_mapping(c_idx, group_name),
                    "backgroundColor": colormap_local[color],
                    "data": [{'x': var_label_mapping(x_idx, x), 'y': y} for x, y in
                             zip(group_data[x_idx], group_data[y_idx])]
                })
                color += 1
        else:
            # Make group by x and, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            # privacy restriction: only return something when there are 5 or more values =! NaN
            # (opposite is very unlikely)
            aggregated_df_mean = df.groupby(x_idx).filter(lambda x:
                                                          x[y_idx].notna().sum() >= 5).groupby(x_idx)[
                y_idx].mean().reset_index().sort_values(x_idx, ascending=True)
            # Add dict for y-axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",
                "backgroundColor": "black",
                "data": aggregated_df_mean[y_idx].tolist()
            })
        # Store unique x_var values
        req_data_dict = {
            'labels': var_label_mapping(x_idx, aggregated_df_mean[x_idx].unique().tolist()),
            'datasets': temp
        }
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=extend_schema(
        summary="Returns the count for the given variables x grouped by c (optional) to produce a Variable Count "
                "Bar Plot",
        description="""Returns averaged data for the given variables x (e.g. time) in JSON format to produce a 
            Variable Count Bar Plot. The optional parameter c (e.g. sex) allows for comparisons between different groups 
            such as males and females.
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetDataBarCountView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars
        x = request.GET.get("x")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "":
            return HttpResponseBadRequest('Variable x must be declared.', status=405)
        # Get var_id from request var (stored in brackets at the end of the request var which is built
        # from description + (var_id) (in case of phenotypes and proteins))
        x_idx = extract_var_id(x)

        if x_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data',
                                          status=405)
        temp = []

        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id) (in case of phenotypes and proteins))
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in all_data.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x:
                return HttpResponseBadRequest('Variable x and c must be different', status=405)
            # Make df subset with x, c var and a count value for each pair of group
            # TODO Group combinations where c_idx is NaN will not be returned and therefore not appear ->
            #  return 0 instead?
            df_count = all_data[[x_idx, c_idx]].groupby([x_idx, c_idx]).size().reset_index(name='counts')
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the count values with the corresponding x value
            color = 0
            colormap_local = COLOR_PALETTE
            num_colors = len(all_data[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(COLOR_PALETTE, num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name, group_data in df_count.groupby(c_idx):
                temp.append({
                    "label": var_label_mapping(c_idx, group_name),
                    "backgroundColor": colormap_local[color],
                    "data": [{'x': var_label_mapping(x_idx, x), 'y': y} for x, y in
                             zip(group_data[x_idx], group_data['counts'])]
                })
                color += 1
        # if no color var c is given only group by x var
        else:
            # Make df subset with x var and a count variable
            df_count = pd.DataFrame(all_data[x_idx]).groupby(x_idx).size().reset_index(name='counts')
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",  # TODO rather empty label?
                "backgroundColor": "black",  # TODO change default color?
                "data": df_count['counts'].tolist()
            })
        # Store unique x_var values
        req_data_dict["labels"] = var_label_mapping(x_idx, df_count[x_idx].unique().tolist())
        # Store the count data values
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=extend_schema(
        summary="Returns boxplot statistics for the given variables x and y grouped by c (optional) to produce a Box "
                "Plot",
        description="""Returns boxplot statistics for the given variables x (e.g. time) and y (e.g. dosage) in JSON 
            format to produce a Box Plot. The optional parameter c (e.g. sex) allows for comparisons between different 
            groups such as males and females.
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetDataBoxPlotView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Fill NaN values with the NaN boxplot dictionary
        nan_boxplot = {
            'min': -100,
            'q1': -100,
            'median': -100,
            'mean': -100,
            'q3': -100,
            'max': -100
        }

        try:
            x, y, c = plot_variables(request)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id) or (in case of metabolites) simply the request var)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in all_data.columns or y_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data',
                                          status=405)
        # Check if y var is a string (e.g. time variable) which would result in an error during aggregation
        # -> else throw HttpResponseBadRequest
        if pd.api.types.is_string_dtype(all_data[y_idx]):
            return HttpResponseBadRequest(
                'y Variable is not numerical and can not be visualized in this plot.', status=405)

        # helper function to calculate boxplot stats or return nan boxplot when privacy restrictions are violated
        def boxplot_stats(group):
            if group[y_idx].notna().sum() >= 5:
                return {
                    'min': group[y_idx].min(),
                    'q1': group[y_idx].quantile(0.25),
                    'median': group[y_idx].median(),
                    'mean': group[y_idx].mean(),
                    'q3': group[y_idx].quantile(0.75),
                    'max': group[y_idx].max(),
                }
            else:
                return nan_boxplot

        temp = []
        grouped = pd.DataFrame()
        # Make df subset with x and y var
        df = pd.DataFrame(all_data[[x_idx, y_idx]])
        # Check if c var is given and if so split data by it
        if c is not None and c != "":
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in all_data.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Add var c column to subset df
            df[c_idx] = all_data[c_idx]
            # Group and reformat data by calculating box plot statistics for each x_idx, c_idx group
            grouped = df.groupby([x_idx, c_idx]).apply(boxplot_stats).unstack()
            # x_idx, c_idx groups with no values are returned as NaNs and need to be converted to the nan_boxplot
            # representation
            grouped = grouped.applymap(lambda x: nan_boxplot if pd.isna(x) else x)
            # Add for each color var its own dict containing its label, a background and darker border color, some
            # styling parameters and the box plot statistics in a data dictionary.
            color = 0
            colormap_local = COLOR_PALETTE
            num_colors = len(all_data[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(COLOR_PALETTE, num_colors)
            bordercolor_map_local = [rgb_to_hex(darken_rgb(rgb)) for rgb in colormap_local]
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name in grouped.columns:
                dataset = {
                    'label': var_label_mapping(c_idx, group_name),
                    'backgroundColor': colormap_local[color],
                    'borderColor': bordercolor_map_local[color],
                    'padding': 10,
                    'itemRadius': 0,
                    'borderWidth': 1,
                    # Get stats for each group. If group has less than 5 values (excluding Nan's) only nan stats are
                    # sent for privacy protection.
                    'data': grouped[group_name].tolist(),
                }
                temp.append(dataset)
                color += 1
        # if no color var c is given only group by x var
        else:
            # Group and reformat data by calculating box plot statistics for each x_idx group
            grouped = df.groupby(x_idx).apply(boxplot_stats)
            # Make a dict containing a background and darker border color, some styling parameters and
            # the box plot statistics in a data dictionary.
            temp_style = {
                "label": "Whole Population",
                "backgroundColor": "black",
                'padding': 10,
                'itemRadius': 0,
                'borderWidth': 1,
                'data': grouped.tolist(),
            }
            temp.append(temp_style)
        # Store unique x_var values
        req_data_dict = {
            'labels': var_label_mapping(x_idx, grouped.index.tolist()),
            'datasets': temp
        }
        return JsonResponse(req_data_dict, safe=True)


@extend_schema_view(
    get=extend_schema(
        summary="Returns contingency table for the given variables x and y for plotting a Heatmap",
        description="""Returns contingency table for the given categorical variables x (e.g. sex) and y (e.g. desease 
            stage) for plotting a Heatmap in JSON format. """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetDataHeatmapView(generics.GenericAPIView):
    @staticmethod
    def get(request):
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None or y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        # Check if variables are equal because this will not return meaningful results and can throw an error later
        # -> not necessary here since it works but for consistency can be included
        # if x == y:
        #    return HttpResponseBadRequest(
        #        'Variable x and y must be different', status=405)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in all_data.columns or y_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)
        # compute contingency table
        contingency_tab = pd.crosstab(all_data[x_idx], all_data[y_idx])
        # save in dictionary and return in json format
        req_data_dict = {}
        req_data_dict["xCategories"] = var_label_mapping(x_idx, contingency_tab.index.astype(str).tolist())
        req_data_dict["yCategories"] = var_label_mapping(y_idx, contingency_tab.columns.astype(str).tolist())
        contingency_tab_inverse = np.array(contingency_tab.values)
        req_data_dict["datasets"] = contingency_tab_inverse.T.tolist()
        return JsonResponse(req_data_dict, safe=True)


# TODO assess if we want a limit for number of categories that color variable c has?
# privacy popup for line plot -> return -100 when data not avaiable due to less than 5 values being != NaN
# => currently not used and just an option to change GetDataView.
@extend_schema_view(
    get=extend_schema(
        summary="Returns averaged data for the given variables x and y grouped by c (optional)",
        description="""Returns averaged data for the given variables x (e.g. time) and y (e.g. dosage) in JSON format.
            The optional parameter c (e.g. sex) allows for comparisons between different groups such as males and females.
            """,
        parameters=[
            OpenApiParameter(
                name='x',
                description='variable x',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='y',
                description='variable y',
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name='c',
                description='colour variable',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            )
        ],
    )
)
class GetDataView2(generics.GenericAPIView):
    @staticmethod
    def get(request):
        try:
            x, y, c = plot_variables(request)
        except ValueError as ex:
            return HttpResponseBadRequest(str(ex), status=405)

        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id) or (in case of metabolites) simply the request var)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in all_data.columns or y_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)

        # def privacy_sensitive_mean(group):
        #     if group[y_idx].notna().sum() >= 5:
        #         return {'x': group[x_idx], 'y': group[y_idx].mean()}  # group[y_idx].mean()
        #     else:
        #         return {'x': group[x_idx], 'y': -100}
        def privacy_sensitive_mean(group):
            if group[y_idx].notna().sum() >= 5:
                return group[y_idx].mean()
            else:
                return -100

        temp = []
        grouped = pd.DataFrame()
        # Check if c var is given and if so split data by it
        if c is not None and c != "":
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in all_data.columns:
                return HttpResponseBadRequest('Variable c, if declared, must be a valid variable of the data',
                                              status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Group and reformat data by calculating the mean for each x_idx, c_idx group
            grouped = all_data[[x_idx, y_idx, c_idx]].groupby([x_idx, c_idx]).apply(privacy_sensitive_mean).unstack()
            # grouped = grouped.apply(lambda col: col.apply(lambda x: {'x': col.name, 'y': -100} if pd.isna(x) else x))
            # grouped = grouped.applymap(lambda x: .100 if pd.isna(x) else x)
            # x_idx, c_idx groups with no values are returned as NaNs and need to be converted to the nan representation
            # (e.g. -100)
            grouped.fillna(-100, inplace=True)
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            colormap_local = COLOR_PALETTE
            num_colors = len(all_data[c_idx].unique())
            # check if more colors are needed than available, if yes enlarge palette to required size
            if num_colors > len(colormap_local):
                colormap_local = enlarge_palette(COLOR_PALETTE, num_colors)
            colormap_local = [rgb_to_hex(rgb) for rgb in colormap_local]
            for group_name in grouped.columns:
                temp.append({
                    "label": var_label_mapping(c_idx, group_name),
                    "backgroundColor": colormap_local[color],
                    "data": grouped[group_name].tolist(),
                })
                color += 1
        # if no color var c is given only group by x var
        else:
            # Group and reformat data by calculating the mean for each x_idx  group
            grouped = all_data[[x_idx, y_idx]].groupby(x_idx).apply(privacy_sensitive_mean)
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",
                "backgroundColor": "black",
                "data": grouped.tolist()
            })
        # Store unique x_var values
        req_data_dict = {
            'labels': var_label_mapping(x_idx, grouped.index.tolist()),
            'datasets': temp
        }
        return JsonResponse(req_data_dict, safe=True)
