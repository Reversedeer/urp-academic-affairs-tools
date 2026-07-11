# URP Tools

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/Reversedeer/urp-academic-affairs-tools#Apache-2.0-1-ov-file)
[![PyPI](https://img.shields.io/pypi/v/urp-tools.svg)](https://pypi.org/project/urp-tools/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Code style: Ruff](https://img.shields.io/badge/code%20style-Ruff-46a2f1.svg)](https://docs.astral.sh/ruff/)
[![Code style: Black](https://img.shields.io/badge/code%20style-Black-000000.svg)](https://github.com/psf/black)

## Features

- Async login with captcha recognition and retry support
- Timetable export to Excel
- Teaching evaluation preview, selection, confirmation, and submission
- Supports previewing the course list for booking courses and supports course cancellation.

## Requirements

- Python `>=3.10,<3.11`
- Poetry `2.x` for development

> [!CAUTION]
>
> The current goal of this project is to be used on `jws.qgxy.cn`

## Installation

#### PyPI

```bash
pip install urp-tools
```

#### Install from source code

```bash
git clone https://github.com/Reversedeer/urp-academic-affairs-tools.git
cd urp-academic-affairs-tools
poetry install
```

## Configuration

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

## Environment

| Variable | Description | Must | Default |
| --- | --- | --- | --- |
| `URP_BASE_URL` | URP base URL | Yes | `https://jws.qgxy.cn` |
| `URP_USERNAME` | Login username | Yes  | null                       |
| `URP_PASSWORD` | Login password | Yes  | null |
| `URP_DEFAULT_CHOICE` | Default evaluation choice | No | `A` |
| `URP_DEFAULT_COMMENT` | Default evaluation comment | No | `老师教学认真课程收获较大` |
| `URP_EVALUATION_WAIT_SECONDS` | Wait time before evaluation submission | No | `120` |
| `URP_EVALUATION_LIMIT` | Optional submission limit for evaluation | No | null                       |
| `URP_EVALUATION_CONCURRENCY` | Evaluation open/submit concurrency | No | `3` |

## Usage

### Run with Poetry

```bash
#Run with Poetry
poetry run urp-tools
#Run as a module
poetry run python -m urp_academic_affairs_tools.main
#Run directly from source
python urp_academic_affairs_tools/main.py
```

> [!NOTE]
>
> - Due to server limitations, teaching evaluations require a 120-second submission wait.
>
> - Successful course selection still depends on system availability. To ensure a higher success rate, please submit repeatedly until confirmed.



## License

This project is licensed under the [Apache-2.0 License](https://github.com/Reversedeer/urp-academic-affairs-tools#Apache-2.0-1-ov-file).
