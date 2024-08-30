# PyREVM
Guideline on installation PyREVM.

## Prerequisites

- Python 3.11 virtual environment
- Rust

## Setup

> - Install pipx
```bash
$ pip install --user pipx
$ pipx ensurepath
```
> *might need to add ~/.local/bin to PATH env var in order to use pipx globally*

> - Install poetry
```bash
$ pipx install poetry
```

> - Install maturin
```bash
$ pipx install maturin
```

> - Build pyrevm
```bash
$ cd lib/pyrevm
$ make build
$ make test
```

## Run

- Trial test
```bash
$ python test.py
```