import pandas as pd
import re
import numpy as np
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from rest_framework import generics
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from network.queries import *
import json
import seaborn as sns

import environ
env = environ.Env()
environ.Env.read_env()

#Nodes = {'Disorders':Disorder, 'Proteins':Protein, 'Metabolites':Metabolite, 'Phenotypes': Phenotype, 'Genes':Gene}
#Edges = {'EffectsProteinProtein':EffectsProteinProtein,
#         'EffectsProteinPhenotype':EffectsProteinPhenotype,
#         'EffectsPhenotypePhenotype':EffectsPhenotypePhenotype,
#         'EffectsMetabolitePhenotype':EffectsMetabolitePhenotype,
#         'EffectsProteinMetabolite':EffectsProteinMetabolite,
#         'EffectsMetaboliteMetabolite':EffectsMetaboliteMetabolite}
types = ["protein", "metabolite", "phenotype"] # "disorders", "genes"

## TODO deal deal with time var selection
# This is wrapped in try-except to be ignored before healthcheck
try:
    # TODO check here for necessary columns in the files (change into env variables?)
    phenotypes_filtered = pd.read_csv(
                env("PHENOTYPE_PATH"),
                sep=',', header=0)
    phenotypes_meta_filtered = pd.read_csv(
                env("PHENOTYPE_META_PATH"),
                sep='\t', header=0, index_col=0, usecols=['label', 'type', 'description'])
    proteins = pd.read_csv(
                env("PROTEIN_PATH"),
                sep=',', header=0, index_col=0)
    proteins_meta = pd.read_csv(
                env("PROTEIN_META_PATH"), sep='\t', header=0, index_col=0, usecols=['protein_id','EntrezGeneSymbol'])
    metabolites = pd.read_csv(
                env("METABOLITE_PATH"),sep=',', header=0, index_col=0)
    # TODO change this when all files have the same index & indexname
    all_data = pd.concat([metabolites.reset_index(drop=True),proteins.reset_index(drop=True), phenotypes_filtered], axis=1)
    # Get the mapping of values (e.g. 0:female, 1:male) for a nicer representation
    # Open the file and load the JSON data
    with open(env("VAR_LABEL_MAPPING"), 'r') as file:
        var_label_map_dict = json.load(file)

except FileNotFoundError:
    pass

# Function to extract the variable Id from the user friendly input
# (id is either in brackets at the end or simply the input)
def extract_var_id(var):
    var = var.replace(' / Metabolite', '')
    return re.sub(r'^.*\(|\)$', '', var) if re.search(r'\(.*?\)', var) else var

# Function to convert the numerical values of (most) phenotypical variables into more representative labels
# (e.g. 0:female, 1:male)
def var_label_mapping(var_id,label):
    if var_id not in var_label_map_dict:
        return label
    curr_var_label_dict = var_label_map_dict[var_id]
    # convert list of labels or one label using the var label mapping dictionary
    # -> when the label is not contained in the dict (e.g. for proteins, metabolites and some phenotypes)
    # the original label is returned
    if isinstance(label, list):
        return [curr_var_label_dict.get(str(l), str(l)) for l in label]
    else:
        return curr_var_label_dict.get(str(label), str(label))

# functions to get appropriate background colors for plotting
def darken_hex(hex_color, factor=0.2):
    # Convert the hex color to RGB
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    # Darken the color by the factor
    r = int(r * (1 - factor))
    g = int(g * (1 - factor))
    b = int(b * (1 - factor))
    # Convert back to hex
    return f'#{r:02x}{g:02x}{b:02x}'
# functions to get appropriate colors for plotting
def rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
def darken_rgb(rgb, factor=0.2):
    darkened_rgb = [max(0, min(1, c - factor)) for c in rgb]
    return tuple(darkened_rgb)
# Colormaps for overview page plots
#colormap = ['#fff7fb','#ece7f2','#d0d1e6','#a6bddb','#74a9cf','#3690c0','#0570b0','#045a8d','#023858'][::-1]
color_palette = sns.color_palette("muted")
colormap = [rgb_to_hex(rgb) for rgb in color_palette]
bordercolor_map = [rgb_to_hex(darken_rgb(rgb)) for rgb in color_palette]

