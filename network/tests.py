from django.test import TestCase
import pandas as pd
from network.utils import (
    multiprocess,
    cat_cat,
    cat_cont,
    cont_cont,
    calculate_association_scores,
    check_files
)
from django.test import SimpleTestCase
from django.urls import reverse, resolve
from network.views import *


class ParallelProcessingTestCase(TestCase):
    # Check if simple computation produces the correct result
    def test_multiprocess(self):
        items = [1, 2, 3]
        num_workers = 2
        function_call = lambda x: x + 1
        result = multiprocess(items, num_workers, function_call)
        self.assertEqual(result, [2, 3, 4])


class AssociationScoresTestCase(TestCase):

    def test_cat_cat(self):
        # Case 1: One of the phenotypes has only one possible value and no test is perfomed
        phenotypes_cat = pd.DataFrame({
            'pheno1': ['high', 'high', 'high', 'high'],
            'pheno2': ['large', 'small', 'large', 'small']})
        pair_cat_cat = ('pheno1', 'pheno2')
        result = cat_cat(pair_cat_cat, phenotypes_cat)

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertEqual(result['pval'], 1)
        self.assertEqual(result['effsize'], 0)
        self.assertEqual(result['effsize_type'], None)
        self.assertEqual(result['test'], None)

        # Case 2: Both phenotypes have at least two categories and a Chi-squared test is performed
        phenotypes_cat = pd.DataFrame({
            'pheno1': ['high', 'high', 'low', 'low'],
            'pheno2': ['large', 'small', 'large', 'small']})
        pair_cat_cat = ('pheno1', 'pheno2')
        result = cat_cat(pair_cat_cat, phenotypes_cat)

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertEqual(result['effsize_type'], 'Cramer´s v')
        self.assertEqual(result['test'], 'Chi-squared test')

    def test_cat_cont(self):
        # Case 1: The categorical variable has only one possible value and no test is performed
        phenotypes_cat = pd.DataFrame({
            'pheno1': ['high', 'high', 'high', 'high']})
        phenotypes_cont = pd.DataFrame({
            'pheno2': [1.0, 2.0, 3.0, 4.0]})
        pair_cat_cont = (0, 0)  # Indices instead of labels
        result = cat_cont(pair_cat_cont, phenotypes_cat, phenotypes_cont, test='parametric')

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertEqual(result['pval'], 1)
        self.assertEqual(result['effsize'], 0)
        self.assertEqual(result['effsize_type'], None)
        self.assertEqual(result['test'], None)

        # Case 2: The categorical variable has exactly two categories and a parametric t-test is performed
        phenotypes_cat = pd.DataFrame({
            'pheno1': ['high', 'high', 'low', 'low']})
        result = cat_cont(pair_cat_cont, phenotypes_cat, phenotypes_cont, test='parametric')

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertEqual(result['effsize_type'], "Cohen's d")
        self.assertEqual(result['test'], 't-test')

        # Case 3: The categorical variable has exactly two categories and a non-parametric Mann–Whitney U test is performed
        result = cat_cont(pair_cat_cont, phenotypes_cat, phenotypes_cont, test='non-parametric')

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertEqual(result['effsize_type'], "Cohen's d")
        self.assertEqual(result['test'], 'Mann–Whitney U test')

        # Case 4: The categorical variable has more than two categories and a parametric one-way ANOVA test is performed
        phenotypes_cat = pd.DataFrame({
            'pheno1': ['high', 'intermediate', 'low', 'low']})
        result = cat_cont(pair_cat_cont, phenotypes_cat, phenotypes_cont, test='parametric')

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertEqual(result['effsize_type'], "eta squared")
        self.assertEqual(result['test'], 'one-way ANOVA test')

        # Case 5: The categorical variable has more than two categories and a non-parametric Kruskal–Wallis test is performed
        result = cat_cont(pair_cat_cont, phenotypes_cat, phenotypes_cont, test='non-parametric')

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertEqual(result['effsize_type'], "eta squared")
        self.assertEqual(result['test'], 'Kruskal–Wallis test')

    def test_cont_cont(self):
        phenotypes_cont = pd.DataFrame({
            'pheno1': [1.0, 2.0, 3.0, 4.0],
            'pheno2': [14.0, 23.0, 44.0, 111.0]})
        pair_cont_cont = ('pheno1', 'pheno2')

        # Case 1: parametric Pearson correlation test
        result = cont_cont(pair_cont_cont, phenotypes_cont, test='parametric')

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertEqual(result['effsize_type'], 'correlation')
        self.assertEqual(result['test'], 'Pearson correlation')

        # Case 2: non-parametric Spearman´s rank correlation test
        result = cont_cont(pair_cont_cont, phenotypes_cont, test='non-parametric')

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertEqual(result['effsize_type'], 'correlation')
        self.assertEqual(result['test'], 'Spearman´s rank correlation')

    def test_calculate_association_scores(self):
        # Case 1: run without proteins and metabolites
        phenotypes = pd.DataFrame({
            'id': [1, 2, 3, 4],
            'pheno1': ['large', 'small', 'large', 'small'],
            'pheno2': [1.0, 2.0, 3.0, 4.0],
            'pheno3': ['high', 'high', 'low', 'low'],
            'pheno4': [True, False, False, True],
            'pheno5': [12, 22, 41, 78]
        })
        phenotypes_meta = pd.DataFrame({
            'label': ['pheno1', 'pheno2', 'pheno3', 'pheno4', 'pheno5'],
            'type': ['categorical', 'float', 'categorical', 'boolean', 'integer']
        })
        result = calculate_association_scores(phenotypes, phenotypes_meta, id_column='id')

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertIn('effsize_type', result)
        self.assertIn('test', result)
        self.assertIn('adj_pval', result)

        # Case 2: run with proteins and metabolites
        phenotypes = pd.DataFrame({
            'id': [1, 2, 3, 4],
            'pheno1': ['large', 'small', 'large', 'small'],
            'pheno2': [1.0, 2.0, 3.0, 4.0],
            'pheno3': ['high', 'high', 'low', 'low'],
            'pheno4': [True, False, False, True],
            'pheno5': [12, 22, 41, 78]
        })
        phenotypes_meta = pd.DataFrame({
            'label': ['pheno1', 'pheno2', 'pheno3', 'pheno4', 'pheno5'],
            'type': ['categorical', 'float', 'categorical', 'boolean', 'integer']
        })
        proteins = pd.DataFrame({
            'id': [4, 3, 1, 2],
            'prot1': [22.3, 11.4, 35.1, 28.5],
            'prot2': [2.3, 4.7, 3.4, 1.2]
        })
        metabolites = pd.DataFrame({
            'id': [2, 3, 1, 4],
            'prot1': [10.2, 8.9, 22.2, 19.9],
            'prot2': [67.0, 111.5, 98.6, 72.4]
        })
        result = calculate_association_scores(phenotypes, phenotypes_meta, id_column='id',
                                              proteins=proteins, metabolites=metabolites)

        self.assertIn('label1', result)
        self.assertIn('label2', result)
        self.assertIn('pval', result)
        self.assertIn('effsize', result)
        self.assertIn('effsize_type', result)
        self.assertIn('test', result)
        self.assertIn('adj_pval', result)


