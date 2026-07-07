from django.test import TestCase
from network.utils import (
    multiprocess,
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