@extend_schema_view(
    get=extend_schema(
        summary="Returns the top network edges and corresponding nodes that are connected to a query node q",
        description="""Returns for a query node q the top l (limit, default = 10) network edges and corresponding nodes 
            for each type meaning protein, metabolite, phenotype (e.g. for limit 10 -> 30 edges). To efficiently query
            the correct tables the type of input node as a variable t is required. (Referring to function 
            orm_queries/network_query.)
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
    def get(self, request):
        # Get request vars
        query_id = request.GET.get("q")
        type = request.GET.get("t")
        limit = request.GET.get("l")
        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        if type is None or type not in types:
            return HttpResponseBadRequest('Query type t must be declared and either protein, metabolite and phenotype', status=405)
        if limit is None or limit == "":
            limit = 10
        else:
            try:
                limit = int(limit)
            except ValueError as e:
                return HttpResponseBadRequest(
                    f'Limit l must be a valid integer, not {limit}', status=405)

        if limit > 50:
            return HttpResponseBadRequest(
                f'Limit l takes a maximal value of 50, not {limit}', status=405)
        # retrieve chris nodes & edges + external edges using orm_queries/network_queries function
        edges, nodes, externals = network_query(query_id, type, limit)
        # reformat Edges and Nodes and return as json
        Edges = {}
        for table, results in edges.items():
            Edges[table] = list(results)
        Nodes = {}
        for results in nodes:
            # group by source_table
            if results['source_table'] in Nodes:
                Nodes[results['source_table']].append(results)
            else:
                Nodes[results['source_table']] = [results]
        combined_query = {
            'Nodes': Nodes,
            'Edges': Edges,
            'External Edges': list(externals)
        }
        return JsonResponse(combined_query, safe=False, status=200)

@extend_schema_view(
    get=extend_schema(
        summary="Returns all external edges and their nodes for a query node q",
        description="""Returns all external edges and their nodes for a query node q. Maps external edges where 
            the partner node exists as a chris node back otherwise returns external node.
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
    def get(self, request):
        # Get request vars
        query_id = request.GET.get("q")
        if query_id is None or query_id == "":
            return HttpResponseBadRequest('Query id q must be declared and non empty.', status=405)
        # retrieve chris nodes & edges + external edges using orm_queries/external_query function
        externals, cohort_nodes, external_nodes = external_query(query_id)
        # reformat CHRIS and External Nodes and return as json
        Nodes = {}
        for results in cohort_nodes:
            # group by source_table
            if results['source_table'] in Nodes:
                Nodes[results['source_table']].append(results)
            else:
                Nodes[results['source_table']] = [results]
        combined_query = {
            'External Edges': list(externals),
            'Chris Nodes': Nodes,
            'External Nodes': list(external_nodes)
        }
        return JsonResponse(combined_query, safe=False, status=200)

@extend_schema_view(
    get=extend_schema(
        summary="Returns node id/name recommendations depending on the input request typed by the user",
        description="""Returns a dictionary of node id containing a display name, description, and source_table 
            (/node_type) (as dictionary) depending on the input request typed by the user which is sent via string s. 
            (Referring to function orm_queries/typeahead_query)
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
    def get(self, request):
        # Get request vars
        s = request.GET.get("s")
        if s is None or s == "":
            return HttpResponseBadRequest('Query string s must be declared and non empty.', status=405)
        # retrieve recommendations using the orm_queries/typeahead_query function
        res = typeahead_query(s)
        # reformat and return as json
        res_filtered = res.values('id', 'description', 'display_name','source_table')
        dict_from_queryset = {item['id']: {'display_name':item['display_name'], 'description':item['description'], 'source_table':item['source_table']} for item in res_filtered}
        return JsonResponse(dict_from_queryset, safe=True)

@extend_schema_view(
    get=extend_schema(
        summary="Returns all possible phenotype variables grouped by their type in JSON format",
        description='Returns all possible phenotype variables grouped by their type in JSON format. '
                    'e.g. {"nonbinaryCategorical":["Happiness on Scale 1 to 10 (happiness_scale_id)"],'
                    '"binaryCategorical":["Disease XY (diseaseXY_id)"], '
                    '"countinous":["BMI (BMI_id)","Height in cm (Height_id)"]}'
    )
)
class GetVariablesView(generics.GenericAPIView):
    def get(self, request):
        def makeGroup(cols):
            ctype = cols['type']
            cnumcat = cols['num_cat']
            if ctype == 'integer' or ctype == 'float' or ctype == 'time':
                return 'continuous'
            elif cnumcat == 2:
                return 'binaryCategorical'
            else:
                return 'nonbinaryCategorical'
        ## get Phenotype variables
        # get subtable of meta data for the variables that are actually in the simulated phenotypes dataset
        phenotypes_values = pd.DataFrame(phenotypes_meta_filtered[
                                             [(i in phenotypes_filtered.columns) for i in
                                              phenotypes_meta_filtered.index]][['type','description']].copy())
        # calculate the number of categories to differentiate the binary and nonbinary categorical type
        phenotypes_values.loc[:,'num_cat'] = pd.Series(phenotypes_filtered.nunique())
        # annotate each variable with one of the types 'continuous', 'binaryCategorical' and 'nonbinaryCategorical'
        # based on the type variable in the data and the calculated number of categories
        phenotypes_values.loc[:,'group'] = phenotypes_values.loc[:, ['type', 'num_cat']].apply(makeGroup,axis=1)
        # create identifier annotation which combines the user friendly description with the chris id in brackets
        phenotypes_values.loc[:,'identifier'] = np.where(
            phenotypes_values['description'].isna(),
            phenotypes_values.index,
            phenotypes_values.loc[:,'description'] + ' (' + phenotypes_values.index + ')')
        del phenotypes_values['description']
        del phenotypes_values['num_cat']
        del phenotypes_values['type']
        ## get Protein variables
        protein_values = pd.DataFrame(proteins_meta[
                                          [(i in proteins.columns) for i in
                                           proteins_meta.index]]['EntrezGeneSymbol'].copy())
        # Create 'identifier' column based on conditions
        protein_values['identifier'] = np.where(
            protein_values['EntrezGeneSymbol'].isna(),
            protein_values.index,
            protein_values['EntrezGeneSymbol'] + ' / Protein' + ' (' + protein_values.index + ')'
        )
        del protein_values['EntrezGeneSymbol']
        protein_values.loc[:, 'group'] = 'continuous'
        ## get Metabolite variables
        metabolite_values = pd.DataFrame(index=metabolites.columns, data={'identifier': metabolites.columns + ' / Metabolite'})
        metabolite_values.loc[:, 'group'] = 'continuous'

        ## combine all data
        combined_vals = pd.concat([phenotypes_values,protein_values,metabolite_values],axis=0)
        #print(combined_vals)
        #combined_vals.fillna('',inplace=True)
        # create output dict and return it
        values_dict = combined_vals.groupby('group').apply(lambda dd: list(dd.identifier)).to_dict()
        return JsonResponse(values_dict, safe=True)

@extend_schema_view(
    get=extend_schema(
        summary="Returns data statistics to be plotted in the overview table",
        description='Returns data statistics (of phenotype, metabolite and protein data) to be plotted in the overview '
                    'table in JSON format.'
                    'e.g. '
    )
)
class GetTableView(generics.GenericAPIView):
    def get(self, request):
        # build result dict in right format
        req_data_dict = {}
        # TODO adapt when file not present
        req_data_dict['Participants'] = len(all_data)
        req_data_dict['Phenotypes'] = len(phenotypes_filtered.columns)
        req_data_dict['Proteins'] = len(proteins.columns)
        req_data_dict['Metabolites'] = len(metabolites.columns)
        #req_data_dict['Gene Variants'] = len(all_data)
        df = pd.DataFrame(phenotypes_meta_filtered['type'][
                                             [(i in phenotypes_filtered.columns) for i in
                                              phenotypes_meta_filtered.index]].copy()).value_counts()
        req_data_dict['Phenotype-Boolean'] = int(df['boolean']) if 'boolean' in df.index else 0
        req_data_dict['Phenotype-Categorical'] = int(df['categorical']) if 'categorical' in df.index else 0
        req_data_dict['Phenotype-Float'] = int(df['float']) if 'float' in df.index else 0
        req_data_dict['Phenotype-Integer'] = int(df['integer']) if 'integer' in df.index else 0
        req_data_dict['Phenotype-Time'] = int(df['time']) if 'time' in df.index else 0
        return JsonResponse(req_data_dict, safe=True)


# TODO assess if we want a limit for number of categories that color variable c has?
@extend_schema_view(
    get=extend_schema(
        summary="Returns averaged data for the given variables x and y grouped by c in JSON format",
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
class GetDataView(generics.GenericAPIView):
    def get(self, request):
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Variable that checks if any data can be shown based on privacy restriction (more than 5 patients/ values per group)
        show = False
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None or y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        if x == y:
            return HttpResponseBadRequest(
                'Variable x and y must be different', status=405)
        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id))
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in all_data.columns or y_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)
        if pd.api.types.is_string_dtype(all_data[y_idx]):
            return HttpResponseBadRequest(
                'y Variable is not numerical and can not be visualized in this plot.', status=405)
        # Make df subset with x and y var
        df = pd.DataFrame(all_data[[x_idx, y_idx]])
        temp = []
        # Check if c var is given and if so split data by it
        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id)
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in all_data.columns:
                return HttpResponseBadRequest('Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Add var c column to subset df
            df[c_idx] = all_data[c_idx]
            # Make group by x and c var, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            # privacy restriction: only return groups with 5 or more values =! NaN
            aggregated_df_mean = (df.groupby([x_idx, c_idx]).filter(lambda x:
                x[y_idx].notna().sum() >= 5).groupby([x_idx, c_idx])[y_idx].mean().reset_index().
                                  sort_values(x_idx, ascending=True))
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            #colormap = sns.color_palette("tab10")
            # convert colors to hexcolors for compatibility with vue-chartjs plotting
            #color_pal = [mcolors.to_hex(colormap[i]) for i in range(len(colormap))]
            for group_name, group_data in aggregated_df_mean.groupby(c_idx):
                temp.append({
                    "label": var_label_mapping(c_idx,group_name),
                    "backgroundColor": colormap[color],
                    "data": [{'x': var_label_mapping(x_idx,x), 'y': y} for x, y in zip(group_data[x_idx], group_data[y_idx])]
                })
                color += 1
        # if no color var c is given simply return all data in one group
        else:
            # Make group by x and, aggregate over y using mean (+sort by x var for sorted x-axis in plot)
            # privacy restriction: only return something when there are 5 or more values =! NaN (opposite is very unlikely) # TODO cover and test this corner case (show var?)
            aggregated_df_mean = df.groupby(x_idx).filter(lambda x:
                 x[y_idx].notna().sum() >= 5).groupby(x_idx)[y_idx].mean().reset_index().sort_values(x_idx, ascending=True)
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",  #TODO rather empty label?
                "backgroundColor": "black",   #TODO change default color?
                "data": aggregated_df_mean[y_idx].tolist()
            })
        # Store unique x_var values
        req_data_dict["labels"] = var_label_mapping(x_idx,aggregated_df_mean[x_idx].unique().tolist())
        # Store the y dict/ dicts (if color var was given)
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)

@extend_schema_view(
    get=extend_schema(
        summary="Returns the count for the given variables x grouped by c in JSON format",
        description="""Returns averaged data for the given variables x (e.g. time) in JSON format.
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
    def get(self, request):
        # Get request vars
        x = request.GET.get("x")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Variable that checks if any data can be shown based on privacy restriction (more than 5 patients/ values per group)
        show = False
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "":
            return HttpResponseBadRequest('Variable x must be declared.', status=405)
        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id))
        x_idx = extract_var_id(x)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x must be a valid variable of the data',
                                          status=405)
        temp = []
        # Check if c var is given and if so split data by it
        if c is not None and c != "":
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id)
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in all_data.columns:
                return HttpResponseBadRequest(
                    'Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x:
                return HttpResponseBadRequest('Variable x and c must be different', status=405)
            # Make df subset with x, c var and a count value for each pair of group
            # TODO ! Group combinations where c_idx is NaN will not be returned -> return 0?
            df_count = all_data[[x_idx, c_idx]].groupby([x_idx, c_idx]).size().reset_index(name='counts')
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            for group_name, group_data in df_count.groupby(c_idx):
                temp.append({
                    "label": var_label_mapping(c_idx,group_name),
                    "backgroundColor": colormap[color],
                    "data": [{'x': var_label_mapping(x_idx,x), 'y': y} for x, y in zip(group_data[x_idx], group_data['counts'])]
                })
                color += 1
        # if no color var c is given simply return all data in one group
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
        req_data_dict["labels"] = var_label_mapping(x_idx,df_count[x_idx].unique().tolist())
        # Store the y dict/ dicts (if color var was given)
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)

