# gunicorn.config.py

# Bind to all interfaces on port 8000
bind = "0.0.0.0:8000"

# Number of worker processes (based on CPU cores)
workers = 3  # Adjust based on the number of available CPUs

# Worker class for handling ASGI applications
worker_class = "uvicorn.workers.UvicornWorker"

# Set the timeout to handle long-running requests
timeout = 3000  # Increase timeout to 120 seconds

# Graceful timeout for workers to complete tasks on shutdown
graceful_timeout = 3000

# Temporary directory for Gunicorn workers
worker_tmp_dir = "/dev/shm"

# Log level for debugging and performance monitoring
loglevel = "info"

# Maximum number of simultaneous connections per worker
worker_connections = 1000