class CheckFilesTestCase(TestCase):

    def test_check_files(self):
        # TODO: Replace paths to our data by something else, maybe we should include a demo dataset that we can use for testing
        # Case 1: Unknown ID column
        path = "/nfs/scratch/DyHealthNet/chris_summary_data/fully_simulated/phenotypes_filtered.csv"
        with self.assertRaises(KeyError):
            check_files(path, check_id=True, id_column="ID")

        # Case 2: Unsupported file format
        path = "/nfs/scratch/DyHealthNet/chris_summary_data/fully_simulated/phenotypes_filtered.txt"
        with self.assertRaises(ValueError):
            check_files(path, check_id=False)

        # Case 3: Regular run with ID check
        path = "/nfs/scratch/DyHealthNet/chris_summary_data/fully_simulated/metabolites.csv"
        result = check_files(path, check_id=True, id_column="Patient ID")
        self.assertFalse(result.empty)

# class GetVariablesViewTestCases(TestCase):
#     def test_user_detail(self):
#         url = reverse('user_detail', args=[self.user.id])
#         response = self.client.get(url)
#
#         # Check the status code
#         self.assertEqual(response.status_code, 200)
#
#         # Check individual fields
#         response_data = response.json()  # Parse JSON response
#         self.assertEqual(response_data['id'], self.user.id)
#         self.assertEqual(response_data['username'], 'testuser')
#         self.assertEqual(response_data['email'], 'test@example.com')