@extend_schema_view(
    get=extend_schema(
        summary="Returns boxplot data for the given variables x and y grouped by c in JSON format",
        description="""Returns boxplot data for the given variables x (e.g. time) and y (e.g. dosage) in JSON format.
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
class GetDataBoxPlotView(generics.GenericAPIView):
    def get(self, request):
        # Fill NaN values with the NaN boxplot dictionary
        nan_boxplot = {
            'min': -100,
            'q1': -100,
            'median': -100,
            'mean': -100,
            'q3': -100,
            'max': -100
        }
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None or y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        # Check if variables are equal because this will not return meaningful results and can throw an error later
        if x == y:
            return HttpResponseBadRequest('Variable x and y must be different.', status=405)
        # Get var_id from request vars (stored in brackets at the end of the requents var which is built
        # from description + (var_id)
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in all_data.columns or y_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data',
                                          status=405)
        if pd.api.types.is_string_dtype(all_data[y_idx]):
            return HttpResponseBadRequest(
                'y Variable is not numerical and can not be visualized in this plot.', status=405)
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
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id)
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
            # Make df subset with x, y and c var
            grouped = df.groupby([x_idx, c_idx]).apply(boxplot_stats).unstack()
            grouped = grouped.applymap(lambda x: nan_boxplot if pd.isna(x) else x)
            # Add for each color var its own dict containing its label, a background and darker border color, some
            # styling parameters and the box plot statistics in a data dictionary.
            color = 0
            #colormap = sns.color_palette("tab10")
            # convert colors to hexcolors for compatibility with vue-chartjs plotting
            #color_pal = [mcolors.to_hex(colormap[i]) for i in range(len(colormap))]
            #bordercolor_pal = [mcolors.to_hex(darken_rgb(colormap[i])) for i in range(len(colormap))]
            for group_name in grouped.columns:
                dataset = {
                    'label': var_label_mapping(c_idx,group_name),
                    'backgroundColor': colormap[color],
                    'borderColor': bordercolor_map[color],
                    'padding': 10,
                    'itemRadius': 0,
                    'borderWidth': 1,
                    # Get stats for each group. If group has less than 5 values (excluding Nan's) only nan stats are
                    # sent for privacy protection.
                    'data': grouped[group_name].tolist(),
                }
                temp.append(dataset)
                print(f'group {group_name}: {len(grouped[group_name].tolist())}')
                color += 1
            # if no color var c is only group by x var
        else:
            # Make df subset with x and y var
            grouped = df.groupby(x_idx).apply(boxplot_stats)
            # Make a dict containing a background and darker border color, some styling parameters and
            # the box plot statistics in a data dictionary.
            temp_style = {
            "label": "Whole Population",  # TODO rather empty label?
            "backgroundColor": "black",  # TODO change default color?
            'padding': 10,
            'itemRadius': 0,
            'borderWidth': 1,
            'data': grouped.tolist(),
            }
            print(f'group without c: {len(grouped.tolist())}')
            temp.append(temp_style)
        # Store unique x_var values
        req_data_dict["labels"] = var_label_mapping(x_idx,grouped.index.tolist())
        print(f'labels: {len(req_data_dict["labels"])}')
        # Store the y dict/ dicts (if color var was given)
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)

@extend_schema_view(
    get=extend_schema(
        summary="Returns contingency table for the given variables x and y for plotting a heatmap in JSON format",
        description="""Returns contingency table for the given categorical variables x (e.g. sex) and y (e.g. desease 
            stage) for plotting a heatmap in JSON format. """,
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
    def get(self, request):
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")

        # Variable that checks if any data can be shown based on privacy restriction (more than 5 patients/ values per group)
        show = False
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None or y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        # Check if variables are equal because this will not return meaningful results and can throw an error later
        # -> not necessary here since it works but for consistency can be included
        #if x == y:
        #    return HttpResponseBadRequest(
        #        'Variable x and y must be different', status=405)
        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id))
        x_idx = extract_var_id(x)
        y_idx = extract_var_id(y)
        # Check if x and y var are present in our data -> else throw HttpResponseBadRequest
        if x_idx not in all_data.columns or y_idx not in all_data.columns:
            return HttpResponseBadRequest('Variable x and y must be a valid variable of the data', status=405)
        # compute contingency table
        contingency_tab = pd.crosstab(all_data[x_idx], all_data[y_idx])
        # save in dictionary and return in json format
        req_data_dict = {}
        req_data_dict["xCategories"] = var_label_mapping(x_idx,contingency_tab.index.astype(str).tolist())
        req_data_dict["yCategories"] = var_label_mapping(y_idx,contingency_tab.columns.astype(str).tolist())
        contingency_tab_inverse = np.array(contingency_tab.values)
        req_data_dict["datasets"] = contingency_tab_inverse.T.tolist()
        return JsonResponse(req_data_dict, safe=True)



# privacy popup for line plot -> return -100 when data not avaiable because there are only 0-4 values != NaN

# TODO assess if we want a limit for number of categories that color variable c has?
@extend_schema_view(
    get=extend_schema(
        summary="Returns averaged data for the given variables x and y grouped by c in JSON format",
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
    def get(self, request):
        # Get request vars
        x = request.GET.get("x")
        y = request.GET.get("y")
        c = request.GET.get("c")

        # build result dict in right format
        req_data_dict = {}
        # Variable that checks if any data can be shown based on privacy restriction (more than 5 patients/ values per group)
        show = False
        # Check if x and y var are given -> else throw HttpResponseBadRequest
        if x is None or x == "" or y is None or y == "":
            return HttpResponseBadRequest('Variable x and y must be declared.', status=405)
        if x == y:
            return HttpResponseBadRequest(
                'Variable x and y must be different', status=405)
        # Get var_id from request vars (stored in brackets at the end of the requests var which is built
        # from description + (var_id))
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
            # Get var_id from request var (stored in brackets at the end of the requents var which is built
            # from description + (var_id)
            c_idx = extract_var_id(c)
            # Check if c var is present in our data -> else throw HttpResponseBadRequest
            if c_idx not in all_data.columns:
                return HttpResponseBadRequest('Variable c, if declared, must be a valid variable of the data', status=405)
            # Check if variables are equal because this will not return meaningful results and can throw an error later
            if c == x or c == y:
                return HttpResponseBadRequest(
                    'Variable x and y must be different from c', status=405)
            # Make df subset with x, y and c var
            grouped = all_data[[x_idx, y_idx, c_idx]].groupby([x_idx, c_idx]).apply(privacy_sensitive_mean).unstack()
            #grouped = grouped.apply(lambda col: col.apply(lambda x: {'x': col.name, 'y': -100} if pd.isna(x) else x))
            #grouped = grouped.applymap(lambda x: .100 if pd.isna(x) else x)
            grouped.fillna(-100, inplace=True)
            # Add for each color var its own dict containing its label, a color from the color palette and a dict that
            # associates the aggregated values with the corresponding x value (this way we do not have to create NaN
            # values for x positions with no aggregated value present)
            color = 0
            #colormap = sns.color_palette("tab10")
            # convert colors to hexcolors for compatibility with vue-chartjs plotting
            #color_pal = [mcolors.to_hex(colormap[i]) for i in range(len(colormap))]
            for group_name in grouped.columns:
                temp.append({
                    "label": var_label_mapping(c_idx,group_name),
                    "backgroundColor": colormap[color],
                    "data": grouped[group_name].tolist(),
                })
                color += 1
        # if no color var c is given simply return all data in one group
        else:
            # Make df subset with x and y var
            grouped = all_data[[x_idx, y_idx]].groupby(x_idx).apply(privacy_sensitive_mean)
            # Add dict for y axis containing the y label, black as the color and the aggregated values
            temp.append({
                "label": "Whole Population",  #TODO rather empty label?
                "backgroundColor": "black",   #TODO change default color?
                "data": grouped.tolist()
            })
        # Store unique x_var values
        req_data_dict["labels"] = var_label_mapping(x_idx,grouped.index.tolist())
        # Store the y dict/ dicts (if color var was given)
        req_data_dict["datasets"] = temp
        return JsonResponse(req_data_dict, safe=True)
