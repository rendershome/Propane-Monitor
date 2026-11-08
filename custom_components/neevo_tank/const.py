"""Constants for the Nee-Vo Tank Monitor integration."""

from datetime import timedelta

DOMAIN = "neevo_tank"

# Monitors report about once a day, so polling more often gains little.
UPDATE_INTERVAL = timedelta(hours=6)

# Keep showing the last good data through a short outage, because one failed
# poll would otherwise blank every sensor until the next poll.
FAILURE_GRACE = timedelta(hours=24)

# How long to wait before contacting Nee-Vo again after a failed setup.
SETUP_RETRY_FIRST_WAIT = timedelta(minutes=15)
SETUP_RETRY_LONGEST_WAIT = timedelta(hours=4)

# When a monitor's last reading counts as overdue.
READING_OVERDUE_AFTER = timedelta(hours=48)

# How old a history entry can be and still be used as the current level.
HISTORY_FRESH_FOR = timedelta(hours=36)

# Window and minimum span for the average consumption rate.
RATE_WINDOW_DAYS = 30
RATE_MINIMUM_DAYS = 7

STORAGE_VERSION = 1
STORAGE_SAVE_DELAY = 30

MANUFACTURER = "Otodata"
MODEL = "Nee-Vo Tank Monitor"
