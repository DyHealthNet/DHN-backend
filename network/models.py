from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.contrib.auth.models import User
from django.apps import apps

# 'Cohort' models correspond to CHRIS nodes
class CohortMetabolite(models.Model):
    cohort_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_metabolite'


class CohortPhenotype(models.Model):
    cohort_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_phenotype'


class CohortProtein(models.Model):
    cohort_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_protein'


class CohortVariant(models.Model):
    cohort_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_variant'


# Other nodes correspond to external data
class Disorder(models.Model):
    mondo_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'disorder'


class Gene(models.Model):
    entrez_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    synonyms = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    chromosome = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gene'


class GenomicVariant(models.Model):
    clinvar_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    alternative_sequence = models.CharField(max_length=200, blank=True, null=True)
    chromosome = models.CharField(max_length=200, blank=True, null=True)
    data_sources = models.CharField(max_length=200, blank=True, null=True)
    xrefs = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    position = models.CharField(max_length=200, blank=True, null=True)
    reference_sequence = models.CharField(max_length=200, blank=True, null=True)
    type = models.CharField(max_length=200, blank=True, null=True)
    variant_type = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'genomic_variant'


class Metabolite(models.Model):
    hmdb_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    synonyms = models.CharField(max_length=200, blank=True, null=True)
    xrefs = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'metabolite'


class Phenotype(models.Model):
    hpo_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    xrefs = ArrayField(
        models.CharField(max_length=50, blank=True, null=True),
    )
    synonyms = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'phenotype'


class Protein(models.Model):
    uniprot_id = models.CharField(primary_key=True, max_length=200, db_index=True)
    display_name = models.CharField(max_length=200, blank=True, null=True)
    sequence = models.CharField(max_length=200, blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, null=True)
    observation_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'protein'