class URLTestCase(SimpleTestCase):

    def test_get_variables_url(self):
        url = reverse('network:get_variables')
        self.assertEqual(url, '/network/api/variables/')
        self.assertEqual(resolve(url).func.view_class, GetVariablesView)

    def test_get_plot_data_url(self):
        url = reverse('network:get_plot_data')
        self.assertEqual(url, '/network/api/plotData/')
        self.assertEqual(resolve(url).func.view_class, GetDataView)

    def test_get_boxplot_data_url(self):
        url = reverse('network:get_boxplot_data')
        self.assertEqual(url, '/network/api/plotDataBoxPlot/')
        self.assertEqual(resolve(url).func.view_class, GetDataBoxPlotView)

    def test_get_heatmap_data_url(self):
        url = reverse('network:get_heatmap_data')
        self.assertEqual(url, '/network/api/plotDataHeatmap/')
        self.assertEqual(resolve(url).func.view_class, GetDataHeatmapView)

    def test_get_network_url(self):
        url = reverse('network:get_network')
        self.assertEqual(url, '/network/api/getNetwork/')
        self.assertEqual(resolve(url).func.view_class, GetNetworkView)

    def test_get_typeahead_url(self):
        url = reverse('network:get_typeahead')
        self.assertEqual(url, '/network/api/getTypeaheadResults/')
        self.assertEqual(resolve(url).func.view_class, TypeaheadView)

class URLStatusCodeTestCase(TestCase):
    def test_get_variables_url_status_code(self):
        response = self.client.get(reverse('network:get_variables'))
        self.assertEqual(response.status_code, 200)

    def test_get_plot_data_url_status_code(self):
        url = reverse('network:get_plot_data')
        response = self.client.get(f'{url}?x=Pacemaker/implantable%20defibrillator%20(x0af11)&y=Sniffin%20Stick%20%231%20(Orange)%20(x0ol01)&c=Sex%20(x0_sex)')
        self.assertEqual(response.status_code, 200)

    def test_get_boxplot_data_url_status_code(self):
        url = reverse('network:get_boxplot_data')
        response = self.client.get(f'{url}?x=Pacemaker/implantable%20defibrillator%20(x0af11)&y=Sniffin%20Stick%20%231%20(Orange)%20(x0ol01)&c=Sex%20(x0_sex)')
        self.assertEqual(response.status_code, 200)

    def test_get_heatmap_data_url_status_code(self):
        url = reverse('network:get_heatmap_data')
        response = self.client.get(f'{url}?x=Pacemaker/implantable%20defibrillator%20(x0af11)&y=Sniffin%20Stick%20%231%20(Orange)%20(x0ol01)')
        self.assertEqual(response.status_code, 200)

    # TODO need temp database and entries for that
    # def test_get_network_url_status_code(self):
    #     url = reverse('network:get_network')
    #     response = self.client.get(f'{url}?q=x0rd09&t=phenotype&l=10')
    #     self.assertEqual(response.status_code, 200)
    #
    # def test_get_typeahead_url_status_code(self):
    #     url = reverse('network:get_typeahead')
    #     response = self.client.get(f'{url}?s=Bec')
    #     self.assertEqual(response.status_code, 200)

    def test_nonexistent_url_status_code(self):
        response = self.client.get('/nonexistent/')
        self.assertEqual(response.status_code, 404)