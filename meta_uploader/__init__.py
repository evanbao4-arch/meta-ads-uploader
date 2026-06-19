"""Meta Ads Uploader.

A small CLI that takes a creative (from Google Drive, a URL, or a local file) and
creates a PAUSED, ready-to-go ad in your Meta ad account. It talks to the Meta
Marketing API over plain HTTPS — no SDK.

Nothing in this package ever turns an ad on or spends money: every ad and ad set
is created with status='PAUSED'. You review and launch in Ads Manager.
"""

__version__ = "0.1.0"
