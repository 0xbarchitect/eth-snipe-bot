# Supervisord
Keep long running process

## Dependencies
- Python 3.11 (by conda)

# Install dependencies
```sh
$ pip install supervisor
```

# Start
Run following command from project folder
```sh
$ supervisord -c ./devops/supervisord.conf
```

# Manage
```sh
$ supervisorctl
```
