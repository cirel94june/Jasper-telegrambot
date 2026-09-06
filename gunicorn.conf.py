def post_fork(server, worker):
    """Start bot background jobs in the worker, never in Gunicorn's master."""
    import bot

    bot.start_runtime_background_tasks()

