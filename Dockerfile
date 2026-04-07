# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /code

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Create necessary directories for local fallback (though Cloudinary is preferred)
RUN mkdir -p app/static/uploads/posts \
             app/static/uploads/avatars \
             app/static/uploads/zones \
             app/static/uploads/stories

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Render injects PORT at runtime (default 10000)
EXPOSE 10000

# Run the application — Render sets $PORT automatically
CMD gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-10000}
