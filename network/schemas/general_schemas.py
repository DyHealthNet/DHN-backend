from drf_spectacular.utils import extend_schema

variables_schema = extend_schema(
        summary="Returns all possible phenotype variables (+ protein & metabolite variables if provided) grouped by "
                "their type",
        description='Returns all possible phenotype variables grouped by their type in JSON format. '
                    'e.g. {"nonbinaryCategorical":["Happiness on Scale 1 to 10 (happiness_scale_id)"],'
                    '"binaryCategorical":["Disease XY (diseaseXY_id)"], '
                    '"countinous":["BMI (BMI_id)","Height in cm (Height_id)"]}'
    )