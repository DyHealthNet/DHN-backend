import sys

import pandas as pd
import re
import numpy as np
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes, OpenApiExample
from rest_framework import generics
from django.http import JsonResponse, HttpResponseBadRequest
from network.models import CohortVariant, UserContextLink, Context
from network.color_utils import *
from django.contrib.auth import authenticate, login, logout  #Authentication models & functions
from django.contrib.auth.models import auth, Group, User  # Authentication models & functions
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

import json

from rest_framework.views import APIView

from network.score_calculation import separate_cat_cont
from network.utils import check_files_and_return, list_node_variables
from network.contexts.contexts import subset_patients, create_context_id, delete_context_tables
from network.tasks import create_context_wrapper, test_task
import os
import environ
import logging
from celery.result import AsyncResult


logger = logging.getLogger('network')


# Don't try to load data if runserver is not requested
