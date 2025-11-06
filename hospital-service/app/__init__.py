from dotenv import load_dotenv, find_dotenv
import warnings

# Suppress Pydantic v2 migration warning about `orm_mode` -> `from_attributes`.
# This project uses Pydantic v1 and FastAPI; the warning is non-fatal but
# noisy. Keep this filter until a full migration to Pydantic v2 is done.
warnings.filterwarnings(
	"ignore",
	message=r"Valid config keys have changed in V2:.*orm_mode.*",
	category=UserWarning,
)

# Centralize environment loading for the `app` package. This ensures
# any module that imports `app` will have the .env values available.
load_dotenv(find_dotenv())

__all__ = []
