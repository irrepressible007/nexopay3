"""gunicorn settings for the always-on app server (deploy/appserver.sh passes its flags on top)."""


def post_worker_init(worker):
    # Runs before the worker accepts visitors, so its first real visitor isn't the slow one.
    from bridge_wsgi import warm_up

    warm_up()
