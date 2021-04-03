import os
import sentry_sdk
from dotenv import load_dotenv

# Load env from .env if possible.
load_dotenv(verbose=True)
SENTRY_LINK = os.environ.get("SENTRY_LINK")

sentry_sdk.init(SENTRY_LINK, release="urban-robot@0.0.1", traces_sample_rate=1.0)

division_by_zero = 1 / 0
