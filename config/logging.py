import structlog

from config.installed_apps import get_installed_apps


def get_logging_module_names(*, base_apps: list[str]):
    return base_apps + get_installed_apps()


def get_structlog_renderer(*, debug: bool):
    if debug:
        return structlog.dev.ConsoleRenderer(colors=True)
    return structlog.processors.JSONRenderer()


def get_console_handler(*, log_level: str):
    return {
        "class": "logging.StreamHandler",
        "formatter": "structlog",
        "level": log_level,
    }


def get_shared_processors():
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]


def configure_structlog(*, shared_processors: list):
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logging_config(*, debug: bool, log_level: str, base_apps: list[str]):
    shared_processors = get_shared_processors()
    foreign_pre_chain = [
        *shared_processors,
        structlog.stdlib.ExtraAdder(),
    ]

    configure_structlog(shared_processors=shared_processors)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structlog": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.format_exc_info,
                    get_structlog_renderer(debug=debug),
                ],
                "foreign_pre_chain": foreign_pre_chain,
            },
        },
        "handlers": {
            "console": get_console_handler(log_level=log_level),
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "loggers": {
            "django": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            **{
                app_name: {
                    "handlers": ["console"],
                    "level": log_level,
                    "propagate": False,
                }
                for app_name in get_logging_module_names(base_apps=base_apps)
            },
        },
    }
