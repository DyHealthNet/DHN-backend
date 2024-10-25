# backend_django
Django backend for the DyHealthNet Masters project (2024) to build a prototype for an interactive multi-omics network which aims to include both data from the Cooperative Health Research in South Tyrol (CHRIS) study and public data from external databases.

## Usage guide

1. Clone the repository using one of the following options:  
   ```bash
   git clone https://github.com/DyHealthNet/backend_django.git #https
   git clone git@github.com:DyHealthNet/backend_django.git #ssh

2. Create a conda environment including all package dependencies and activate it:   
   ```bash
   conda env create -f environment.yml -n dyhealthnet_env
   conda activate dyhealthnet_env

3. Set the secret key in the .env.example file manually and rename the file afterwards:
   ```bash
   cd backend_django/dyhealthnet_project
   vi .env.example #Edit secret key variable
   mv .env.example .env
   
4. Install and run redis server:
   ```bash
   sudo apt update && sudo apt install redis-server
   ```
   
5. Install and run celery worker:
   ```bash
   celery -A dyhealthnet_project worker -l info
   ```

6. Run the server and access it on your browser according to the instructions:  
   ```bash
   cd ..
   python manage.py runserver
   ```
   

## Format specifications

### Phenotypes

**Phenotypes are not optional.**

Your phenotype file must use columns as variables and rows as samples. 
One (usually the first) column must be the sample ID, specified by the `PATIENT_ID_COLUMN` variable in the `.env` file.
Furthermore, there must exist a meta file, which contains a column `PHENOTYPE_TYPE_COLUMN` which specifies the numeric 
type of the variable. Allowed types are `boolean`, `categorical`, `float` and `integer`. These types are used to 
determine the statistical tests that will be performed on the data.


### Proteins

**Proteins are optional.**

Your protein file must use columns as proteins and rows as samples.
Ensure that you have a consistent column with the sample ID, specified by the `PATIENT_ID_COLUMN` variable in the 
`.env` file.

### Metabolites

**Metabolites are optional.**

Your metabolite file must use columns as metabolites and rows as samples.
Ensure that you have a consistent column with the sample ID, specified by the `PATIENT_ID_COLUMN` variable in the 
`.env` file.