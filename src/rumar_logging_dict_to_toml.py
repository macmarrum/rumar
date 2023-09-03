from pathlib import Path

import tomli_w

dict_config = {
    'version': 1,
    'formatters': {
        'formatter': {
            'format': '{levelShort} {asctime}: {funcName:24} {msg}',
            'style': '{',
            'validate': True,
        }
    },
    'handlers': {
        'to_console': {
            'class': 'logging.StreamHandler',
            'formatter': 'formatter',
            'level': 'DEBUG_14',
        },
        'to_file': {
            'class': 'logging.FileHandler',
            'filename': 'rumar.log',
            'encoding': 'UTF-8',
            'formatter': 'formatter',
            'level': 'DEBUG_14',
        }
    },
    'loggers': {
        'rumar': {
            'level': 'DEBUG_14',
            'handlers': ['to_console', 'to_file'],
        }
    }
}

with Path(__file__).with_suffix('.toml').open('wb') as rumar_toml:
    tomli_w.dump(dict_config, rumar_toml)

