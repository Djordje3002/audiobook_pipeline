web: gunicorn app:app --timeout 120 --workers 1 --worker-class gthread --threads 4
worker: rq worker --url $REDIS_URL pipeline
release: flask --app app db upgrade
