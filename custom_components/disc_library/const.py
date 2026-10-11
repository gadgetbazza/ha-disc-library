"""Constants for Disc Library."""

DOMAIN = "disc_library"
CONF_PLAYERS = "players"
CONF_INDEX = "index"
CONF_INDEX_URL = "index_url"
DEFAULT_INDEX = "disc_library/index.json"
# Rebuilt weekly from TheDiscDB by this repo's GitHub Action; checked daily
DEFAULT_INDEX_URL = "https://raw.githubusercontent.com/gadgetbazza/ha-disc-library/main/data/index.json"
STORAGE_KEY = "disc_library.discs"
STORAGE_VERSION = 1

TMDB_IMAGE = "https://image.tmdb.org/t/p/"

# Oppo disc_type values -> index format
DISC_FORMATS = {"uhd bluray": "uhd", "bluray": "bd", "blu-ray": "bd", "dvd": "dvd"}

# A title shorter than this is a menu loop, trailer or extra, not the film
MIN_FEATURE_SECONDS = 45 * 60
