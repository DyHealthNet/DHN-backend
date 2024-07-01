# backend_django
Django backend for the DyHealthNet Masters project (2024) to build a prototype for an interactive multi-omics network which aims to include both data from the Cooperative Health Research in South Tyrol (CHRIS) study and public data from external databases.

## Usage guide

1. Create a conda environment including all package dependencies and activate it:   
   ```bash
   conda env create -f environment.yml -n dyhealthnet_env
   conda activate dyhealthnet_env
   
4. Clone the repository using one of the following options:  
   ```bash
   git clone https://github.com/DyHealthNet/backend_django.git #https
   git clone git@github.com:DyHealthNet/backend_django.git #ssh

6. Set the secret key in the .env.example file manually and rename the file afterwards:
   ```bash
   cd backend_django/dyhealthnet_project
   vi .env.example #Edit secret key variable
   mv .env.example .env
   
8. Run the server and access it on your browser according to the instructions:  
   ```bash
   cd ..
   python manage.py runserver`
   