# 'Associates' models correspond to externally verified associations between nodes
class DisorderAssociatesPhenotype(models.Model):
    id = models.IntegerField(null=False, blank=False, primary_key=True, db_index=True)
    mondo_id = models.ForeignKey('Disorder', models.DO_NOTHING, blank=True, null=True)
    hpo_id = models.ForeignKey('Phenotype', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'disorder_associates_phenotype'


class GeneAssociatesDisorder(models.Model):
    id = models.IntegerField(null=False, blank=False, primary_key=True, db_index=True)
    entrez_id = models.ForeignKey('Gene', models.DO_NOTHING, blank=True, null=True)
    mondo_id = models.ForeignKey('Disorder', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gene_associates_disorder'


class MetaboliteAssociatesDisorder(models.Model):
    id = models.IntegerField(null=False, blank=False, primary_key=True, db_index=True)
    hmdb_id = models.ForeignKey('Metabolite', models.DO_NOTHING, blank=True, null=True)
    mondo_id = models.ForeignKey('Disorder', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'metabolite_associates_disorder'


class ProteinAssociatesMetabolite(models.Model):
    id = models.IntegerField(null=False, blank=False, primary_key=True, db_index=True)
    uniprot_id = models.ForeignKey('Protein', models.DO_NOTHING, blank=True, null=True)
    hmdb_id = models.ForeignKey('Metabolite', models.DO_NOTHING, blank=True, null=True)
    edge_source = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'protein_associates_metabolite'


class ProteinAssociatesProtein(models.Model):
    id = models.IntegerField(null=False, blank=False, primary_key=True, db_index=True)
    uniprot_id_1 = models.ForeignKey('Protein', models.DO_NOTHING, db_column='uniprot_id_1', blank=True, null=True,
                                     related_name='protein_1')
    uniprot_id_2 = models.ForeignKey('Protein', models.DO_NOTHING, db_column='uniprot_id_2', blank=True, null=True,
                                     related_name='protein_2')

    class Meta:
        managed = False
        db_table = 'protein_associates_protein'


class ProteinAssociatesGene(models.Model):
    id = models.IntegerField(null=False, blank=False, primary_key=True, db_index=True)
    uniprot_id = models.ForeignKey('Protein', models.DO_NOTHING, blank=True, null=True)
    entrez_id = models.ForeignKey('Gene', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'protein_associates_gene'


class VariantAssociatesGene(models.Model):
    id = models.IntegerField(null=False, blank=False, primary_key=True, db_index=True)
    clinvar_id = models.ForeignKey('GenomicVariant', models.DO_NOTHING, blank=True, null=True)
    entrez_id = models.ForeignKey('Gene', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'variant_associates_gene'


# 'Edges' models correspond to edges between CHRIS nodes with calculated association scores
class EdgesMetaboliteMetabolite(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    metabolite_1 = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, db_column='metabolite_id_1', blank=True,
                                     null=True,
                                     related_name='cohort_metabolite_1')
    metabolite_2 = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, db_column='metabolite_id_2', blank=True,
                                     null=True,
                                     related_name='cohort_metabolite_2')
    pearson_p_unadjusted = models.FloatField(blank=True, null=True)
    pearson_p_bonferroni = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_hb = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_yek = models.FloatField(blank=True, null=True)
    pearson_e_r2 = models.FloatField(blank=True, null=True)

    spearman_p_unadjusted = models.FloatField(blank=True, null=True)
    spearman_p_bonferroni = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_hb = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_yek = models.FloatField(blank=True, null=True)
    spearman_e_rho = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_metabolite_metabolite'
        abstract = True


class EdgesMetabolitePhenotype(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    metabolite = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, blank=True, null=True,
                                   db_column='metabolite_id')
    phenotype = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True, db_column='phenotype_id')

    ttest_p_unadjusted = models.FloatField(blank=True, null=True)
    ttest_p_bonferroni = models.FloatField(blank=True, null=True)
    ttest_p_benjamini_hb = models.FloatField(blank=True, null=True)
    ttest_p_benjamini_yek = models.FloatField(blank=True, null=True)
    ttest_e_cohens_d = models.FloatField(blank=True, null=True)

    anova_p_unadjusted = models.FloatField(blank=True, null=True)
    anova_p_bonferroni = models.FloatField(blank=True, null=True)
    anova_p_benjamini_hb = models.FloatField(blank=True, null=True)
    anova_p_benjamini_yek = models.FloatField(blank=True, null=True)
    anova_e_np2 = models.FloatField(blank=True, null=True)

    mwu_p_unadjusted = models.FloatField(blank=True, null=True)
    mwu_p_bonferroni = models.FloatField(blank=True, null=True)
    mwu_p_benjamini_hb = models.FloatField(blank=True, null=True)
    mwu_p_benjamini_yek = models.FloatField(blank=True, null=True)
    mwu_e_r = models.FloatField(blank=True, null=True)

    kruskal_p_unadjusted = models.FloatField(blank=True, null=True)
    kruskal_p_bonferroni = models.FloatField(blank=True, null=True)
    kruskal_p_benjamini_hb = models.FloatField(blank=True, null=True)
    kruskal_p_benjamini_yek = models.FloatField(blank=True, null=True)
    kruskal_e_eta2 = models.FloatField(blank=True, null=True)

    pearson_p_unadjusted = models.FloatField(blank=True, null=True)
    pearson_p_bonferroni = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_hb = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_yek = models.FloatField(blank=True, null=True)
    pearson_e_r2 = models.FloatField(blank=True, null=True)

    spearman_p_unadjusted = models.FloatField(blank=True, null=True)
    spearman_p_bonferroni = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_hb = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_yek = models.FloatField(blank=True, null=True)
    spearman_e_rho = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_metabolite_phenotype'
        abstract = True


class EdgesPhenotypePhenotype(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    phenotype_1 = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, db_column='phenotype_id_1', blank=True,
                                    null=True,
                                    related_name='cohort_phenotype_1')
    phenotype_2 = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, db_column='phenotype_id_2', blank=True,
                                    null=True,
                                    related_name='cohort_phenotype_2')

    chi2_p_unadjusted = models.FloatField(blank=True, null=True)
    chi2_p_bonferroni = models.FloatField(blank=True, null=True)
    chi2_p_benjamini_hb = models.FloatField(blank=True, null=True)
    chi2_p_benjamini_yek = models.FloatField(blank=True, null=True)
    chi2_e_cramers_v = models.FloatField(blank=True, null=True)
    chi2_e_phi = models.FloatField(blank=True, null=True)

    ttest_p_unadjusted = models.FloatField(blank=True, null=True)
    ttest_p_bonferroni = models.FloatField(blank=True, null=True)
    ttest_p_benjamini_hb = models.FloatField(blank=True, null=True)
    ttest_p_benjamini_yek = models.FloatField(blank=True, null=True)
    ttest_e_cohens_d = models.FloatField(blank=True, null=True)

    anova_p_unadjusted = models.FloatField(blank=True, null=True)
    anova_p_bonferroni = models.FloatField(blank=True, null=True)
    anova_p_benjamini_hb = models.FloatField(blank=True, null=True)
    anova_p_benjamini_yek = models.FloatField(blank=True, null=True)
    anova_e_np2 = models.FloatField(blank=True, null=True)

    mwu_p_unadjusted = models.FloatField(blank=True, null=True)
    mwu_p_bonferroni = models.FloatField(blank=True, null=True)
    mwu_p_benjamini_hb = models.FloatField(blank=True, null=True)
    mwu_p_benjamini_yek = models.FloatField(blank=True, null=True)
    mwu_e_r = models.FloatField(blank=True, null=True)

    kruskal_p_unadjusted = models.FloatField(blank=True, null=True)
    kruskal_p_bonferroni = models.FloatField(blank=True, null=True)
    kruskal_p_benjamini_hb = models.FloatField(blank=True, null=True)
    kruskal_p_benjamini_yek = models.FloatField(blank=True, null=True)
    kruskal_e_eta2 = models.FloatField(blank=True, null=True)

    pearson_p_unadjusted = models.FloatField(blank=True, null=True)
    pearson_p_bonferroni = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_hb = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_yek = models.FloatField(blank=True, null=True)
    pearson_e_r2 = models.FloatField(blank=True, null=True)

    spearman_p_unadjusted = models.FloatField(blank=True, null=True)
    spearman_p_bonferroni = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_hb = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_yek = models.FloatField(blank=True, null=True)
    spearman_e_rho = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_phenotype_phenotype'
        abstract = True


class EdgesProteinMetabolite(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    protein = models.ForeignKey('CohortProtein', models.DO_NOTHING, blank=True, null=True, db_index=True,
                                db_column='protein_id')
    metabolite = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, blank=True, null=True,
                                   db_column='metabolite_id')

    pearson_p_unadjusted = models.FloatField(blank=True, null=True)
    pearson_p_bonferroni = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_hb = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_yek = models.FloatField(blank=True, null=True)
    pearson_e_r2 = models.FloatField(blank=True, null=True)

    spearman_p_unadjusted = models.FloatField(blank=True, null=True)
    spearman_p_bonferroni = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_hb = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_yek = models.FloatField(blank=True, null=True)
    spearman_e_rho = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_protein_metabolite'
        abstract = True


class EdgesProteinPhenotype(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    protein = models.ForeignKey('CohortProtein', models.DO_NOTHING, blank=True, null=True, db_index=True,
                                db_column='protein_id')
    phenotype = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True, db_column='phenotype_id')

    ttest_p_unadjusted = models.FloatField(blank=True, null=True)
    ttest_p_bonferroni = models.FloatField(blank=True, null=True)
    ttest_p_benjamini_hb = models.FloatField(blank=True, null=True)
    ttest_p_benjamini_yek = models.FloatField(blank=True, null=True)
    ttest_e_cohens_d = models.FloatField(blank=True, null=True)

    anova_p_unadjusted = models.FloatField(blank=True, null=True)
    anova_p_bonferroni = models.FloatField(blank=True, null=True)
    anova_p_benjamini_hb = models.FloatField(blank=True, null=True)
    anova_p_benjamini_yek = models.FloatField(blank=True, null=True)
    anova_e_np2 = models.FloatField(blank=True, null=True)

    mwu_p_unadjusted = models.FloatField(blank=True, null=True)
    mwu_p_bonferroni = models.FloatField(blank=True, null=True)
    mwu_p_benjamini_hb = models.FloatField(blank=True, null=True)
    mwu_p_benjamini_yek = models.FloatField(blank=True, null=True)
    mwu_e_r = models.FloatField(blank=True, null=True)

    kruskal_p_unadjusted = models.FloatField(blank=True, null=True)
    kruskal_p_bonferroni = models.FloatField(blank=True, null=True)
    kruskal_p_benjamini_hb = models.FloatField(blank=True, null=True)
    kruskal_p_benjamini_yek = models.FloatField(blank=True, null=True)
    kruskal_e_eta2 = models.FloatField(blank=True, null=True)

    pearson_p_unadjusted = models.FloatField(blank=True, null=True)
    pearson_p_bonferroni = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_hb = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_yek = models.FloatField(blank=True, null=True)
    pearson_e_r2 = models.FloatField(blank=True, null=True)

    spearman_p_unadjusted = models.FloatField(blank=True, null=True)
    spearman_p_bonferroni = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_hb = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_yek = models.FloatField(blank=True, null=True)
    spearman_e_rho = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_protein_phenotype'
        abstract = True


class EdgesProteinProtein(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    protein_1 = models.ForeignKey('CohortProtein', models.DO_NOTHING, db_column='protein_id_1', blank=True, null=True,
                                  related_name='cohort_protein_1', db_index=True)
    protein_2 = models.ForeignKey('CohortProtein', models.DO_NOTHING, db_column='protein_id_2', blank=True, null=True,
                                  related_name='cohort_protein_2', db_index=True)

    pearson_p_unadjusted = models.FloatField(blank=True, null=True)
    pearson_p_bonferroni = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_hb = models.FloatField(blank=True, null=True)
    pearson_p_benjamini_yek = models.FloatField(blank=True, null=True)
    pearson_e_r2 = models.FloatField(blank=True, null=True)

    spearman_p_unadjusted = models.FloatField(blank=True, null=True)
    spearman_p_bonferroni = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_hb = models.FloatField(blank=True, null=True)
    spearman_p_benjamini_yek = models.FloatField(blank=True, null=True)
    spearman_e_rho = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_protein_protein'
        abstract = True


class EdgesVariantMetabolite(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    metabolite = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, blank=True, null=True,
                                   db_column='metabolite_id')
    variant = models.ForeignKey('CohortVariant', models.DO_NOTHING, blank=True, null=True, db_column='variant_id')

    gwas_p_unadjusted = models.FloatField(blank=True, null=True)
    gwas_p_bonferroni = models.FloatField(blank=True, null=True)
    gwas_e_unspecified = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_variant_metabolite'
        abstract = True


class EdgesVariantPhenotype(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    phenotype = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True, db_column='phenotype_id')
    variant = models.ForeignKey('CohortVariant', models.DO_NOTHING, blank=True, null=True, db_column='variant_id')

    gwas_p_unadjusted = models.FloatField(blank=True, null=True)
    gwas_p_bonferroni = models.FloatField(blank=True, null=True)
    gwas_e_unspecified = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_variant_phenotype'
        abstract = True


class EdgesVariantProtein(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    protein = models.ForeignKey('CohortProtein', models.DO_NOTHING, blank=True, null=True, db_column='protein_id')
    variant = models.ForeignKey('CohortVariant', models.DO_NOTHING, blank=True, null=True, db_column='variant_id')

    gwas_p_unadjusted = models.FloatField(blank=True, null=True)
    gwas_p_bonferroni = models.FloatField(blank=True, null=True)
    gwas_e_unspecified = models.FloatField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'edges_variant_protein'
        abstract = True


# 'References' edges map CHRIS nodes to external nodes
class CohortReferencesMetabolite(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    cohort_id = models.ForeignKey('CohortMetabolite', models.DO_NOTHING, blank=True, null=True)
    hmdb_id = models.ForeignKey('Metabolite', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_metabolite'


class CohortReferencesDisease(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    cohort_id = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True)
    mondo_id = models.ForeignKey('Disorder', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_disease'


class CohortReferencesPhenotype(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    cohort_id = models.ForeignKey('CohortPhenotype', models.DO_NOTHING, blank=True, null=True)
    hpo_id = models.ForeignKey('Phenotype', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_phenotype'


class CohortReferencesProtein(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    cohort_id = models.ForeignKey('CohortProtein', models.DO_NOTHING, blank=True, null=True)
    uniprot_id = models.ForeignKey('Protein', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_protein'


class CohortReferencesVariant(models.Model):
    id = models.IntegerField(primary_key=True, db_index=True)
    cohort_id = models.ForeignKey('CohortVariant', models.DO_NOTHING, blank=True, null=True)
    clinvar_id = models.ForeignKey('GenomicVariant', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cohort_references_variant'


# add model for all contexts so we can keep track of them
class Context(models.Model):
    context_id = models.IntegerField(primary_key=True, db_column='context_id')
    cat_cat_test = models.CharField(max_length=200, blank=True, null=True)
    cont_cont_test = models.CharField(max_length=200, blank=True, null=True)
    cat_cont_b_test = models.CharField(max_length=200, blank=True, null=True)
    cat_cont_m_test = models.CharField(max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_accessed = models.DateTimeField(blank=True, null=True)
    params = models.JSONField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'context'


# Views combining several tables
class ViewDescriptionFTS(models.Model):
    id = models.CharField(primary_key=True, max_length=200, db_column='id')
    description = models.CharField(blank=True, null=True, db_column='description', max_length=200)
    display_name = models.CharField(blank=True, null=True, db_column='display_name', max_length=200)
    source_table = models.TextField(blank=True, null=True, db_column='source_table')
    xrefs = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'view_description_fts'


class ViewAssociationsEdges(models.Model):
    source_id = models.CharField(primary_key=True, blank=True, max_length=200, db_column='source_id', db_index=True)
    target_id = models.CharField(blank=True, null=True, max_length=200, db_column='target_id', db_index=True)

    class Meta:
        managed = False
        db_table = 'view_associations_edges'


class ViewReferencesEdges(models.Model):
    source_table = models.TextField(blank=True, null=True)
    cohort_id = models.CharField(primary_key=True, blank=True, max_length=200, db_column='cohort_id')
    reference_id = models.CharField(blank=True, null=True, max_length=200, db_column='reference_id')

    class Meta:
        managed = False
        db_table = 'view_references_edges'


class ViewExternalNodes(models.Model):
    node_id = models.CharField(primary_key=True, blank=True, max_length=200, db_column='node_id')
    source_table = models.TextField(blank=True, null=True, db_column='source_table')

    class Meta:
        managed = False
        db_table = 'view_external_nodes'


class UserContextLink(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("FINISHED", "Finished"),
    ]
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)
    context = models.ForeignKey(Context,  blank=True, null=True, on_delete=models.CASCADE)
    #context_id = models.CharField(blank=True, max_length=200, db_column='context_id')
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    context_value = models.IntegerField(blank=True, null=True)
    context_task_id = models.CharField(blank=True, max_length=200)
    context_status = models.CharField(blank=True, max_length=200, choices=STATUS_CHOICES, default="Pending")

    class Meta:
        managed = True
        db_table = 'user_context'


def create_dynamic_model(base_model, table_name, registry={}):
    """
    Create a dynamic model based on the specified base model and table name.
    :param base_model: The base model class to inherit from.
    :param table_name: The name of the database table.
    :return: A dynamically created model.
    """

    class DynamicModel(base_model):
        class Meta:
            db_table = table_name
            managed = False

    # Store the model in the registry
    registry[table_name] = DynamicModel

    return DynamicModel
