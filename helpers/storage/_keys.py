"""The bucket's top-level prefixes, one per kind of file the app keeps there."""

#: Uploaded and synced worksheet files.
WORKSHEET_PREFIX = "worksheets/"
#: Generated question audio (helpers/audio_cache.py).
AUDIO_PREFIX = "audio/"
#: Public images: article heroes and school photos (helpers/images.py).
IMAGE_PREFIX = "images/"
