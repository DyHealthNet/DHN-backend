# Use an official Python runtime as the parent image.
FROM python:3.11.9-slim

# Set environment variables for proper locale and unbuffered output.
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory to /app in the container.
WORKDIR /app

# Copy the "requirements.txt" file from your host machine into the image's "/app" folder.
COPY backend/requirements.txt /app

# Install any needed packages specified in "requirements.txt".
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the Django project files to the container's "/app" directory, maintaining proper permissions and ownership.
COPY backend/ /app/
COPY database /app/database
RUN mkdir /app/staticfiles

# Set up environment variables for Django settings file, static files location, etc.
ENV DJANGO_SETTINGS_MODULE=dyhealthnet_project.settings
# ENV STATIC_ROOT=/app/staticfiles

# Run collectstatic command to prepare static files for production.
# RUN python manage.py collectstatic --no-input

# Expose port 8000 for the WSGI server (you can change this if you use a different port).
EXPOSE 8000

# Start the Gunicorn WSGI server to serve your Django app on all available network interfaces.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "dyhealthnet_project.wsgi:application"]
